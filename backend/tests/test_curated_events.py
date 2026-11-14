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


async def _run_handler(monkeypatch, method, path, exc):
    """Call the 5xx handler with emit stubbed; return (response, emit kwargs)."""
    from app.main import create_app

    handler = create_app().exception_handlers.get(Exception)
    captured = {}

    async def fake_emit(session, **kw):
        captured.update(kw)
        return 1

    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    monkeypatch.setattr("app.services.activity.emit", fake_emit)
    monkeypatch.setattr("app.main.async_session", fake_session)

    request = MagicMock()
    request.method = method
    request.url.path = path
    request.state.user = None
    return await handler(request, exc), captured


def _simbad_both_mirrors_down():
    """NonTransientError as catalog_cache builds it when both SIMBAD mirrors fail."""
    import httpx
    from app.services import catalog_cache as cc
    from app.services.upstream import request_with_fallback

    class FakeClient:
        def post(self, url, **kw):
            req = httpx.Request("POST", url)
            if "cds.unistra.fr" in url:
                resp = httpx.Response(404, request=req)
                raise httpx.HTTPStatusError(
                    f"Client error '404 Not Found' for url '{url}'", request=req, response=resp,
                )
            raise httpx.ReadTimeout("The read operation timed out", request=req)

    urls = [
        "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
        "https://simbad.harvard.edu/simbad/sim-tap/sync",
    ]
    try:
        request_with_fallback(FakeClient(), "POST", urls, service="simbad")
    except httpx.HTTPError as exc:
        err = cc._non_transient("simbad", "IC 1396", exc)
        err.__cause__ = exc
        return err
    raise AssertionError("request_with_fallback did not raise")


@pytest.mark.asyncio
async def test_5xx_handler_upstream_failure_is_readable_502(monkeypatch):
    import json

    exc = _simbad_both_mirrors_down()
    resp, captured = await _run_handler(monkeypatch, "POST", "/api/targets/orphan-preview", exc)

    expected = (
        "SIMBAD lookup for 'IC 1396' failed: SIMBAD is unavailable: "
        "simbad.cds.unistra.fr returned HTTP 404 (Not Found); "
        "simbad.harvard.edu timed out"
    )
    assert resp.status_code == 502
    assert json.loads(resp.body) == {"detail": expected}
    # The message leads with the cause, not the route or the class name.
    assert captured["message"] == f"{expected} (POST /api/targets/orphan-preview)"
    assert captured["severity"] == "error"
    assert captured["event_type"] == "api_error"

    details = captured["details"]
    assert details["method"] == "POST"
    assert details["path"] == "/api/targets/orphan-preview"
    assert details["exception_type"] == "NonTransientError"
    assert details["exception"] == str(exc)[:500]
    # The raw httpx text survives in the chain for debugging, but never
    # reaches the client.
    assert "ReadTimeout: The read operation timed out" in details["error_chain"]
    assert "read operation" not in resp.body.decode()
    json.dumps(details)


@pytest.mark.asyncio
async def test_5xx_handler_bare_httpx_error_stays_generic_500(monkeypatch):
    """A bare httpx error may name a private host, so the client gets nothing."""
    import json
    import httpx

    req = httpx.Request("GET", "http://nina.lan:1888/v2/api?secret=1")
    exc = httpx.ConnectError("[Errno 111] Connection refused", request=req)
    resp, captured = await _run_handler(monkeypatch, "GET", "/api/x", exc)

    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "Internal server error"}
    # The admin-only activity log still gets the readable cause.
    assert captured["message"].startswith("GET /api/x failed: ConnectError")
    assert "nina.lan" in captured["message"]
    assert captured["details"]["exception_type"] == "ConnectError"


@pytest.mark.asyncio
async def test_5xx_handler_fallback_failure_in_cause_chain_is_502(monkeypatch):
    """An ``attempts`` error from request_with_fallback is a catalog failure,
    even when a route wrapped it in something else."""
    import json

    fallback_exc = _simbad_both_mirrors_down().__cause__
    assert hasattr(fallback_exc, "attempts")
    expected = (
        "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found); "
        "simbad.harvard.edu timed out"
    )

    resp, captured = await _run_handler(monkeypatch, "GET", "/api/x", fallback_exc)
    assert resp.status_code == 502
    assert json.loads(resp.body) == {"detail": expected}
    assert captured["message"] == f"{expected} (GET /api/x)"
    json.dumps(captured["details"])

    wrapped = RuntimeError("internal text that must not leak")
    wrapped.__cause__ = fallback_exc
    resp, captured = await _run_handler(monkeypatch, "GET", "/api/x", wrapped)
    assert resp.status_code == 502
    assert json.loads(resp.body) == {"detail": expected}
    assert captured["details"]["exception_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_5xx_handler_non_upstream_cause_chain_stays_500(monkeypatch):
    """A cause chain with no catalog failure in it never opens the 502 path,
    even when a link is a bare httpx error."""
    import json
    import httpx

    for cause in (
        KeyError("inner secret"),
        httpx.ReadTimeout("timed out", request=httpx.Request("GET", "http://nina.lan/x")),
    ):
        exc = RuntimeError("outer secret")
        exc.__cause__ = cause
        resp, captured = await _run_handler(monkeypatch, "GET", "/api/x", exc)

        assert resp.status_code == 500
        assert json.loads(resp.body) == {"detail": "Internal server error"}
        assert captured["message"].startswith("GET /api/x failed: RuntimeError")
        assert type(cause).__name__ in captured["details"]["error_chain"]


@pytest.mark.asyncio
async def test_5xx_handler_catalog_outage_error_is_502(monkeypatch):
    """CatalogOutageError (a lookup that got no answer) reads as a 502."""
    import json
    import httpx
    from app.services import catalog_cache as cc

    cc.clear_outages()
    cc._mark_outage("simbad", httpx.ReadTimeout("The read operation timed out"))
    try:
        with pytest.raises(cc.CatalogOutageError) as raised:
            cc.raise_if_outage("simbad", "sesame", key="IC 1396")
    finally:
        cc.clear_outages()

    resp, captured = await _run_handler(
        monkeypatch, "POST", "/api/targets/orphan-preview", raised.value,
    )
    assert resp.status_code == 502
    detail = json.loads(resp.body)["detail"]
    assert detail.startswith("SIMBAD lookup for 'IC 1396' could not be completed: ")
    assert captured["message"] == f"{detail} (POST /api/targets/orphan-preview)"
    assert captured["details"]["exception_type"] == "CatalogOutageError"


@pytest.mark.asyncio
async def test_5xx_handler_generic_error_keeps_prefix_and_hides_text(monkeypatch):
    import json

    resp, captured = await _run_handler(monkeypatch, "POST", "/api/targets", ValueError("bad input"))

    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "Internal server error"}
    assert captured["message"].startswith("POST /api/targets failed: ValueError")
    assert "bad input" in captured["message"]
    details = captured["details"]
    assert details["exception_type"] == "ValueError"
    assert details["exception"] == "bad input"
    assert "bad input" in details["error_chain"]
    json.dumps(details)


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
    # get_sync_redis is imported lazily inside the function from app.config
    monkeypatch.setattr("app.config.get_sync_redis", lambda: MagicMock())
    # Reset the lazily-built module-level engine so the patched create_engine runs.
    monkeypatch.setattr(cmod, "_task_event_engine", None, raising=False)

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
    monkeypatch.setattr(cmod, "_task_event_engine", None, raising=False)

    cmod._emit_task_event("task_retry", "warning", "app.worker.tasks.x", "id1", Exception("retry"))

    assert captured["event_type"] == "task_retry"
    assert captured["severity"] == "warning"
