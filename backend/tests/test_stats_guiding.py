"""DB-backed tests for GET /api/stats/guiding and compute_guiding_stats.

Seeds phd2_logs, phd2_sessions and a telescope alias, then asserts the
spec formulas, grouping rules and ordering from
docs/superpowers/specs/2026-08-24-phd2-statistics-design.md.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied.
"""
import statistics
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_session
from app.main import app
from app.models.phd2 import Phd2Log, Phd2Session
from app.models.user import User, UserRole
from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
from app.services.normalization import invalidate_alias_cache
from app.services.phd2_metrics import MIN_FRAMES, _weighted_rms


TEST_DB_URL = settings.database_url

RIG_A = "SQA55"
RIG_A_ALIAS = "Askar_SQA55"
RIG_B = "Askar140APO"

# (total, ra, dec) per seeded session, keyed by a short label.
RMS = {
    "a_main": (0.5, 0.3, 0.4),
    "a_gated": (9.0, 9.0, 9.0),
    "a_alias": (0.7, 0.5, 0.5),
    "b_main": (1.0, 0.6, 0.8),
    "b_edge": (1.0, 0.6, 0.8),
}
FRAMES = {"a_main": 300, "a_gated": 50, "a_alias": 200, "b_main": 400, "b_edge": MIN_FRAMES}
DROPS = {"a_main": 3, "a_gated": 1, "a_alias": 2, "b_main": 4, "b_edge": 0}


def _sess(log_id, label, **kw):
    total, ra, dec = RMS[label]
    defaults = dict(
        id=uuid.uuid4(),
        log_id=log_id,
        started_at_local=datetime(2026, 3, 5, 21, 0, 0),
        started_at_utc=datetime(2026, 3, 6, 2, 0, 0, tzinfo=timezone.utc),
        duration_s=3600.0,
        session_date=date(2026, 3, 5),
        equipment_profile="profile",
        pixel_scale_arcsec=1.5,
        frame_count=FRAMES[label],
        drop_count=DROPS[label],
        rms_total_arcsec=total,
        rms_ra_arcsec=ra,
        rms_dec_arcsec=dec,
        events=[],
    )
    defaults.update(kw)
    return Phd2Session(**defaults)


async def _truncate(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE phd2_logs, user_settings RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def seeded_db():
    from app.database import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    await _truncate(engine)

    log_id = uuid.uuid4()
    async with Session() as s:
        s.add(UserSettings(
            id=SETTINGS_ROW_ID,
            equipment={
                "cameras": {},
                "telescopes": {RIG_A: {"aliases": [RIG_A_ALIAS]}},
            },
        ))
        s.add(Phd2Log(
            id=log_id,
            file_path="/guiding-stats-test/PHD2_GuideLog.txt",
            parse_status="ok",
            run_count=1, session_count=6,
        ))
        await s.flush()

        # Rig A, canonical spelling: the reference session.
        s.add(_sess(
            log_id, "a_main",
            telescope=RIG_A,
            session_date=date(2026, 3, 5),
            started_at_utc=datetime(2026, 3, 6, 2, 0, 0, tzinfo=timezone.utc),
            duration_s=3600.0,
            alt_deg=45.0, exposure_ms=2000.0, settle_median_s=3.5,
            rms_total_filtered_arcsec=0.45,
        ))
        # Rig A, gated: too few frames to weight, still counted. alt exactly
        # 30 lands in the 30-60 band. Its 9.0 RMS must stay out of the
        # weighted figures, but its guide exposure still shows up.
        s.add(_sess(
            log_id, "a_gated",
            telescope=RIG_A,
            session_date=date(2026, 3, 20),
            started_at_utc=datetime(2026, 3, 21, 2, 0, 0, tzinfo=timezone.utc),
            duration_s=300.0,
            alt_deg=30.0, exposure_ms=3000.0, settle_median_s=None,
        ))
        # Rig A under its alias spelling: must merge into RIG_A.
        s.add(_sess(
            log_id, "a_alias",
            telescope=RIG_A_ALIAS,
            session_date=date(2026, 4, 2),
            started_at_utc=datetime(2026, 4, 3, 2, 0, 0, tzinfo=timezone.utc),
            duration_s=1800.0,
            alt_deg=25.0, exposure_ms=1000.0, settle_median_s=2.5,
            rms_total_filtered_arcsec=0.65,
        ))
        # Rig B: two sessions, one guide exposure, no settle medians.
        s.add(_sess(
            log_id, "b_main",
            telescope=RIG_B,
            session_date=date(2026, 3, 5),
            started_at_utc=datetime(2026, 3, 6, 3, 0, 0, tzinfo=timezone.utc),
            duration_s=7200.0,
            alt_deg=70.0,
            exposure_ms=1500.0,
        ))
        # alt exactly 60 lands in the >60 band; frame_count == MIN_FRAMES is
        # not gated.
        s.add(_sess(
            log_id, "b_edge",
            telescope=RIG_B,
            session_date=date(2026, 3, 6),
            started_at_utc=datetime(2026, 3, 7, 3, 0, 0, tzinfo=timezone.utc),
            duration_s=1800.0,
            alt_deg=60.0,
            exposure_ms=1500.0,
        ))
        # Unmapped profile: excluded everywhere, counted once.
        s.add(_sess(
            log_id, "a_main",
            telescope=None,
            session_date=date(2026, 3, 5),
            alt_deg=50.0,
        ))

        await s.commit()

    invalidate_alias_cache()

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
    await _truncate(engine)
    await engine.dispose()
    await app_engine.dispose()


@asynccontextmanager
async def _no_redis_cache():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    yield r


async def _get_guiding():
    with patch("app.services.cache.async_redis", _no_redis_cache):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/guiding")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rig(data, name):
    for r in data["rigs"]:
        if r["telescope"] == name:
            return r
    raise AssertionError(f"{name} not in {[r['telescope'] for r in data['rigs']]}")


def _rows(rows):
    return [SimpleNamespace(frame_count=FRAMES[l], rms_total_arcsec=RMS[l][0],
                            rms_ra_arcsec=RMS[l][1], rms_dec_arcsec=RMS[l][2])
            for l in rows]


@pytest.mark.asyncio
async def test_rig_scorecard_matches_weighted_rms_and_gates(seeded_db):
    data = await _get_guiding()

    assert data["unmapped_session_count"] == 1
    assert [r["telescope"] for r in data["rigs"]] == [RIG_B, RIG_A]

    a = _rig(data, RIG_A)
    rows_a = _rows(["a_main", "a_gated", "a_alias"])
    assert a["session_count"] == 3
    assert a["gated_session_count"] == 1
    assert a["rms_total_arcsec"] == _weighted_rms(rows_a, "rms_total_arcsec")
    assert a["rms_ra_arcsec"] == _weighted_rms(rows_a, "rms_ra_arcsec")
    assert a["rms_dec_arcsec"] == _weighted_rms(rows_a, "rms_dec_arcsec")
    # The 9.0 gated session must not have moved the figure.
    assert a["rms_total_arcsec"] < 1.0
    assert a["rms_total_filtered_arcsec"] == pytest.approx(
        ((300 * 0.45 ** 2 + 200 * 0.65 ** 2) / 500) ** 0.5, abs=1e-6)
    assert a["ra_dec_ratio"] == pytest.approx(a["rms_dec_arcsec"] / a["rms_ra_arcsec"], abs=1e-3)
    assert a["guided_hours"] == round(5700 / 3600, 2)
    assert a["settle_median_s"] == statistics.median([3.5, 2.5])
    assert a["exposure_ms_values"] == [1000, 2000, 3000]

    b = _rig(data, RIG_B)
    assert b["session_count"] == 2
    assert b["gated_session_count"] == 0
    assert b["rms_total_arcsec"] == pytest.approx(1.0, abs=1e-6)
    assert b["rms_total_filtered_arcsec"] is None
    assert b["settle_median_s"] is None
    assert b["exposure_ms_values"] == [1500]


@pytest.mark.asyncio
async def test_response_carries_only_the_trimmed_keys(seeded_db):
    """The trim dropped settings/pier_side/monthly/star_lost_reasons/
    calibrations and five per-rig fields; nothing may leak back in."""
    data = await _get_guiding()

    assert set(data) == {"unmapped_session_count", "rigs", "altitude_bands"}
    assert set(data["rigs"][0]) == {
        "telescope", "session_count", "gated_session_count", "guided_hours",
        "rms_total_arcsec", "rms_ra_arcsec", "rms_dec_arcsec",
        "rms_total_filtered_arcsec", "ra_dec_ratio", "settle_median_s",
        "exposure_ms_values",
    }
    assert set(data["altitude_bands"][0]) == {
        "telescope", "band", "session_count",
        "rms_total_arcsec", "rms_ra_arcsec", "rms_dec_arcsec",
    }


@pytest.mark.asyncio
async def test_altitude_bands(seeded_db):
    data = await _get_guiding()

    bands = [(b["telescope"], b["band"], b["session_count"]) for b in data["altitude_bands"]]
    # 25 -> <30, 30 -> 30-60 (gated but counted), 45 -> 30-60, 60 and 70 -> >60.
    assert bands == [
        (RIG_B, ">60", 2),
        (RIG_A, "<30", 1),
        (RIG_A, "30-60", 2),
    ]
    mid_a = next(b for b in data["altitude_bands"] if b["telescope"] == RIG_A and b["band"] == "30-60")
    assert mid_a["rms_total_arcsec"] == 0.5  # gated 9.0 excluded from weighting


@pytest.mark.asyncio
async def test_compute_guiding_stats_without_http(seeded_db):
    from app.services.phd2_stats import compute_guiding_stats

    async with seeded_db() as s:
        result = await compute_guiding_stats(s)

    assert result.unmapped_session_count == 1
    assert [r.telescope for r in result.rigs] == [RIG_B, RIG_A]
    assert result.model_dump(mode="json") == await _get_guiding()


@pytest.mark.asyncio
async def test_guiding_stats_cache_key_is_invalidated():
    from app.services import cache as cache_mod

    r = AsyncMock()

    async def _empty_scan(match=None):
        return
        yield

    r.scan_iter = _empty_scan

    @asynccontextmanager
    async def _redis():
        yield r

    with patch.object(cache_mod, "async_redis", _redis):
        await cache_mod.invalidate_stats_and_analysis_cache()

    deleted = {k for call in r.delete.call_args_list for k in call.args}
    assert "galactilog:stats:guiding" in deleted

    from tests.conftest import bootstrap_worker_module
    tc = bootstrap_worker_module("app.worker.tasks_common")
    with patch.object(tc, "_redis") as fake:
        tc._invalidate_stats_cache()
    deleted = {k for call in fake.delete.call_args_list for k in call.args}
    assert "galactilog:stats:guiding" in deleted
