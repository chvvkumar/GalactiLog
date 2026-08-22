"""DB-backed tests for the FWHM unit fix and the timeline efficiency formula.

Guards two regressions in GET /api/stats:

1. Image.fwhm is already in arcseconds (NINA Session Metadata CSV). Equipment
   Inventory used to multiply it by the plate scale, so a rig at 2.94 arcsec/px
   reported an FWHM three times the one Equipment Performance showed. Both views
   must now report the same plain median over the same LIGHT frames, with alias
   spellings merged, and disclose how many frames carry an FWHM at all.

2. The timeline efficiency denominator used to be dark hours over the nights
   that had imaging, so N concurrent rigs could reach N x 100 percent. It is now
   dark hours times the rigs that took LIGHT frames that night, floored at one,
   summed over every date in the period.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied.
"""
import statistics
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models import Image
from app.models.site_dark_hours import SiteDarkHours
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.normalization import invalidate_alias_cache


TEST_DB_URL = settings.database_url

# Site used for the dark-hours lookup. Written into every frame's raw_headers
# so _extract_site_coords finds it, and used as the key of the dark-hours rows.
SITE_LAT = 33.0
SITE_LON = -96.0
DARK_HOURS = 8.0

NIGHT_1 = date(2024, 3, 1)
NIGHT_2 = date(2024, 3, 31)
MARCH_DAYS = 31

# 2024-03-01 is a Friday, so its ISO week (2024-W09) opens on Mon 2024-02-26.
WEEK_1 = "2024-W09"
WEEK_2 = "2024-W13"
LEAD_IN = [date(2024, 2, d) for d in (26, 27, 28, 29)]
DARK_NIGHTS = LEAD_IN + [date(2024, 3, d) for d in range(1, MARCH_DAYS + 1)]

# Rig 1: plate scale far from 1.0, so a stray plate-scale multiply is visible.
SQA55_SCALE = 2.94
# Four of rig 1's eight LIGHT frames carry an FWHM.
SQA55_FWHM = [6.0, 7.0, 8.0, 9.5]
SQA55_MEDIAN = statistics.median(SQA55_FWHM)  # 7.5


def _img(**kw):
    """Build an Image with required-but-irrelevant defaults filled in."""
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        exposure_time=3600.0,
        raw_headers={"SITELAT": str(SITE_LAT), "SITELONG": str(SITE_LON)},
    )
    defaults.update(kw)
    return Image(**defaults)


async def _truncate(engine):
    """Empty just the tables this file owns, in one statement.

    TRUNCATE rather than DELETE, and CASCADE rather than a hand-written list of
    dependent tables: a plain DELETE FROM targets aborts on a foreign key from
    session_notes left behind by another file, and because the whole clean-slate
    ran in one transaction that rollback silently took DELETE FROM images with
    it. The leftover frames then landed in this file's medians, which is what
    made the suite order-dependent. targets is deliberately not touched here:
    nothing in this file needs it, and truncating it is what dragged the foreign
    key in.
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE images, user_settings, site_dark_hours "
            "RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def seeded_stats_db():
    # The stats queries run on app.database.async_session, whose engine is a
    # module-level singleton. pytest-asyncio gives each test a fresh event
    # loop, so pooled connections from the previous test belong to a closed
    # loop; dispose on both sides rather than let pool_pre_ping trip over them.
    from app.database import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    await _truncate(engine)

    async with Session() as s:
        s.add(UserSettings(
            id=SETTINGS_ROW_ID,
            equipment={
                "cameras": {"ASI2600MM Pro": {"aliases": ["ASI2600"]}},
                "telescopes": {
                    "SQA55": {"aliases": ["Askar_SQA55"]},
                    "Askar140APO_0.8x": {"aliases": ["Askar_140APO"]},
                },
            },
        ))

        # --- Night 1, rig 1 (SQA55): eight LIGHT frames under two raw
        # spellings that alias to one canonical rig. FWHM on half of them.
        for i in range(8):
            raw_tel, raw_cam = (
                ("Askar_SQA55", "ASI2600") if i < 4 else ("SQA55", "ASI2600MM Pro")
            )
            s.add(_img(
                session_date=NIGHT_1,
                capture_date=datetime(2024, 3, 1, 20, i, tzinfo=timezone.utc),
                telescope=raw_tel, camera=raw_cam, filter_used="Ha",
                arcsec_per_pixel=SQA55_SCALE,
                median_hfr=1.4,
                fwhm=SQA55_FWHM[i // 2] if i % 2 == 0 else None,
            ))

        # Calibration frames on the same rig, same night. Must not reach the
        # inventory frame count, the integration total or the FWHM median.
        for i in range(3):
            s.add(_img(
                image_type="FLAT", exposure_time=1.0,
                session_date=NIGHT_1,
                capture_date=datetime(2024, 3, 1, 18, i, tzinfo=timezone.utc),
                telescope="SQA55", camera="ASI2600MM Pro", filter_used="Ha",
                arcsec_per_pixel=SQA55_SCALE, fwhm=99.0,
            ))

        # --- Night 1, rig 2 (Askar140APO): eight LIGHT frames, no FWHM.
        for i in range(8):
            s.add(_img(
                session_date=NIGHT_1,
                capture_date=datetime(2024, 3, 1, 21, i, tzinfo=timezone.utc),
                telescope="Askar_140APO", camera="ASI533MM", filter_used="L",
                arcsec_per_pixel=0.99, median_hfr=1.8,
            ))

        # --- Night 2: rig 2 alone, two LIGHT frames (2 hours).
        for i in range(2):
            s.add(_img(
                session_date=NIGHT_2,
                capture_date=datetime(2024, 3, 31, 21, i, tzinfo=timezone.utc),
                telescope="Askar_140APO", camera="ASI533MM", filter_used="L",
                arcsec_per_pixel=0.99, median_hfr=1.9,
            ))

        # --- Night 2: a third rig that shot only calibration frames. It must
        # not raise that night's rig count.
        for i in range(3):
            s.add(_img(
                image_type="FLAT", exposure_time=1.0,
                session_date=NIGHT_2,
                capture_date=datetime(2024, 3, 31, 18, i, tzinfo=timezone.utc),
                telescope="FlatOnly Scope", camera="FlatOnly Cam", filter_used="L",
            ))

        # A dark-hours row for every night of March plus the four February days
        # that complete the ISO week holding 2024-03-01. _eff_for_dates returns
        # None for a period missing even one of its nights, so a period is only
        # scored when its whole span is covered -- which is exactly what
        # backfill_dark_hours guarantees in production.
        for d in DARK_NIGHTS:
            s.add(SiteDarkHours(
                date=d, dark_hours=DARK_HOURS,
                latitude=SITE_LAT, longitude=SITE_LON,
            ))

        await s.commit()

    invalidate_alias_cache()
    import app.api.stats as stats_mod
    stats_mod._site_coords_cache = None

    async def _override_session():
        async with Session() as s:
            yield s

    def _override_user():
        u = MagicMock(spec=User)
        u.id = uuid.uuid4()
        u.username = "tester"
        u.role = UserRole.admin
        u.is_active = True
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield Session

    app.dependency_overrides.clear()
    invalidate_alias_cache()
    stats_mod._site_coords_cache = None
    # Leave nothing behind: the settings row collides with the fixed-id row
    # other DB-backed files insert, and stale images would skew their counts.
    await _truncate(engine)
    await engine.dispose()
    await app_engine.dispose()


@asynccontextmanager
async def _no_redis_cache():
    """Yield a Redis client that never has a cached stats payload."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    yield r


async def _get_stats():
    import time
    with patch("app.api.stats.async_redis", _no_redis_cache), \
         patch("app.api.stats._storage_last_update", time.time()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_name(items, name):
    for it in items:
        if it["name"] == name:
            return it
    raise AssertionError(f"{name} not in {[i['name'] for i in items]}")


def _combo(data, tel, cam):
    for c in data["equipment_performance"]:
        if c["telescope"] == tel and c["camera"] == cam:
            return c
    raise AssertionError(
        f"({tel}, {cam}) not in "
        f"{[(c['telescope'], c['camera']) for c in data['equipment_performance']]}"
    )


def _period(entries, period):
    for e in entries:
        if e["period"] == period:
            return e
    raise AssertionError(f"{period} not in {[e['period'] for e in entries]}")


# ---------------------------------------------------------------------------
# Issue 1: FWHM is arcseconds already, and both views must agree
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fwhm_median_is_identical_across_views_and_unscaled(seeded_stats_db):
    data = await _get_stats()

    tel = _by_name(data["equipment"]["telescopes"], "SQA55")
    cam = _by_name(data["equipment"]["cameras"], "ASI2600MM Pro")
    combo = _combo(data, "SQA55", "ASI2600MM Pro")

    # The plain median of the stored values, with no plate-scale multiply.
    assert tel["median_fwhm"] == SQA55_MEDIAN
    assert tel["median_fwhm_arcsec"] == SQA55_MEDIAN
    assert cam["median_fwhm"] == SQA55_MEDIAN
    assert cam["median_fwhm_arcsec"] == SQA55_MEDIAN
    assert combo["median_fwhm"] == SQA55_MEDIAN
    assert combo["median_fwhm_arcsec"] == SQA55_MEDIAN

    # The bug being guarded: multiplying by a 2.94 arcsec/px plate scale.
    assert tel["median_fwhm"] != round(SQA55_MEDIAN * SQA55_SCALE, 2)


@pytest.mark.asyncio
async def test_fwhm_frame_count_reports_partial_coverage(seeded_stats_db):
    data = await _get_stats()

    tel = _by_name(data["equipment"]["telescopes"], "SQA55")
    cam = _by_name(data["equipment"]["cameras"], "ASI2600MM Pro")
    combo = _combo(data, "SQA55", "ASI2600MM Pro")

    assert tel["fwhm_frame_count"] == len(SQA55_FWHM)
    assert cam["fwhm_frame_count"] == len(SQA55_FWHM)
    assert combo["fwhm_frame_count"] == len(SQA55_FWHM)
    # Coverage is partial: half the LIGHT frames have no CSV FWHM.
    assert tel["frame_count"] == 8
    assert sum(f["fwhm_frame_count"] for f in combo["filter_breakdown"]) == len(SQA55_FWHM)

    # Rig 2 has no FWHM at all.
    rig2 = _by_name(data["equipment"]["telescopes"], "Askar140APO_0.8x")
    assert rig2["fwhm_frame_count"] == 0
    assert rig2["median_fwhm"] is None


@pytest.mark.asyncio
async def test_alias_spellings_merge_into_one_median(seeded_stats_db):
    data = await _get_stats()

    names = [t["name"] for t in data["equipment"]["telescopes"]]
    assert "Askar_SQA55" not in names
    tel = _by_name(data["equipment"]["telescopes"], "SQA55")
    assert tel["grouped"] is True
    assert tel["nights"] == 1


@pytest.mark.asyncio
async def test_calibration_frames_excluded_from_inventory(seeded_stats_db):
    data = await _get_stats()

    tel = _by_name(data["equipment"]["telescopes"], "SQA55")
    # Eight LIGHT frames, not the eleven that include the three flats.
    assert tel["frame_count"] == 8
    assert tel["integration_seconds"] == 8 * 3600.0
    # The flats carry fwhm 99.0; if they leaked in they would move the median.
    assert tel["median_fwhm"] == SQA55_MEDIAN
    assert tel["fwhm_frame_count"] == len(SQA55_FWHM)

    # A rig with only calibration frames does not appear at all.
    assert "FlatOnly Scope" not in [t["name"] for t in data["equipment"]["telescopes"]]


# ---------------------------------------------------------------------------
# Issue 2: timeline efficiency denominator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_rigs_one_night_stays_at_or_below_100(seeded_stats_db):
    data = await _get_stats()

    day = _period(data["timeline_daily"], "2024-03-01")
    # Two rigs x 8 hours of exposure against 2 x 8 dark hours.
    assert day["integration_seconds"] == 16 * 3600.0
    assert day["efficiency_pct"] == 100.0
    assert all(
        e["efficiency_pct"] is None or e["efficiency_pct"] <= 100.0
        for e in data["timeline_daily"] + data["timeline_weekly"] + data["timeline_monthly"]
    )


@pytest.mark.asyncio
async def test_calibration_only_rig_does_not_raise_rig_count(seeded_stats_db):
    data = await _get_stats()

    day = _period(data["timeline_daily"], "2024-03-31")
    # One imaging rig: 2 hours against 1 x 8 dark hours. The flats-only rig
    # would halve this to 12.5 if it were counted.
    assert day["integration_seconds"] == 2 * 3600.0
    assert day["efficiency_pct"] == 25.0


@pytest.mark.asyncio
async def test_month_keeps_dark_nights_without_imaging_in_denominator(seeded_stats_db):
    data = await _get_stats()

    month = _period(data["timeline_monthly"], "2024-03")
    assert month["integration_seconds"] == 18 * 3600.0

    # 8 x 2 rigs on the 1st, 8 x 1 on the 31st, 8 x 1 on each of the other 29.
    denom = DARK_HOURS * 2 + DARK_HOURS + DARK_HOURS * (MARCH_DAYS - 2)
    assert month["efficiency_pct"] == round(18 / denom * 100, 1)
    # Had the 29 empty nights been dropped, this would read 75.0.
    assert month["efficiency_pct"] < 10.0


@pytest.mark.asyncio
async def test_week_spanning_the_month_boundary_counts_its_lead_in_nights(seeded_stats_db):
    data = await _get_stats()

    # 2024-W09 runs Mon 2024-02-26 to Sun 2024-03-03: four February nights with
    # no imaging, then the two-rig night, then two more empty ones.
    week = _period(data["timeline_weekly"], WEEK_1)
    denom = DARK_HOURS * (len(LEAD_IN) + 2) + DARK_HOURS * 2
    assert week["efficiency_pct"] == round(16 / denom * 100, 1)

    # 2024-W13 runs Mon 2024-03-25 to Sun 2024-03-31, one rig on the last night.
    week2 = _period(data["timeline_weekly"], WEEK_2)
    assert week2["efficiency_pct"] == round(2 / (DARK_HOURS * 7) * 100, 1)


@pytest.mark.asyncio
async def test_period_missing_a_dark_hours_row_reports_no_efficiency(seeded_stats_db):
    """A gap in site_dark_hours must blank the period, not inflate it.

    Treating an absent row as zero darkness would quietly drop that night out
    of the denominator, which is the exact arithmetic that pushed the old
    percentages past 100. None is honest and self-corrects on the next backfill.
    """
    Session = seeded_stats_db
    async with Session() as s:
        await s.execute(
            delete(SiteDarkHours).where(SiteDarkHours.date == date(2024, 3, 15))
        )
        await s.commit()

    data = await _get_stats()

    assert _period(data["timeline_monthly"], "2024-03")["efficiency_pct"] is None
    # Only the period containing the gap is affected.
    assert _period(data["timeline_daily"], "2024-03-01")["efficiency_pct"] == 100.0
    assert _period(data["timeline_weekly"], WEEK_1)["efficiency_pct"] is not None


# ---------------------------------------------------------------------------
# The backfill that keeps those dark-hours rows present. Without full-span
# coverage every assertion above degrades to None on a live install.
# ---------------------------------------------------------------------------

def test_backfill_dark_hours_covers_every_calendar_night_of_the_span():
    from datetime import timedelta
    import app.api.stats as stats_mod
    import app.services.astro_night as astro_night
    import app.worker.tasks_sessions as ts

    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=[])),                 # existing rows
        MagicMock(one=MagicMock(return_value=(NIGHT_1, NIGHT_2))),  # first/last session
    ]
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False

    asked: list[date] = []

    def _batch(dates, lat, lon):
        asked.extend(dates)
        return [DARK_HOURS] * len(dates)

    with patch.object(ts, "Session", MagicMock(return_value=cm)),          patch.object(ts, "_redis", MagicMock()),          patch.object(stats_mod, "_extract_site_coords_sync",
                      return_value=stats_mod.SiteCoords(latitude=SITE_LAT, longitude=SITE_LON)),          patch.object(astro_night, "dark_hours_batch", _batch):
        result = ts.backfill_dark_hours()

    assert result["status"] == "complete"

    # Backs up a week from the first session, then snaps to the 1st of that
    # month, so the ISO week holding the first imaging night is whole.
    assert min(asked) == date(2024, 2, 1)
    # Runs past today so a day that beat misses still has a row tomorrow.
    assert max(asked) >= date.today() + timedelta(days=35)
    # Every calendar night in between, not just the imaging ones.
    assert len(set(asked)) == (max(asked) - min(asked)).days + 1
    assert date(2024, 3, 15) in asked  # a night with no frames at all


def test_backfill_dark_hours_is_scheduled_and_registered():
    """Beat dispatches by name; an unregistered name is rejected at the worker."""
    import app.worker.tasks_sessions  # noqa: F401  importing is what registers it
    from app.worker.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["backfill-dark-hours"]
    assert entry["task"] == "app.worker.tasks.backfill_dark_hours"
    assert entry["task"] in celery_app.tasks
