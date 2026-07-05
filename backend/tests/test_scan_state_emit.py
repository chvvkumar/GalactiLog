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


def test_start_scanning_sync_resets_kind_and_clears_dispatch_marker():
    """start_scanning_sync must reset kind back to "scan" (in case a prior
    CSV backfill left kind="csv_backfill" on the shared hash) and clear the
    scan:dispatched marker now that the real state has taken over (AUD-016,
    AUD-030)."""
    from app.services.scan_state import start_scanning_sync, SCAN_DISPATCHED_KEY

    r = MagicMock()
    start_scanning_sync(r)

    mapping = r.hset.call_args.kwargs["mapping"]
    assert mapping["kind"] == "scan"
    assert mapping["state"] == "scanning"
    r.delete.assert_any_call(SCAN_DISPATCHED_KEY)


def test_check_complete_sync_skips_activity_and_cascade_for_csv_backfill_kind():
    """AUD-030: a CSV backfill run reaching "complete" must not emit the
    scan_complete activity or dispatch the post-scan maintenance cascade -
    only a real scan (kind="scan", the default) should do that.
    """
    from app.services.scan_state import check_complete_sync
    r = _redis(total=3, completed=3, failed=0)
    r.hgetall.return_value["kind"] = "csv_backfill"
    emit_calls = []

    def fake_emit(*a, **kw):
        emit_calls.append(True)

    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine") as mock_engine:
        check_complete_sync(r)

    assert emit_calls == []
    mock_engine.assert_not_called()
    # State still transitions to a terminal value and the stats cache is
    # still invalidated - only the scan-specific activity/cascade are skipped.
    r.hset.assert_called_once()
    assert r.hset.call_args.kwargs["mapping"]["state"] == "complete"
    r.expire.assert_called_once()
    r.delete.assert_called_once_with("galactilog:stats:cache", "galactilog:fits_keys")


def test_check_complete_sync_default_kind_still_runs_scan_cascade():
    """A hash with no "kind" field (every pre-existing real scan) is treated
    as kind="scan" and keeps emitting the scan_complete activity.
    """
    from app.services.scan_state import check_complete_sync
    r = _redis()
    assert "kind" not in r.hgetall.return_value
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append(event_type)

    mock_session = MagicMock()
    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    assert "scan_complete" in emit_calls


def test_thumbnail_regen_failed_emitted_for_thumbnail_failures():
    import json
    from app.services.scan_state import check_complete_sync
    r = _redis(total=3, completed=2, failed=1, new_files=0)
    r.lrange.return_value = [
        json.dumps({"file": "/tmp/test_thumbnails/bad_abc123.jpg", "error": "stretch error"})
    ]
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "category": category})

    mock_session = MagicMock()
    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    ev_types = [e["event_type"] for e in emit_calls]
    assert "thumbnail_regen_failed" in ev_types


def test_add_skipped_path_sync_refreshes_ttl():
    """3.3: every insert refreshes the 7-day backstop TTL, not just rebuilds."""
    from app.services.scan_state import add_skipped_path_sync, SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL
    r = MagicMock()
    add_skipped_path_sync(r, "/data/dark_001.fits")
    r.sadd.assert_called_once_with(SCAN_SKIPPED_PATHS_KEY, "/data/dark_001.fits")
    r.expire.assert_called_once_with(SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL)


def test_rebuild_skipped_paths_sync_replaces_set_with_ttl():
    from app.services.scan_state import rebuild_skipped_paths_sync, SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe

    rebuild_skipped_paths_sync(r, {"/data/a.fits", "/data/b.fits"})

    pipe.delete.assert_called_once_with(SCAN_SKIPPED_PATHS_KEY)
    assert pipe.sadd.call_args[0][0] == SCAN_SKIPPED_PATHS_KEY
    assert set(pipe.sadd.call_args[0][1:]) == {"/data/a.fits", "/data/b.fits"}
    pipe.expire.assert_called_once_with(SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL)
    pipe.execute.assert_called_once()


def test_rebuild_skipped_paths_sync_empty_still_deletes_key():
    """An empty rebuild (no paths survived) must still clear the stale set,
    but skips the now-pointless sadd/expire (nothing to expire)."""
    from app.services.scan_state import rebuild_skipped_paths_sync, SCAN_SKIPPED_PATHS_KEY
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe

    rebuild_skipped_paths_sync(r, set())

    pipe.delete.assert_called_once_with(SCAN_SKIPPED_PATHS_KEY)
    pipe.sadd.assert_not_called()
    pipe.expire.assert_not_called()
    pipe.execute.assert_called_once()
