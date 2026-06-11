"""Tests for curated emit() points added for the application log feature.

Covers the api_error 5xx handler (Task 9) and the Celery task_failure /
task_retry signal emits (Task 12). Auth and settings emit points (Tasks 10-11)
are exercised by their own API tests; here we assert the lower-level builders /
handlers that can be tested in isolation without a live DB.
"""
import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())


# ---------------------------------------------------------------------------
# Task 9: api_error on unhandled 5xx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_5xx_handler_emits_api_error(monkeypatch):
    from app.main import create_app

    application = create_app()
    handler = application.exception_handlers.get(Exception)
    assert handler is not None

    captured = {}

    async def fake_emit(session, *, category, severity, event_type, message, **kw):
        captured.update(
            category=category, severity=severity, event_type=event_type,
            message=message, details=kw.get("details"), actor=kw.get("actor"),
        )
        return 1

    # Stub the fresh-session context manager and the emit helper.
    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    monkeypatch.setattr("app.services.activity.emit", fake_emit)
    monkeypatch.setattr("app.main.async_session", fake_session)

    request = MagicMock()
    request.method = "POST"
    request.url.path = "/api/targets"
    request.state.user = None  # no authenticated user

    resp = await handler(request, ValueError("boom"))

    assert resp.status_code == 500
    assert captured["event_type"] == "api_error"
    assert captured["category"] == "system"
    assert captured["severity"] == "error"
    assert "POST /api/targets failed: ValueError" in captured["message"]
    assert captured["details"]["path"] == "/api/targets"
    assert captured["details"]["method"] == "POST"


@pytest.mark.asyncio
async def test_5xx_handler_still_returns_500_when_emit_fails(monkeypatch):
    from app.main import create_app

    application = create_app()
    handler = application.exception_handlers.get(Exception)

    async def boom_emit(*a, **kw):
        raise RuntimeError("db down")

    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    monkeypatch.setattr("app.services.activity.emit", boom_emit)
    monkeypatch.setattr("app.main.async_session", fake_session)

    request = MagicMock()
    request.method = "GET"
    request.url.path = "/api/x"
    request.state.user = None

    resp = await handler(request, RuntimeError("kaboom"))
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Task 12: Celery task_failure / task_retry signal emits
# ---------------------------------------------------------------------------

def test_emit_task_event_writes_event(monkeypatch):
    import app.worker.celery_app as cmod

    captured = {}

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        captured.update(
            category=category, severity=severity, event_type=event_type,
            message=message, details=kw.get("details"), actor=kw.get("actor"),
        )
        return 1

    fake_engine = MagicMock()
    monkeypatch.setattr("app.services.activity.emit_sync", fake_emit_sync)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: fake_engine)
    monkeypatch.setattr(cmod, "get_sync_redis", lambda: MagicMock(), raising=False)
    # get_sync_redis is imported lazily inside the function from app.config
    monkeypatch.setattr("app.config.get_sync_redis", lambda: MagicMock())

    cmod._emit_task_event("task_failure", "error", "app.worker.tasks.ingest_file", "abc123", ValueError("boom"))

    assert captured["event_type"] == "task_failure"
    assert captured["severity"] == "error"
    assert captured["category"] == "system"
    assert captured["details"]["task"] == "app.worker.tasks.ingest_file"
    assert captured["details"]["task_id"] == "abc123"


def test_emit_task_event_retry(monkeypatch):
    import app.worker.celery_app as cmod

    captured = {}

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        captured.update(event_type=event_type, severity=severity)
        return 1

    monkeypatch.setattr("app.services.activity.emit_sync", fake_emit_sync)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("app.config.get_sync_redis", lambda: MagicMock())

    cmod._emit_task_event("task_retry", "warning", "app.worker.tasks.x", "id1", Exception("retry"))

    assert captured["event_type"] == "task_retry"
    assert captured["severity"] == "warning"
