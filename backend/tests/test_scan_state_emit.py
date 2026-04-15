import os, sys, json
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
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _redis(total=5, completed=5, failed=0, new_files=5):
    r = MagicMock()
    r.hgetall.return_value = {
        "state": "ingesting", "total": str(total), "completed": str(completed),
        "failed": str(failed), "started_at": "1700000000.0", "completed_at": "",
        "new_files": str(new_files), "changed_files": "0", "removed": "0",
        "csv_enriched": "0", "skipped_calibration": "0",
    }
    r.hset = MagicMock()
    r.expire = MagicMock()
    r.delete = MagicMock()
    r.lrange.return_value = []
    return r


def test_check_complete_sync_calls_emit_sync_on_completion():
    from app.services.scan_state import check_complete_sync
    r = _redis()
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "category": category, "severity": severity})

    mock_session = MagicMock()

    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    assert any(e["event_type"] == "scan_complete" for e in emit_calls)
    ev = next(e for e in emit_calls if e["event_type"] == "scan_complete")
    assert ev["category"] == "scan"
    assert ev["severity"] == "info"


def test_check_complete_sync_no_emit_when_in_progress():
    from app.services.scan_state import check_complete_sync
    r = _redis(total=10, completed=5, failed=0)
    emit_calls = []

    def fake_emit(*a, **kw):
        emit_calls.append(True)

    with patch("app.services.scan_state.emit_sync", fake_emit):
        check_complete_sync(r)

    assert len(emit_calls) == 0


def test_scan_files_failed_emitted_when_failures_occur():
    from app.services.scan_state import check_complete_sync
    r = _redis(total=3, completed=2, failed=1, new_files=3)
    r.lrange.return_value = [json.dumps({"file": "/fits/bad.fits", "error": "parse error"})]
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    mock_session = MagicMock()

    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    failure_evs = [e for e in emit_calls if e["event_type"] == "scan_files_failed"]
    assert len(failure_evs) == 1
    assert failure_evs[0]["details"]["failed_files"][0]["path"] == "/fits/bad.fits"
    assert "truncated" in failure_evs[0]["details"]
