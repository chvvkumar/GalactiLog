"""Real-DB tests for Phase 5 Task 3: exact Image.panel_id joins in panel stats.

Seeds real Target/Mosaic/MosaicPanel/Image rows (with panel_id/panel_label set
the way Task 1's backfill / Task 2's ingest hook set them) and exercises
panel_stats, batch_panel_stats, list_mosaic_summaries, and the
GET /{mosaic_id}/panels/{panel_id}/sessions endpoint against a real Postgres
test DB, asserting the exact-join rewrite returns correct, panel-scoped
results without the old ILIKE prefilter + object_matches_panel recheck.
"""
import os
import sys
import uuid
from datetime import date
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models import Target, Image, Mosaic, MosaicPanel
from app.services.mosaic_stats import panel_stats, batch_panel_stats, list_mosaic_summaries

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]


def _img(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        raw_headers={},
    )
    defaults.update(kw)
    return Image(**defaults)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))

    yield Session

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db):
    Session = db

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# BINDING requirement (Task 1 senior review): simple panels (no
# object_pattern) must keep resolved_target_id equality and count ALL target
# LIGHT frames, INCLUDING token-bearing OBJECT frames that got a panel_label
# but no panel_id (or a different panel_id) assigned. Narrowing to panel_id
# would silently drop those frames -- this test locks the preserved behavior.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simple_panel_counts_all_target_frames_including_token_bearing_ones(db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="M31 simple", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="M31 simple mosaic")
        s.add(mosaic)
        await s.flush()

        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="M31 simple", object_pattern=None,
        )
        s.add(panel)
        await s.flush()

        # Frame with no panel token at all -- gets panel_id via the simple
        # fallback (mirrors Task 1/2 semantics).
        s.add(_img(
            resolved_target_id=target.id, exposure_time=100.0, filter_used="L",
            panel_id=panel.id, panel_label=None,
            session_date=date(2026, 1, 1),
        ))
        # Frame whose OBJECT happens to look panel-shaped (token-bearing) --
        # gets panel_label set but panel_id left NULL by the backfill/ingest
        # logic (no matching MosaicPanel for that specific label). Today's
        # simple-panel query has no OBJECT filter at all, so this frame is
        # still counted; the rewrite must not regress that.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=200.0, filter_used="L",
            panel_id=None, panel_label="Panel 7",
            raw_headers={"OBJECT": "M31 Panel 7"},
            session_date=date(2026, 1, 2),
        ))
        await s.commit()

        target = await s.get(Target, target.id)
        panel = await s.get(MosaicPanel, panel.id)
        panel.target = target  # relationship access used by panel_stats

        stats = await panel_stats(panel, s)

    assert stats.total_frames == 2
    assert stats.total_integration_seconds == 300.0


# ---------------------------------------------------------------------------
# AUD-008 regression as a real-row test: sibling panels "Panel 1" / "Panel 12"
# sharing a target. The exact panel_id join must not need the old
# object_matches_panel recheck to keep them separate.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pattern_panel_sibling_numbers_do_not_cross_contaminate(db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="Sh2-119", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="Sh2-119 mosaic")
        s.add(mosaic)
        await s.flush()

        panel_1 = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 1", object_pattern="%Sh2-119%Panel%1%",
        )
        panel_12 = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 12", object_pattern="%Sh2-119%Panel%12%",
        )
        s.add_all([panel_1, panel_12])
        await s.flush()

        # Frame belongs to Panel 1 -- panel_id set exactly, no ambiguity.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=300.0,
            panel_id=panel_1.id, panel_label="Panel 1",
            raw_headers={"OBJECT": "Sh2-119 Panel 1"},
            session_date=date(2026, 2, 1),
        ))
        # Frame belongs to Panel 12 -- under the OLD ILIKE prefilter
        # ("%Sh2-119%Panel%1%" also matches "Sh2-119 Panel 12" as a
        # substring), this used to require the Python recheck to exclude it
        # from Panel 1's count. The exact join must exclude it without any
        # recheck.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=500.0,
            panel_id=panel_12.id, panel_label="Panel 12",
            raw_headers={"OBJECT": "Sh2-119 Panel 12"},
            session_date=date(2026, 2, 2),
        ))
        await s.commit()

        target = await s.get(Target, target.id)
        panel_1 = await s.get(MosaicPanel, panel_1.id)
        panel_1.target = target
        panel_12 = await s.get(MosaicPanel, panel_12.id)
        panel_12.target = target

        stats_1 = await panel_stats(panel_1, s)
        stats_12 = await panel_stats(panel_12, s)

    assert stats_1.total_frames == 1
    assert stats_1.total_integration_seconds == 300.0
    assert stats_12.total_frames == 1
    assert stats_12.total_integration_seconds == 500.0


# ---------------------------------------------------------------------------
# Stats-freshness: ingesting an Image directly into an accepted panel (with
# panel_id set, no detection job re-run) must be picked up immediately by
# panel_stats -- this is the concrete proof of the "accepted mosaics frozen"
# bug fix.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_panel_stats_reflects_newly_ingested_image_without_redetection(db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="IC1805", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="IC1805 mosaic")
        s.add(mosaic)
        await s.flush()

        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 3", object_pattern="%IC1805%Panel%3%",
        )
        s.add(panel)
        await s.flush()

        target = await s.get(Target, target.id)
        panel = await s.get(MosaicPanel, panel.id)
        panel.target = target

        before = await panel_stats(panel, s)
        assert before.total_frames == 0

        # Simulate a fresh ingest directly assigning panel_id (Task 2's hook),
        # no offline detection job involved.
        s.add(_img(
            resolved_target_id=target.id, exposure_time=250.0,
            panel_id=panel.id, panel_label="Panel 3",
            raw_headers={"OBJECT": "IC1805 Panel 3"},
            session_date=date(2026, 3, 1),
        ))
        await s.commit()

        after = await panel_stats(panel, s)

    assert after.total_frames == 1
    assert after.total_integration_seconds == 250.0


# ---------------------------------------------------------------------------
# batch_panel_stats: confirmed unchanged for simple panels -- still
# resolved_target_id-scoped, still counts token-bearing frames.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_panel_stats_simple_panel_counts_all_target_frames(db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="NGC7000 batch", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="NGC7000 batch mosaic")
        s.add(mosaic)
        await s.flush()

        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="NGC7000 batch", object_pattern=None,
        )
        s.add(panel)
        await s.flush()

        s.add(_img(resolved_target_id=target.id, exposure_time=100.0,
                    panel_id=panel.id, session_date=date(2026, 4, 1)))
        s.add(_img(resolved_target_id=target.id, exposure_time=150.0,
                    panel_id=None, panel_label="Panel 9",
                    raw_headers={"OBJECT": "NGC7000 Panel 9"},
                    session_date=date(2026, 4, 2)))
        await s.commit()

        target = await s.get(Target, target.id)
        panel = await s.get(MosaicPanel, panel.id)
        panel.target = target

        result = await batch_panel_stats([panel], s)

    stats = result[str(panel.id)]
    assert stats.total_frames == 2
    assert stats.total_integration_seconds == 250.0


# ---------------------------------------------------------------------------
# list_mosaic_summaries: pattern-panel aggregation via the exact panel_id
# join, end to end against a real mosaic with two sibling pattern panels.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_mosaic_summaries_pattern_panels_exact_join(db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="Veil east/west", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="Veil mosaic")
        s.add(mosaic)
        await s.flush()

        panel_a = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 1", object_pattern="%Veil%Panel%1%",
        )
        panel_b = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 2", object_pattern="%Veil%Panel%2%",
        )
        s.add_all([panel_a, panel_b])
        await s.flush()

        s.add(_img(resolved_target_id=target.id, exposure_time=300.0,
                    panel_id=panel_a.id, panel_label="Panel 1",
                    raw_headers={"OBJECT": "Veil Panel 1"},
                    session_date=date(2026, 5, 1)))
        s.add(_img(resolved_target_id=target.id, exposure_time=600.0,
                    panel_id=panel_b.id, panel_label="Panel 2",
                    raw_headers={"OBJECT": "Veil Panel 2"},
                    session_date=date(2026, 5, 2)))
        await s.commit()

        summaries = await list_mosaic_summaries(s)

    veil = next(m for m in summaries if m.name == "Veil mosaic")
    assert veil.panel_count == 2
    assert veil.total_frames == 2
    assert veil.total_integration_seconds == 900.0
    assert veil.first_session == "2026-05-01"
    assert veil.last_session == "2026-05-02"


# ---------------------------------------------------------------------------
# GET /{mosaic_id}/panels/{panel_id}/sessions -- exact join end to end
# through the API endpoint.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_panel_sessions_endpoint_uses_exact_join(api_client, db):
    Session = db
    async with Session() as s:
        target = Target(primary_name="M42 sessions", aliases=[])
        s.add(target)
        await s.flush()

        mosaic = Mosaic(name="M42 sessions mosaic")
        s.add(mosaic)
        await s.flush()

        panel_1 = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 1", object_pattern="%M42%Panel%1%",
        )
        panel_12 = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 12", object_pattern="%M42%Panel%12%",
        )
        s.add_all([panel_1, panel_12])
        await s.flush()

        s.add(_img(resolved_target_id=target.id, exposure_time=120.0,
                    filter_used="Ha",
                    panel_id=panel_1.id, panel_label="Panel 1",
                    raw_headers={"OBJECT": "M42 Panel 1"},
                    session_date=date(2026, 6, 1)))
        s.add(_img(resolved_target_id=target.id, exposure_time=900.0,
                    filter_used="Ha",
                    panel_id=panel_12.id, panel_label="Panel 12",
                    raw_headers={"OBJECT": "M42 Panel 12"},
                    session_date=date(2026, 6, 2)))
        await s.commit()

        mosaic_id, panel_1_id = mosaic.id, panel_1.id

    resp = await api_client.get(f"/api/mosaics/{mosaic_id}/panels/{panel_1_id}/sessions")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["panel_label"] == "Panel 1"
    assert len(data["sessions"]) == 1
    session_info = data["sessions"][0]
    assert session_info["session_date"] == "2026-06-01"
    assert session_info["total_frames"] == 1
    assert session_info["total_integration_seconds"] == 120.0
