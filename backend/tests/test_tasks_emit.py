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


TASKS_PATH = pathlib.Path("app/worker/tasks.py")


def _run_scan_source() -> str:
    src = TASKS_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_scan":
            return ast.get_source_segment(src, node)
    raise AssertionError("run_scan not found in tasks.py")


def test_run_scan_uses_emit_sync_not_append_activity_sync():
    """The 5 scan emit sites inside run_scan must use emit_sync, not append_activity_sync."""
    run_scan_src = _run_scan_source()
    assert "append_activity_sync(" not in run_scan_src, (
        "run_scan still contains append_activity_sync() calls; "
        "all 5 scan emit sites should use _emit_activity_sync()"
    )
    # All 5 sites should be migrated.
    assert run_scan_src.count("_emit_activity_sync(") >= 5, (
        "run_scan should contain at least 5 _emit_activity_sync() calls "
        "(scan_stopped, delta_scan, orphan_cleanup, orphan_warning, scan_complete)"
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


def _bootstrap_real_tasks():
    """Replace the conftest MagicMock stub with the real app.worker.tasks module."""
    import sys as _sys
    mod = _sys.modules.get("app.worker.tasks")
    if mod is not None and not isinstance(mod, MagicMock):
        return mod
    _sys.modules.pop("app.worker.tasks", None)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_engine)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    with patch("sqlalchemy.create_engine", return_value=mock_engine):
        import app.worker.tasks as tasks_mod
    return tasks_mod


def test_enrichment_query_failed_emits_after_rebuild():
    import pathlib
    src = pathlib.Path("app/worker/tasks.py").read_text()
    assert "enrichment_query_failed" in src


def test_filename_candidate_failed_event_type_present():
    import pathlib
    src = pathlib.Path("app/worker/tasks.py").read_text()
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
    orphan_rows = [(i, None) for i, _ in enumerate(sorted(orphaned))]

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


def test_mosaic_detection_complete_emits():
    tasks_mod = _bootstrap_real_tasks()
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
