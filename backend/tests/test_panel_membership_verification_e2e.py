"""End-to-end tests for the three non-suggestion Phase 5 verification-checklist
items (docs/retrofit-roadmap.md Phase 5), each driven through the REAL code
path rather than direct ORM row seeding, per the Task 6 brief:

  1. Ingest a new file for an accepted mosaic's panel -> panel stats update.
     Task 3's `test_panel_stats_reflects_newly_ingested_image_without_redetection`
     covers this by seeding an Image row with `panel_id` set directly (simulating
     Task 2's ingest hook). This test instead runs the real
     `app.worker.tasks._do_ingest` and then reads the stats back through the
     real `GET /api/mosaics/{id}` endpoint, so the ingest-hook-to-stats path is
     exercised as one continuous flow rather than two independently-verified
     halves.
  2. Ingest a file with a new panel label -> it appears as available. Task 4's
     suite (`test_mosaic_available_panel_labels.py`) seeds NULL-panel_id Image
     rows directly. This test instead runs real `_do_ingest` for the new-label
     frame.
  3. Delete files -> the panel's session data empties cleanly. Task 5's suite
     exercises `prune_stale_panel_sessions` directly (sync-session unit tests)
     and separately asserts, via a mocked `prune_stale_panel_sessions`, that
     `run_scan` calls it exactly once per invocation. Neither test lets a real
     `run_scan` orphan-cleanup pass actually delete the Image rows and prune
     the `MosaicPanelSession` rows in the same call. This test does that: it
     seeds Image/MosaicPanelSession rows whose backing file never exists on
     disk under a real (empty) fits-data root, runs the real `run_scan` task
     body with the DB/scan-directory/prune code paths all live (only cheap,
     unrelated side effects -- Celery `apply_async` dispatch, Redis, activity
     logging -- are stubbed), and asserts the session row is gone afterward.

All three are real-DB-backed against the test Postgres instance, per the
brief. The suggestion-side regression-fixture corpus lives in
`test_panel_suggestion_regression_corpus.py`.
"""
import os
import sys
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

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
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models import Target, Image, Mosaic, MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession

from tests.test_ingest_panel_membership import _bootstrap_tasks, _run_ingest, _meta

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]
SYNC_DB_URL = TEST_DB_URL.replace("+asyncpg", "+psycopg2")
TEST_MARK = "zzp5verifye2e"


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
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, {}
    app.dependency_overrides.clear()


def _sync_engine():
    engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return engine


# ---------------------------------------------------------------------------
# 1. Ingest new file for an accepted mosaic's panel -> stats update.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_new_frame_for_accepted_panel_updates_stats_e2e(db, api_client, tmp_path):
    Session = db
    async with Session() as s:
        target = Target(primary_name=f"{TEST_MARK}_target", aliases=[])
        s.add(target)
        await s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic")
        s.add(mosaic)
        await s.flush()
        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 1", object_pattern=f"%{TEST_MARK}%Panel%1%",
        )
        s.add(panel)
        await s.commit()
        mosaic_id, target_id, panel_id = mosaic.id, target.id, panel.id

    client, headers = api_client

    resp0 = await client.get(f"/api/mosaics/{mosaic_id}", headers=headers)
    assert resp0.status_code == 200
    panel0 = next(p for p in resp0.json()["panels"] if p["panel_id"] == str(panel_id))
    assert panel0["total_frames"] == 0

    tasks_mod = _bootstrap_tasks()
    engine = _sync_engine()
    try:
        meta = _meta(tmp_path, "newframe", f"{TEST_MARK} Panel 1")
        row = _run_ingest(tasks_mod, engine, tmp_path, meta, str(target_id))
        assert row is not None
        assert row["panel_id"] == panel_id
    finally:
        engine.dispose()

    resp1 = await client.get(f"/api/mosaics/{mosaic_id}", headers=headers)
    assert resp1.status_code == 200
    panel1 = next(p for p in resp1.json()["panels"] if p["panel_id"] == str(panel_id))
    assert panel1["total_frames"] == 1


# ---------------------------------------------------------------------------
# 2. Ingest a file with a new panel label -> it appears as available.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_new_panel_label_surfaces_as_available_e2e(db, api_client, tmp_path):
    Session = db
    async with Session() as s:
        target = Target(primary_name=f"{TEST_MARK}_target2", aliases=[])
        s.add(target)
        await s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic2")
        s.add(mosaic)
        await s.flush()
        # An existing accepted panel is required: available-label surfacing
        # only scans targets that already belong to the mosaic via a panel.
        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label="Panel 1", object_pattern=f"%{TEST_MARK}%Panel%1%",
        )
        s.add(panel)
        await s.commit()
        mosaic_id, target_id = mosaic.id, target.id

    client, headers = api_client

    resp0 = await client.get(f"/api/mosaics/{mosaic_id}", headers=headers)
    assert resp0.status_code == 200
    assert resp0.json()["available_panel_labels"] == []

    tasks_mod = _bootstrap_tasks()
    engine = _sync_engine()
    try:
        # "Panel 2" has no matching MosaicPanel row yet.
        meta = _meta(tmp_path, "newlabel", f"{TEST_MARK} Panel 2")
        row = _run_ingest(tasks_mod, engine, tmp_path, meta, str(target_id))
        assert row is not None
        assert row["panel_label"] == "Panel 2"
        assert row["panel_id"] is None
    finally:
        engine.dispose()

    resp1 = await client.get(f"/api/mosaics/{mosaic_id}", headers=headers)
    assert resp1.status_code == 200
    available = resp1.json()["available_panel_labels"]
    assert available == [{"label": "Panel 2", "target_id": str(target_id)}]


# ---------------------------------------------------------------------------
# 3. Delete files -> panel session data empties cleanly, through the real
#    run_scan orphan-detection path (not the prune helper called directly).
# ---------------------------------------------------------------------------

def _run_scan_real_orphan_pass(tasks_mod, engine, fits_root, redis_mock):
    """Drive the real run_scan task body with only cheap, unrelated side
    effects stubbed (Celery apply_async dispatch, activity logging, Redis
    scan-state bookkeeping). The DB session, scan_directory tree walk (over a
    real, empty fits_root so every known row reads as missing-from-disk), and
    prune_stale_panel_sessions all run for real."""
    mock_actx = MagicMock()
    mock_actx.__enter__ = lambda *_a: MagicMock()
    mock_actx.__exit__ = lambda *_a: None

    with patch.object(tasks_mod, "_sync_engine", engine), \
         patch.object(tasks_mod.settings, "fits_data_path", str(fits_root)), \
         patch.object(tasks_mod, "_redis", redis_mock), \
         patch.object(tasks_mod, "_emit_activity_sync", MagicMock()), \
         patch.object(tasks_mod, "_activity_session", lambda: mock_actx), \
         patch.object(tasks_mod, "clear_cancel_sync", MagicMock()), \
         patch.object(tasks_mod, "start_scanning_sync", MagicMock()), \
         patch.object(tasks_mod, "clear_skipped_paths_sync", MagicMock()), \
         patch.object(tasks_mod, "is_cancel_requested_sync", MagicMock(return_value=False)), \
         patch.object(tasks_mod, "set_discovered_sync", MagicMock()), \
         patch.object(tasks_mod, "set_idle_sync", MagicMock()), \
         patch.object(tasks_mod, "check_complete_sync", MagicMock()), \
         patch.object(tasks_mod, "generate_reference_thumbnails", MagicMock()), \
         patch.object(tasks_mod, "detect_duplicate_targets", MagicMock()), \
         patch.object(tasks_mod, "backfill_dark_hours", MagicMock()):
        return tasks_mod.run_scan.run(force_orphan_cleanup=True)


def test_delete_files_via_run_scan_empties_panel_session_cleanly_e2e(tmp_path):
    engine = _sync_engine()
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        s.execute(text("DELETE FROM images WHERE file_path LIKE :p"), {"p": f"%{TEST_MARK}%"})
        s.execute(text(
            "DELETE FROM mosaic_panel_sessions WHERE panel_id IN "
            "(SELECT id FROM mosaic_panels WHERE panel_label LIKE :p)"
        ), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM mosaic_panels WHERE panel_label LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM mosaics WHERE name LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM targets WHERE primary_name LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.commit()

        target = Target(primary_name=f"{TEST_MARK}_scantarget", aliases=[])
        s.add(target)
        s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_scanmosaic")
        s.add(mosaic)
        s.flush()
        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id,
            panel_label=f"{TEST_MARK}_Panel 1", object_pattern=f"%{TEST_MARK}%Panel%1%",
        )
        s.add(panel)
        s.flush()

        fits_root = tmp_path / "fits_root"
        fits_root.mkdir()
        # The file is registered in the catalog but never actually created on
        # disk -- exactly the state a deleted file leaves behind. Real
        # scan_directory walks the (empty) fits_root and reports it missing.
        missing_path = str(fits_root / f"{TEST_MARK}_deleted.fits")
        session_date = date(2026, 3, 1)
        image = Image(
            file_path=missing_path, file_name=f"{TEST_MARK}_deleted.fits",
            resolved_target_id=target.id, image_type="LIGHT",
            panel_id=panel.id, panel_label=panel.panel_label,
            session_date=session_date, raw_headers={},
        )
        s.add(image)
        s.add(MosaicPanelSession(panel_id=panel.id, session_date=session_date, status="included"))
        s.commit()

        panel_id = panel.id
        image_id = image.id

        tasks_mod = _bootstrap_tasks()
        redis_mock = MagicMock()
        redis_mock.set.return_value = True  # scan-run lock acquired

        result = _run_scan_real_orphan_pass(tasks_mod, engine, fits_root, redis_mock)

        assert result["removed"] == 1
        # The deletion happened on a separate connection (tasks_mod's
        # _sync_engine, patched to `engine` above, but via its own Session).
        # This session's identity map still holds the pre-deletion Image
        # object from the earlier `s.add(image)`/`s.commit()`, so `s.get`
        # would return the stale cached instance without hitting the DB.
        # Expire everything first to force a real re-fetch.
        s.expire_all()
        assert s.get(Image, image_id) is None
        remaining_sessions = s.execute(
            select(MosaicPanelSession.id).where(MosaicPanelSession.panel_id == panel_id)
        ).all()
        assert remaining_sessions == []
        # The panel row itself is never deleted, only its stale session data.
        assert s.get(MosaicPanel, panel_id) is not None
    finally:
        s.execute(text("DELETE FROM images WHERE file_path LIKE :p"), {"p": f"%{TEST_MARK}%"})
        s.execute(text(
            "DELETE FROM mosaic_panel_sessions WHERE panel_id IN "
            "(SELECT id FROM mosaic_panels WHERE panel_label LIKE :p)"
        ), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM mosaic_panels WHERE panel_label LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM mosaics WHERE name LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.execute(text("DELETE FROM targets WHERE primary_name LIKE :p"), {"p": f"{TEST_MARK}%"})
        s.commit()
        s.close()
        engine.dispose()
