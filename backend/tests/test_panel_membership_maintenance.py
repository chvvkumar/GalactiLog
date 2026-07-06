"""Tests for Phase 5 Task 5: panel membership maintenance.

Part A (per brief): orphan-cleanup deletion prunes stale MosaicPanelSession
rows without deleting the MosaicPanel row itself.

Part B (extended scope, T2 review finding): Image.panel_id is recomputed
whenever Image.resolved_target_id changes outside ingest (target unmerge,
merge-candidate revert, orphan-to-target attach, custom-target retro-link),
since ingest-time parsing never revisits an already-inserted Image row.

Both halves are real-DB tests against the test Postgres instance; Part A uses
a sync Session (mirrors run_scan's own sync orphan-cleanup block), Part B uses
an async engine (mirrors the async API/service code paths it exercises).
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
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models import Target, Image, Mosaic, MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.models.merge_manifest import MergeManifest
from app.models.filename_candidate import FilenameCandidate
from app.services.mosaic_detection import (
    prune_stale_panel_sessions,
    recompute_panel_membership_for_images,
)
from app.services.target_merge import unmerge_target

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]
SYNC_DB_URL = TEST_DB_URL.replace("+asyncpg", "+psycopg2")

TEST_MARK = "zzpanelmaint"


# ---------------------------------------------------------------------------
# Part A: sync fixtures, mirrors run_scan's own sync orphan-cleanup Session
# ---------------------------------------------------------------------------

def _sync_cleanup(session):
    session.execute(text("DELETE FROM images WHERE file_path LIKE :p"), {"p": f"%{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaic_panel_sessions WHERE panel_id IN "
                          "(SELECT id FROM mosaic_panels WHERE panel_label LIKE :p)"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaic_panels WHERE panel_label LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaics WHERE name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM targets WHERE primary_name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.commit()


@pytest.fixture
def sync_db():
    engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    Session = sessionmaker(bind=engine)
    s = Session()
    _sync_cleanup(s)
    yield s
    _sync_cleanup(s)
    s.close()
    engine.dispose()


def _seed_panel(session, name_suffix):
    target = Target(primary_name=f"{TEST_MARK}_{name_suffix}", aliases=[])
    session.add(target)
    session.flush()
    mosaic = Mosaic(name=f"{TEST_MARK}_mosaic_{name_suffix}")
    session.add(mosaic)
    session.flush()
    panel = MosaicPanel(
        mosaic_id=mosaic.id, target_id=target.id,
        panel_label=f"{TEST_MARK}_panel_{name_suffix}",
        object_pattern=f"%{TEST_MARK}%{name_suffix}%",
    )
    session.add(panel)
    session.flush()
    return target, mosaic, panel


def _seed_image(session, target_id, panel_id, session_date, path_suffix):
    img = Image(
        id=uuid.uuid4(),
        file_path=f"/data/{TEST_MARK}_{path_suffix}.fits",
        file_name=f"{TEST_MARK}_{path_suffix}.fits",
        resolved_target_id=target_id,
        panel_id=panel_id,
        panel_label=None,
        image_type="LIGHT",
        session_date=session_date,
        raw_headers={},
    )
    session.add(img)
    return img


class TestPruneStalePanelSessions:
    def test_prune_removes_only_the_stale_dates_session_row(self, sync_db):
        """Images for one date deleted -> only that date's session row is
        pruned; the other date's row and the MosaicPanel itself remain."""
        s = sync_db
        _target, _mosaic, panel = _seed_panel(s, "twodate")
        d1, d2 = date(2026, 1, 1), date(2026, 1, 2)
        s.add_all([
            MosaicPanelSession(panel_id=panel.id, session_date=d1, status="included"),
            MosaicPanelSession(panel_id=panel.id, session_date=d2, status="included"),
        ])
        img1 = _seed_image(s, panel.target_id, panel.id, d1, "twodate_d1")
        _seed_image(s, panel.target_id, panel.id, d2, "twodate_d2")
        s.commit()

        # Simulate orphan cleanup deleting all Images for date 1 only.
        s.execute(text("DELETE FROM images WHERE id = :id"), {"id": img1.id})
        s.commit()

        pruned = prune_stale_panel_sessions(s, {panel.id})

        assert pruned == 1
        remaining_dates = {
            row[0] for row in s.execute(
                select(MosaicPanelSession.session_date).where(MosaicPanelSession.panel_id == panel.id)
            ).all()
        }
        assert remaining_dates == {d2}
        assert s.get(MosaicPanel, panel.id) is not None

    def test_prune_keeps_panel_row_when_every_date_emptied(self, sync_db):
        """Deleting every Image for a panel prunes all its session rows but
        never deletes the MosaicPanel row (admin grid/rotation config may
        still be meaningful with zero current data)."""
        s = sync_db
        _target, _mosaic, panel = _seed_panel(s, "allgone")
        d1, d2 = date(2026, 2, 1), date(2026, 2, 2)
        s.add_all([
            MosaicPanelSession(panel_id=panel.id, session_date=d1, status="included"),
            MosaicPanelSession(panel_id=panel.id, session_date=d2, status="included"),
        ])
        img1 = _seed_image(s, panel.target_id, panel.id, d1, "allgone_d1")
        img2 = _seed_image(s, panel.target_id, panel.id, d2, "allgone_d2")
        s.commit()

        s.execute(text("DELETE FROM images WHERE id IN (:a, :b)"), {"a": img1.id, "b": img2.id})
        s.commit()

        pruned = prune_stale_panel_sessions(s, {panel.id})

        assert pruned == 2
        remaining = s.execute(
            select(MosaicPanelSession.id).where(MosaicPanelSession.panel_id == panel.id)
        ).all()
        assert remaining == []
        assert s.get(MosaicPanel, panel.id) is not None

    def test_prune_does_not_touch_a_sibling_panels_sessions(self, sync_db):
        """Pruning is scoped precisely per panel: a sibling panel's session
        rows (and its Images' panel_id) are unaffected by another panel's
        orphan cleanup."""
        s = sync_db
        _t1, _m1, panel_a = _seed_panel(s, "siba")
        _t2, _m2, panel_b = _seed_panel(s, "sibb")
        d1 = date(2026, 3, 1)
        s.add_all([
            MosaicPanelSession(panel_id=panel_a.id, session_date=d1, status="included"),
            MosaicPanelSession(panel_id=panel_b.id, session_date=d1, status="included"),
        ])
        img_a = _seed_image(s, panel_a.target_id, panel_a.id, d1, "siba_img")
        img_b = _seed_image(s, panel_b.target_id, panel_b.id, d1, "sibb_img")
        s.commit()

        # Only panel A's image is deleted (as if orphan cleanup only touched A).
        s.execute(text("DELETE FROM images WHERE id = :id"), {"id": img_a.id})
        s.commit()

        pruned = prune_stale_panel_sessions(s, {panel_a.id})

        assert pruned == 1
        # Panel B's session row and its Image's panel_id are untouched.
        b_sessions = s.execute(
            select(MosaicPanelSession.id).where(MosaicPanelSession.panel_id == panel_b.id)
        ).all()
        assert len(b_sessions) == 1
        b_img = s.get(Image, img_b.id)
        assert b_img.panel_id == panel_b.id


def test_run_scan_calls_prune_once_per_invocation_not_per_batch():
    """Pruning runs once per run_scan invocation, not once per 500-row delete
    batch -- a design/perf assertion via call-count on the helper, exercised
    with more than 500 orphaned rows sharing a single panel_id."""
    import ast
    import pathlib
    from tests.test_tasks_emit import _bootstrap_real_tasks, _FakeSession

    tasks_mod = _bootstrap_real_tasks()

    shared_panel_id = uuid.uuid4()
    known_paths = [f"/tmp/test_fits/{TEST_MARK}_{i}.fits" for i in range(1200)]
    disk_paths: list = []  # every known path is now "missing"
    known_rows = [(p, 100, 1.0) for p in known_paths]
    orphan_rows = [(uuid.uuid4(), None, shared_panel_id) for _ in known_paths]

    all_queue = [known_rows, orphan_rows]

    def session_factory(*a, **k):
        return _FakeSession(all_queue)

    fake_cfg = MagicMock()
    fake_cfg.should_include_file.return_value = True
    fake_cfg.roots.return_value = [tasks_mod.Path("/tmp/test_fits")]

    mock_actx = MagicMock()
    mock_actx.__enter__ = lambda s, *a: MagicMock()
    mock_actx.__exit__ = lambda s, *a: None

    with patch.object(tasks_mod, "Session", session_factory), \
         patch.object(tasks_mod, "_redis", MagicMock()), \
         patch.object(tasks_mod, "prune_stale_panel_sessions", MagicMock(return_value=0)) as fake_prune, \
         patch.object(tasks_mod, "_emit_activity_sync", MagicMock()), \
         patch.object(tasks_mod, "_activity_session", lambda: mock_actx), \
         patch.object(tasks_mod, "clear_cancel_sync"), \
         patch.object(tasks_mod, "start_scanning_sync"), \
         patch.object(tasks_mod, "get_skipped_paths_sync", return_value=set()), \
         patch.object(tasks_mod, "clear_skipped_paths_sync"), \
         patch.object(tasks_mod, "is_cancel_requested_sync", return_value=False), \
         patch.object(tasks_mod, "set_discovered_sync"), \
         patch.object(tasks_mod, "set_idle_sync"), \
         patch.object(tasks_mod, "check_complete_sync"), \
         patch.object(tasks_mod, "set_ingesting_sync"), \
         patch.object(tasks_mod, "generate_reference_thumbnails"), \
         patch.object(tasks_mod, "detect_duplicate_targets"), \
         patch.object(tasks_mod, "backfill_dark_hours"), \
         patch("app.services.scan_filters.ScanFilterConfig.from_settings", return_value=fake_cfg), \
         patch("app.services.scanner.scan_directory", return_value=([], [], set(disk_paths))):
        result = tasks_mod.run_scan.run(force_orphan_cleanup=True)

    assert result["removed"] == 1200
    # More than 2 batches of 500 ran, but the prune helper is only called once.
    fake_prune.assert_called_once()
    called_ids = fake_prune.call_args[0][1]
    assert called_ids == {shared_panel_id}


# ---------------------------------------------------------------------------
# Part B: async fixtures for the resolved_target_id-change recompute paths
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _clean(conn):
        await conn.execute(text("DELETE FROM merge_manifests"))
        await conn.execute(text("DELETE FROM merge_candidates"))
        await conn.execute(text("DELETE FROM filename_candidates"))
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))

    async with engine.begin() as conn:
        await _clean(conn)

    yield Session

    async with engine.begin() as conn:
        await _clean(conn)
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
    app.dependency_overrides[require_admin] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


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


@pytest.mark.asyncio
async def test_recompute_populates_panel_id_for_simple_panel_after_target_gain(db):
    """An image that gains a target for the first time (orphan attach) and
    carries no panel_label picks up the target's simple (no-object_pattern)
    panel via the fallback branch, exactly like resolve_panel_membership."""
    Session = db
    async with Session() as s:
        target = Target(primary_name=f"{TEST_MARK}_simple", aliases=[])
        s.add(target)
        await s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic_simple")
        s.add(mosaic)
        await s.flush()
        panel = MosaicPanel(mosaic_id=mosaic.id, target_id=target.id,
                             panel_label=f"{TEST_MARK}_simple_panel", object_pattern=None)
        s.add(panel)
        await s.flush()

        img = _img(resolved_target_id=target.id, panel_label=None, panel_id=None)
        s.add(img)
        await s.commit()

        await recompute_panel_membership_for_images(s, [img.id])
        await s.commit()

        refreshed = await s.get(Image, img.id)
        assert refreshed.panel_id == panel.id


@pytest.mark.asyncio
async def test_recompute_clears_panel_id_when_target_no_longer_matches(db):
    """When resolved_target_id is cleared (e.g. revert), a previously-set
    panel_id is cleared rather than left pointing at a foreign target's
    panel."""
    Session = db
    async with Session() as s:
        target = Target(primary_name=f"{TEST_MARK}_clear", aliases=[])
        s.add(target)
        await s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic_clear")
        s.add(mosaic)
        await s.flush()
        panel = MosaicPanel(mosaic_id=mosaic.id, target_id=target.id,
                             panel_label="Panel 1", object_pattern=f"%{TEST_MARK}%clear%1%")
        s.add(panel)
        await s.flush()

        img = _img(resolved_target_id=None, panel_label="Panel 1", panel_id=panel.id)
        s.add(img)
        await s.commit()

        # resolved_target_id is already None here (simulating the state right
        # after an update statement cleared it); recompute must clear panel_id.
        await recompute_panel_membership_for_images(s, [img.id])
        await s.commit()

        refreshed = await s.get(Image, img.id)
        assert refreshed.panel_id is None


@pytest.mark.asyncio
async def test_unmerge_restores_stale_panel_membership_via_manifest(db):
    """Unmerge staleness: a pattern-panel image merged onto the winner (its
    panel_id repointed to the winner's copy of the panel) is restored to the
    loser's panel_id, not left pointing at the winner's panel, when the
    target unmerges. The panel-target reversion (substring match) runs before
    the recompute inside unmerge_target, so the lookup finds the panel
    already moved back to the loser."""
    Session = db
    async with Session() as s:
        loser = Target(primary_name=f"{TEST_MARK}_loser", aliases=[])
        winner = Target(primary_name=f"{TEST_MARK}_winner", aliases=[f"{TEST_MARK}_loser"])
        s.add_all([loser, winner])
        await s.flush()

        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic_unmerge")
        s.add(mosaic)
        await s.flush()

        # Panel currently owned by the winner post-merge (as merge_targets
        # would have reassigned it), with an object_pattern that names the loser.
        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=winner.id,
            panel_label="Panel 1",
            object_pattern=f"%{TEST_MARK}_loser%Panel%1%",
        )
        s.add(panel)
        await s.flush()

        img = _img(resolved_target_id=winner.id, panel_label="Panel 1", panel_id=panel.id)
        s.add(img)
        await s.flush()

        s.add(MergeManifest(
            winner_id=winner.id, loser_id=loser.id,
            payload={"image_ids": [str(img.id)], "notes_rekeyed": [], "notes_appended": [], "ccv_rekeyed": []},
        ))
        loser.merged_into_id = winner.id
        await s.commit()

        result = await unmerge_target(loser.id, s)
        assert result["status"] == "ok"

        refreshed_img = await s.get(Image, img.id)
        refreshed_panel = await s.get(MosaicPanel, panel.id)

        assert refreshed_img.resolved_target_id == loser.id
        assert refreshed_panel.target_id == loser.id
        # The recompute correctly re-resolved panel_id under the loser
        # (matching by (target_id, panel_label)) rather than clearing it.
        assert refreshed_img.panel_id == panel.id


@pytest.mark.asyncio
async def test_filename_candidate_accept_populates_panel_membership(api_client, db):
    """Orphan-to-target attach: images that were never target-resolved (and
    so never had panel membership attempted at ingest) gain panel_id once
    a filename candidate assigns them a target with a matching simple panel."""
    Session = db
    async with Session() as s:
        target = Target(primary_name=f"{TEST_MARK}_fnattach", aliases=[])
        s.add(target)
        await s.flush()
        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic_fnattach")
        s.add(mosaic)
        await s.flush()
        panel = MosaicPanel(mosaic_id=mosaic.id, target_id=target.id,
                             panel_label=f"{TEST_MARK}_fnattach_panel", object_pattern=None)
        s.add(panel)
        await s.flush()

        img = _img(resolved_target_id=None, panel_label=None, panel_id=None)
        s.add(img)
        await s.flush()

        candidate = FilenameCandidate(
            extracted_name=f"{TEST_MARK}_fnattach",
            suggested_target_id=target.id,
            method="path",
            confidence=0.9,
            status="pending",
            file_count=1,
            file_paths=[img.file_path],
            image_ids=[img.id],
        )
        s.add(candidate)
        await s.commit()
        candidate_id = candidate.id
        target_id = target.id
        panel_id = panel.id
        img_id = img.id

    resp = await api_client.post(
        f"/api/filename-resolution/candidates/{candidate_id}/accept",
        json={"target_id": str(target_id)},
    )
    assert resp.status_code == 200

    async with Session() as s2:
        refreshed = await s2.get(Image, img_id)
        assert refreshed.resolved_target_id == target_id
        assert refreshed.panel_id == panel_id
