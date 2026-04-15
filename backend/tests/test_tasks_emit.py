import ast, pathlib
import os, sys
from unittest.mock import MagicMock
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
