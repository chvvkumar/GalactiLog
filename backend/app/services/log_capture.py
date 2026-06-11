"""Backend log capture handler.

A logging.Handler that serializes log records to JSON and pushes them onto a
capped Redis list (app_logs:buffer). A Celery beat task drains the buffer into
the app_logs table. This keeps the logging hot path off the DB connection pool
and works identically across uvicorn, Celery worker, and beat processes.

The effective capture floor is read at runtime from a Redis key
(app_logs:capture_level), cached briefly so toggling the level on the Activity
Log settings tab takes effect within a few seconds without a process restart.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import redis as sync_redis

from app.config import settings

BUFFER_KEY = "app_logs:buffer"
CAPTURE_LEVEL_KEY = "app_logs:capture_level"
BUFFER_MAX = 10000
DEFAULT_LEVEL = "warning"

# Short socket timeouts so a slow/down Redis cannot stall the request handling
# (or worker) thread that emitted the log. The handler buffers logs as a
# best-effort side channel; dropping a few records is preferable to blocking.
_REDIS_SOCKET_TIMEOUT = 0.15


def _default_redis_factory() -> sync_redis.Redis:
    """Build a Redis client local to the log handler with short socket timeouts.

    Intentionally separate from the shared get_sync_redis() so the aggressive
    timeouts here do not affect other call sites.
    """
    return sync_redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
        socket_timeout=_REDIS_SOCKET_TIMEOUT,
    )

LEVEL_ORDER = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}

# logging.Handler has no formatException; that lives on Formatter. Use a shared
# default formatter to render exc_info into a traceback string.
_FORMATTER = logging.Formatter()

# Always excluded (noisy / recursion risk)
_ALWAYS_EXCLUDE = {"uvicorn.access", __name__}
# Excluded unless WARNING+.
_NOISY_PREFIXES = ("sqlalchemy.engine", "asyncio", "aiormq", "urllib3", "celery.utils")

# The drain task runs every 5s. Its own beat-scheduler and task-lifecycle log
# lines would flood the log at an info/debug capture floor, so they are dropped
# below WARNING. Matched by the task name appearing in the message; other task
# activity (scans, thumbnails, enrichment) is kept so the log stays useful.
_DRAIN_TASK_MARKER = "drain_app_logs"


class RedisLogHandler(logging.Handler):
    def __init__(self, source: str, redis_factory=_default_redis_factory, cache_ttl: float = 5.0):
        super().__init__(level=logging.DEBUG)
        self.source = source
        self._redis_factory = redis_factory
        self._redis = None
        self._cache_ttl = cache_ttl
        self._level_cache = (DEFAULT_LEVEL, 0.0)

    def _redis_client(self):
        if self._redis is None:
            self._redis = self._redis_factory()
        return self._redis

    def _capture_floor(self) -> int:
        value, ts = self._level_cache
        if time.monotonic() - ts > self._cache_ttl:
            try:
                raw = self._redis_client().get(CAPTURE_LEVEL_KEY)
                value = raw if raw in LEVEL_ORDER else DEFAULT_LEVEL
            except Exception:
                # Drop a possibly-broken client so the next call rebuilds it.
                self._redis = None
                value = DEFAULT_LEVEL
            self._level_cache = (value, time.monotonic())
        return LEVEL_ORDER[value]

    def _excluded(self, record: logging.LogRecord) -> bool:
        if record.name in _ALWAYS_EXCLUDE:
            return True
        if record.levelno < logging.WARNING:
            if record.name.startswith(_NOISY_PREFIXES):
                return True
            try:
                if _DRAIN_TASK_MARKER in record.getMessage():
                    return True
            except Exception:
                pass
        return False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._excluded(record):
                return
            level = record.levelname.lower()
            if LEVEL_ORDER.get(level, 100) < self._capture_floor():
                return
            tb = _FORMATTER.formatException(record.exc_info) if record.exc_info else None
            payload = json.dumps({
                "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": level,
                "source": self.source,
                "logger": record.name,
                "message": record.getMessage(),
                "traceback": tb,
            })
            r = self._redis_client()
            r.lpush(BUFFER_KEY, payload)
            r.ltrim(BUFFER_KEY, 0, BUFFER_MAX - 1)
        except Exception:
            # Logging must never raise. Drop a possibly-broken client so the
            # next emit rebuilds it instead of staying broken until restart.
            self._redis = None
