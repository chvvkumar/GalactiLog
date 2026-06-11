import json
import logging
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

from app.services.log_capture import RedisLogHandler, LEVEL_ORDER  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.kv = {}

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    def get(self, key):
        return self.kv.get(key)


def make_record(name="app.test", level=logging.WARNING, msg="hello"):
    return logging.LogRecord(name, level, "f.py", 1, msg, None, None)


def test_handler_pushes_warning_when_floor_is_warning():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "warning"
    h = RedisLogHandler(source="api", redis_factory=lambda: fake)
    h.emit(make_record(level=logging.WARNING, msg="warn!"))
    assert len(fake.lists["app_logs:buffer"]) == 1
    payload = json.loads(fake.lists["app_logs:buffer"][0])
    assert payload["level"] == "warning"
    assert payload["source"] == "api"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "warn!"
    assert payload["traceback"] is None


def test_handler_drops_below_floor():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "warning"
    h = RedisLogHandler(source="api", redis_factory=lambda: fake)
    h.emit(make_record(level=logging.INFO))
    assert "app_logs:buffer" not in fake.lists


def test_handler_excludes_uvicorn_access():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "debug"
    h = RedisLogHandler(source="api", redis_factory=lambda: fake)
    h.emit(make_record(name="uvicorn.access", level=logging.INFO))
    assert "app_logs:buffer" not in fake.lists


def test_handler_captures_traceback():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "error"
    h = RedisLogHandler(source="worker", redis_factory=lambda: fake)
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord("app.x", logging.ERROR, "f.py", 1, "failed", None, sys.exc_info())
    h.emit(rec)
    payload = json.loads(fake.lists["app_logs:buffer"][0])
    assert "ValueError: boom" in payload["traceback"]


def test_handler_never_raises():
    class Broken:
        def get(self, key):
            return "warning"

        def lpush(self, *a):
            raise RuntimeError("redis down")

        def ltrim(self, *a):
            pass

    h = RedisLogHandler(source="api", redis_factory=lambda: Broken())
    h.emit(make_record())  # must not raise


def test_level_order_constant():
    assert LEVEL_ORDER["debug"] < LEVEL_ORDER["warning"] < LEVEL_ORDER["error"]
