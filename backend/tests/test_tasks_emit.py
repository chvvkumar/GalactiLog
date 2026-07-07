import ast, pathlib
import os, sys
from unittest.mock import MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# run_scan lives in tasks_scan.py since the Phase 6 Task 3 module split;
# tasks.py is now a thin facade that only imports/re-exports it.
TASKS_PATH = pathlib.Path("app/worker/tasks_scan.py")
ORPHAN_CLEANUP_PATH = pathlib.Path("app/services/orphan_cleanup.py")


def _run_scan_source() -> str:
    src = TASKS_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_scan":
            return ast.get_source_segment(src, node)
    raise AssertionError("run_scan not found in tasks_scan.py")


def test_run_scan_uses_emit_sync_not_append_activity_sync():
    """The scan emit sites must use emit_sync, not append_activity_sync.

    scan_stopped, delta_scan, and scan_complete stay inline in run_scan.
    orphan_cleanup, orphan_force_warning, and orphan_warning were extracted
    into app.services.orphan_cleanup.cleanup_orphaned_images (Phase 6 Task 4)
    -- run_scan forwards its own _emit_activity_sync reference into that
    call, so the emit sites still resolve to the same function, just via the
    `emit_fn` parameter instead of the module-level name directly.
    """
    run_scan_src = _run_scan_source()
    orphan_cleanup_src = ORPHAN_CLEANUP_PATH.read_text()
    assert "append_activity_sync(" not in run_scan_src, (
        "run_scan still contains append_activity_sync() calls; "
        "all scan emit sites should use _emit_activity_sync()"
    )
    assert "append_activity_sync(" not in orphan_cleanup_src, (
        "orphan_cleanup still contains append_activity_sync() calls; "
        "all scan emit sites should use emit_sync()"
    )
    # All 6 sites (across both modules) should be migrated.
    total_emit_calls = (
        run_scan_src.count("_emit_activity_sync(")
        + orphan_cleanup_src.count("emit_fn(")
    )
    assert total_emit_calls >= 5, (
        "expected at least 5 emit_sync-based calls across run_scan and "
        "orphan_cleanup (scan_stopped, delta_scan, orphan_cleanup, "
        "orphan_force_warning, orphan_warning, scan_complete)"
    )


def test_append_activity_sync_not_imported_in_tasks():
    src = TASKS_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "scan_state" in node.module:
                names = [a.name for a in node.names]
                assert "append_activity_sync" not in names, \
                    "append_activity_sync still imported in tasks.py"


def test_emit_sync_imported_in_tasks():
    src = TASKS_PATH.read_text()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.services.activity":
                names = [a.name for a in node.names]
                if "emit_sync" in names:
                    found = True
    assert found, "emit_sync not imported from app.services.activity in tasks.py"


def _bootstrap_real_tasks(modname="app.worker.tasks_scan"):
    """Load the real target module, patching create_engine so it doesn't need
    a live DB connection at import time.

    run_scan lives in tasks_scan.py and detect_mosaic_panels_task lives in
    tasks_mosaics.py since the Phase 6 Task 3 module split; every patch below
    targets whichever module actually owns the function under test (a
    patch.object() on the app.worker.tasks facade would not affect a function
    whose __globals__ point at a different, real module).
    """
    import sys as _sys
    mod = _sys.modules.get(modname)
    if mod is not None and not isinstance(mod, MagicMock):
        return mod
    _sys.modules.pop(modname, None)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_engine)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    with patch("sqlalchemy.create_engine", return_value=mock_engine):
        import importlib
        mod = importlib.import_module(modname)
    return mod


def test_enrichment_query_failed_emits_after_rebuild():
    import pathlib
    # rebuild_targets/retry_unresolved now live in tasks_target_rebuild.py.
    src = pathlib.Path("app/worker/tasks_target_rebuild.py").read_text()
    assert "enrichment_query_failed" in src


def test_filename_candidate_failed_event_type_present():
    import pathlib
    # _do_ingest now lives in tasks_scan.py.
    src = pathlib.Path("app/worker/tasks_scan.py").read_text()
    assert "filename_candidate_failed" in src


class _FakeSession:
    """Sync Session stand-in shared across every `with Session(...)` block.

    Results are routed by how the caller consumes them, not by block order:
      - `.all()` draws from a shared `all_queue` (the known-paths query, then
        the orphan-batch query). DELETE statements never call `.all()`.
      - `.scalar_one_or_none()` always returns None (the user-settings query,
        which yields empty `general` -> no filters).
    A query is therefore only handed an `.all()` payload when it actually calls
    `.all()`, so changing the order in which run_scan opens Session blocks
    cannot silently misroute results.
    """

    def __init__(self, all_queue):
        self._all_queue = all_queue  # shared list, mutated in place
        self.commit = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        res = MagicMock()
        res.all.side_effect = lambda: self._all_queue.pop(0) if self._all_queue else []
        res.scalar_one_or_none.return_value = None
        return res


def _drive_run_scan(force, known_paths, disk_paths):
    """Run run_scan with all I/O mocked; return the captured emit events."""
    tasks_mod = _bootstrap_real_tasks()

    known_rows = [(p, 100, 1.0) for p in known_paths]
    orphaned = set(known_paths) - set(disk_paths)
    orphan_rows = [(i, None, None) for i, _ in enumerate(sorted(orphaned))]

    emit_calls = []

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({
            "event_type": event_type, "severity": severity,
            "message": message, "details": kw.get("details"),
        })

    # Payloads consumed by `.all()`, in the order those queries run: the
    # known-paths query, then the orphan-batch query. The user-settings query
    # uses `.scalar_one_or_none()` and draws nothing from this queue.
    all_queue = [known_rows, orphan_rows]

    def session_factory(*a, **k):
        return _FakeSession(all_queue)

    # ScanFilterConfig with no rules => should_include_file() True for everything,
    # and roots() yields the fits_root once.
    fake_cfg = MagicMock()
    fake_cfg.should_include_file.return_value = True
    fake_cfg.roots.return_value = [tasks_mod.Path("/tmp/test_fits")]

    mock_redis = MagicMock()
    mock_actx = MagicMock()
    mock_actx.__enter__ = lambda s, *a: MagicMock()
    mock_actx.__exit__ = lambda s, *a: None

    with patch.object(tasks_mod, "Session", session_factory), \
         patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "_emit_activity_sync", fake_emit_sync), \
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
        result = tasks_mod.run_scan.run(force_orphan_cleanup=force)

    return result, emit_calls


def test_force_orphan_cleanup_bypasses_threshold_and_warns():
    """A forced full-deletion scan removes all orphans and emits the warning."""
    known = ["/tmp/test_fits/a.fits", "/tmp/test_fits/b.fits", "/tmp/test_fits/c.fits"]
    # Empty disk => 100% missing, which the unforced guard would skip.
    result, emit_calls = _drive_run_scan(force=True, known_paths=known, disk_paths=[])

    assert result["removed"] == 3
    cleanup = [e for e in emit_calls if e["event_type"] == "orphan_cleanup"]
    assert len(cleanup) == 1
    warn = [e for e in emit_calls if e["event_type"] == "orphan_force_warning"]
    assert len(warn) == 1
    assert warn[0]["severity"] == "warning"
    assert warn[0]["details"] == {"removed": 3, "total_known": 3, "forced": True}
    assert "100% of the catalog" in warn[0]["message"]


def test_unforced_full_deletion_skips_cleanup():
    """Without the force flag a 100%-missing scan skips cleanup and warns."""
    known = ["/tmp/test_fits/a.fits", "/tmp/test_fits/b.fits", "/tmp/test_fits/c.fits"]
    result, emit_calls = _drive_run_scan(force=False, known_paths=known, disk_paths=[])

    assert result["removed"] == 0
    assert not [e for e in emit_calls if e["event_type"] == "orphan_cleanup"]
    assert not [e for e in emit_calls if e["event_type"] == "orphan_force_warning"]
    assert [e for e in emit_calls if e["event_type"] == "orphan_warning"]


def test_run_scan_skips_when_run_lock_already_held():
    """AUD-016: a second run_scan execution must bail out immediately instead
    of enumerating the tree twice when SCAN_RUN_LOCK is already held (e.g. a
    duplicate dispatch racing with an in-flight run_scan)."""
    tasks_mod = _bootstrap_real_tasks()

    mock_redis = MagicMock()
    mock_redis.set.return_value = False  # SET NX fails: lock already held

    with patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "start_scanning_sync") as mock_start, \
         patch.object(tasks_mod, "Session") as mock_session_cls:
        result = tasks_mod.run_scan.run()

    assert result == {"status": "skipped", "reason": "already running"}
    mock_redis.set.assert_called_once_with(
        tasks_mod.SCAN_RUN_LOCK, "1", nx=True, ex=tasks_mod.SCAN_RUN_LOCK_TTL
    )
    mock_start.assert_not_called()
    mock_session_cls.assert_not_called()
    # Never acquired the lock, so it must not release someone else's lock.
    mock_redis.delete.assert_not_called()


def test_run_scan_releases_run_lock_after_completing():
    """run_scan releases SCAN_RUN_LOCK via `finally` once it finishes, so a
    subsequent scan (or a retried dispatch) is not blocked forever."""
    tasks_mod = _bootstrap_real_tasks()

    class _EmptySession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            res = MagicMock()
            res.all.return_value = []
            res.scalar_one_or_none.return_value = None
            return res

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # SCAN_RUN_LOCK acquired

    mock_actx = MagicMock()
    mock_actx.__enter__ = lambda s, *a: MagicMock()
    mock_actx.__exit__ = lambda s, *a: None

    fake_cfg = MagicMock()
    fake_cfg.should_include_file.return_value = True
    fake_cfg.roots.return_value = [tasks_mod.Path("/tmp/test_fits")]

    with patch.object(tasks_mod, "Session", lambda *a, **k: _EmptySession()), \
         patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "_activity_session", lambda: mock_actx), \
         patch.object(tasks_mod, "clear_cancel_sync"), \
         patch.object(tasks_mod, "start_scanning_sync"), \
         patch.object(tasks_mod, "get_skipped_paths_sync", return_value=set()), \
         patch.object(tasks_mod, "clear_skipped_paths_sync"), \
         patch.object(tasks_mod, "is_cancel_requested_sync", return_value=False), \
         patch.object(tasks_mod, "set_discovered_sync"), \
         patch.object(tasks_mod, "set_idle_sync"), \
         patch.object(tasks_mod, "generate_reference_thumbnails"), \
         patch.object(tasks_mod, "detect_duplicate_targets"), \
         patch.object(tasks_mod, "backfill_dark_hours"), \
         patch("app.services.scan_filters.ScanFilterConfig.from_settings", return_value=fake_cfg), \
         patch("app.services.scanner.scan_directory", return_value=([], [], set())):
        result = tasks_mod.run_scan.run()

    assert result["status"] == "complete"
    mock_redis.set.assert_any_call(
        tasks_mod.SCAN_RUN_LOCK, "1", nx=True, ex=tasks_mod.SCAN_RUN_LOCK_TTL
    )
    mock_redis.delete.assert_any_call(tasks_mod.SCAN_RUN_LOCK)


def test_run_scan_rebuilds_skipped_paths_dropping_missing_files():
    """3.3: scan:skipped_paths must be rebuilt each excluded-calibration scan to
    only paths still present on disk, not merely accumulated forever."""
    tasks_mod = _bootstrap_real_tasks()

    prior_skipped = {
        "/tmp/test_fits/still_here.fits",
        "/tmp/test_fits/deleted.fits",
    }

    class _EmptySession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            res = MagicMock()
            res.all.return_value = []
            res.scalar_one_or_none.return_value = None
            return res

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    mock_actx = MagicMock()
    mock_actx.__enter__ = lambda s, *a: MagicMock()
    mock_actx.__exit__ = lambda s, *a: None

    fake_cfg = MagicMock()
    fake_cfg.should_include_file.return_value = True
    fake_cfg.roots.return_value = [tasks_mod.Path("/tmp/test_fits")]

    rebuild_calls = []

    def _fake_exists(self):
        return self.name == "still_here.fits"

    with patch.object(tasks_mod, "Session", lambda *a, **k: _EmptySession()), \
         patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "_activity_session", lambda: mock_actx), \
         patch.object(tasks_mod, "clear_cancel_sync"), \
         patch.object(tasks_mod, "start_scanning_sync"), \
         patch.object(tasks_mod, "get_skipped_paths_sync", return_value=set(prior_skipped)), \
         patch.object(tasks_mod, "rebuild_skipped_paths_sync", side_effect=lambda r, p: rebuild_calls.append(p)), \
         patch.object(tasks_mod, "is_cancel_requested_sync", return_value=False), \
         patch.object(tasks_mod, "set_discovered_sync"), \
         patch.object(tasks_mod, "set_idle_sync"), \
         patch.object(tasks_mod, "generate_reference_thumbnails"), \
         patch.object(tasks_mod, "detect_duplicate_targets"), \
         patch.object(tasks_mod, "backfill_dark_hours"), \
         patch("pathlib.Path.exists", _fake_exists), \
         patch("app.services.scan_filters.ScanFilterConfig.from_settings", return_value=fake_cfg), \
         patch("app.services.scanner.scan_directory", return_value=([], [], set())):
        result = tasks_mod.run_scan.run(include_calibration=False)

    assert result["status"] == "complete"
    assert len(rebuild_calls) == 1
    assert rebuild_calls[0] == {"/tmp/test_fits/still_here.fits"}


def test_mosaic_detection_complete_emits():
    tasks_mod = _bootstrap_real_tasks("app.worker.tasks_mosaics")
    detect_mosaic_panels_task = tasks_mod.detect_mosaic_panels_task
    emit_calls = []

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.delete = MagicMock()

    with patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "_emit_activity_sync", fake_emit_sync), \
         patch.object(tasks_mod, "_activity_session") as mf, \
         patch("asyncio.run", return_value=7):
        mctx = MagicMock()
        mctx.__enter__ = lambda s, *a: MagicMock()
        mctx.__exit__ = lambda s, *a: None
        mf.return_value = mctx

        result = detect_mosaic_panels_task.run()

    assert result["status"] == "complete"
    evs = [e for e in emit_calls if e["event_type"] == "mosaic_detection_complete"]
    assert len(evs) == 1
    assert evs[0]["details"]["candidates"] == 7


def test_detection_task_passes_campaign_gap_days_from_settings():
    """The scan-triggered task must read mosaic_campaign_gap_days from settings
    and pass it to detect_mosaic_panels, matching the manual /detect endpoint."""
    import contextlib
    from unittest.mock import AsyncMock

    tasks_mod = _bootstrap_real_tasks("app.worker.tasks_mosaics")
    detect_mosaic_panels_task = tasks_mod.detect_mosaic_panels_task

    # Fake async session: get(UserSettings, ...) returns general with gap=7.
    settings_row = MagicMock()
    settings_row.general = {"mosaic_campaign_gap_days": 7}

    fake_session = AsyncMock()
    fake_session.get = AsyncMock(return_value=settings_row)
    fake_session.commit = AsyncMock()

    @contextlib.asynccontextmanager
    async def _session_cm():
        yield fake_session

    def _sessionmaker(*a, **k):
        return lambda: _session_cm()

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    captured = {}

    async def fake_detect(session, gap_days=0):
        captured["gap_days"] = gap_days
        return 3

    import app.services.mosaic_detection as md

    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.delete = MagicMock()

    mctx = MagicMock()
    mctx.__enter__ = lambda s, *a: MagicMock()
    mctx.__exit__ = lambda s, *a: None

    with patch.object(tasks_mod, "_redis", mock_redis), \
         patch.object(tasks_mod, "_emit_activity_sync", lambda *a, **k: None), \
         patch.object(tasks_mod, "_activity_session", lambda: mctx), \
         patch.object(md, "detect_mosaic_panels", fake_detect), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=fake_engine), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", _sessionmaker):
        result = detect_mosaic_panels_task.run()

    assert result["status"] == "complete"
    assert result["new_suggestions"] == 3
    assert captured["gap_days"] == 7
