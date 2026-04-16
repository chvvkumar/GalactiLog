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
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _make_session(deleted_count, retention_days=90):
    mock_result = MagicMock()
    mock_result.rowcount = deleted_count
    mock_settings = MagicMock()
    mock_settings.general = {"activity_retention_days": retention_days}
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = mock_settings
    call_count = [0]

    def _execute(stmt, *a, **kw):
        call_count[0] += 1
        return settings_result if call_count[0] == 1 else mock_result

    session = MagicMock()
    session.execute = _execute
    session.commit = MagicMock()
    return session


def test_prune_deletes_old_rows_and_emits():
    from app.worker.prune_activity import prune_activity_events
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    with patch("app.worker.prune_activity.Session") as ms, \
         patch("app.worker.prune_activity.emit_sync", fake_emit), \
         patch("app.worker.prune_activity.get_sync_redis", return_value=MagicMock()):
        session = _make_session(deleted_count=12)
        ms.return_value.__enter__ = lambda s, *a: session
        ms.return_value.__exit__ = lambda s, *a: None
        result = prune_activity_events.run()

    assert result["deleted"] == 12
    evs = [e for e in emit_calls if e["event_type"] == "activity_pruned"]
    assert len(evs) == 1
    assert evs[0]["details"]["deleted_count"] == 12


def test_prune_silent_when_zero_deleted():
    from app.worker.prune_activity import prune_activity_events
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append(event_type)

    with patch("app.worker.prune_activity.Session") as ms, \
         patch("app.worker.prune_activity.emit_sync", fake_emit), \
         patch("app.worker.prune_activity.get_sync_redis", return_value=MagicMock()):
        session = _make_session(deleted_count=0)
        ms.return_value.__enter__ = lambda s, *a: session
        ms.return_value.__exit__ = lambda s, *a: None
        result = prune_activity_events.run()

    assert result["deleted"] == 0
    assert "activity_pruned" not in emit_calls


def test_prune_task_in_beat_schedule():
    from app.worker.celery_app import celery_app
    schedule = celery_app.conf.beat_schedule
    assert "prune-activity-events" in schedule
    entry = schedule["prune-activity-events"]
    assert entry["task"] == "app.worker.prune_activity.prune_activity_events"
