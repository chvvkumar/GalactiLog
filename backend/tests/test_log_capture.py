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


def test_handler_drops_drain_task_noise_below_warning():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "debug"
    h = RedisLogHandler(source="beat", redis_factory=lambda: fake)
    # Beat scheduler / task-trace lines for the every-5s drain task are noise.
    h.emit(make_record(
        name="celery.beat", level=logging.INFO,
        msg="Scheduler: Sending due task drain-app-logs (app.worker.drain_logs.drain_app_logs)",
    ))
    h.emit(make_record(
        name="celery.app.trace", level=logging.INFO,
        msg="Task app.worker.drain_logs.drain_app_logs[abc] succeeded in 0.004s",
    ))
    assert "app_logs:buffer" not in fake.lists


def test_handler_keeps_other_celery_task_logs_at_debug():
    fake = FakeRedis()
    fake.kv["app_logs:capture_level"] = "debug"
    h = RedisLogHandler(source="worker", redis_factory=lambda: fake)
    # Real task activity (scans etc.) must still be captured at info/debug.
    h.emit(make_record(
        name="celery.app.trace", level=logging.INFO,
        msg="Task app.worker.tasks.run_scan[xyz] succeeded in 8.7s",
    ))
    assert len(fake.lists["app_logs:buffer"]) == 1


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


def test_handler_self_heals_after_failure():
    # First client raises on lpush; the handler should reset and rebuild on the
    # next emit, succeeding with a healthy client.
    healthy = FakeRedis()
    healthy.kv["app_logs:capture_level"] = "warning"

    class Flaky:
        def get(self, key):
            return "warning"

        def lpush(self, *a):
            raise RuntimeError("redis down")

        def ltrim(self, *a):
            pass

    clients = [Flaky(), healthy]

    def factory():
        return clients.pop(0)

    h = RedisLogHandler(source="api", redis_factory=factory)
    h.emit(make_record(level=logging.WARNING, msg="first"))  # fails, resets client
    assert h._redis is None
    h.emit(make_record(level=logging.WARNING, msg="second"))  # rebuilds -> healthy
    assert len(healthy.lists["app_logs:buffer"]) == 1


def test_default_factory_uses_short_socket_timeouts():
    from app.services.log_capture import _default_redis_factory, _REDIS_SOCKET_TIMEOUT
    client = _default_redis_factory()
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs.get("socket_connect_timeout") == _REDIS_SOCKET_TIMEOUT
    assert kwargs.get("socket_timeout") == _REDIS_SOCKET_TIMEOUT
