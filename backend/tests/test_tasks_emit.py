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
