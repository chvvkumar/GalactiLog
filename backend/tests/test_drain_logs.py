import json
import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.worker.drain_logs import _drain_once  # noqa: E402


class FakeRedis:
    def __init__(self, entries):
        self.lists = {"app_logs:buffer": list(entries)}

    def rpop(self, key, count=None):
        lst = self.lists.get(key, [])
        if not lst:
            return None
        if count is None:
            return lst.pop()
        out = []
        for _ in range(min(count, len(lst))):
            out.append(lst.pop())
        return out


def _entry(level="warning", msg="m"):
    return json.dumps({
        "timestamp": "2026-06-11T00:00:00+00:00",
        "level": level, "source": "api", "logger": "app.x",
        "message": msg, "traceback": None,
    })


def test_drain_once_returns_parsed_rows():
    fake = FakeRedis([_entry(msg="a"), _entry(msg="b"), "not-json"])
    rows = _drain_once(fake, batch=500)
    # malformed entry skipped, two valid rows
    assert len(rows) == 2
    msgs = {r["message"] for r in rows}
    assert msgs == {"a", "b"}


def test_drain_once_empty():
    fake = FakeRedis([])
    assert _drain_once(fake, batch=500) == []


def test_drain_task_in_beat_schedule():
    from app.worker.celery_app import celery_app
    schedule = celery_app.conf.beat_schedule
    assert "drain-app-logs" in schedule
    entry = schedule["drain-app-logs"]
    assert entry["task"] == "app.worker.drain_logs.drain_app_logs"
    assert entry["schedule"] == 5.0
