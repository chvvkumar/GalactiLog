"""Tests for the global unhandled-exception handler (ARCH-2).

Python-version note: AsyncClient (httpx) + anyio raises an ExceptionGroup when
a BaseHTTPMiddleware (like PrometheusMiddleware) propagates an unhandled exception
in Python 3.13, which bypasses the app-level handler in that transport path.
Starlette's synchronous TestClient does NOT exhibit this issue because it runs the
ASGI app in a thread and collapses the exception group before the handler can be
skipped.  The e2e test below uses TestClient(raise_server_exceptions=False), which
is the correct tool for verifying that the handler fires through the full stack.
Production runs Python 3.12 (Docker image), where the ExceptionGroup quirk does
not arise; this suite covers both the handler unit contract and the full-stack
path using the appropriate client for each.
"""
import json
import pytest
from unittest.mock import MagicMock
from fastapi import APIRouter
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Unit test: handler function contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_500_envelope():
    """The exception handler function must return a 500 JSONResponse with the error envelope."""
    from app.main import create_app
    from starlette.responses import JSONResponse

    application = create_app()

    # Locate the handler directly from the app's exception handlers registry.
    handler = application.exception_handlers.get(Exception)
    assert handler is not None, "No Exception handler registered on the application"

    # Build a minimal mock request with method and url.path attributes.
    mock_request = MagicMock()
    mock_request.method = "GET"
    mock_request.url.path = "/api/test"

    exc = RuntimeError("something went wrong unexpectedly")
    response = await handler(mock_request, exc)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500

    body = json.loads(response.body)
    assert body == {"detail": "Internal server error"}


# ---------------------------------------------------------------------------
# End-to-end test: handler fires through the full middleware stack
# ---------------------------------------------------------------------------

def test_unhandled_exception_e2e_returns_500_envelope():
    """An unhandled route exception must produce {"detail": "Internal server error"}
    even with PrometheusMiddleware (BaseHTTPMiddleware) outermost in the stack.

    Uses Starlette's synchronous TestClient with raise_server_exceptions=False so
    the handler's JSONResponse is returned rather than the exception being re-raised.
    Verified on Python 3.13 (local) and expected to behave identically on Python 3.12
    (production Docker image), where ServerErrorMiddleware wraps the whole stack and
    routes unhandled exceptions to registered handlers before surfacing them.
    """
    from app.main import app

    # Mount a throwaway route that always raises.  Because the app singleton is
    # already constructed with all middleware in place this exercises the full
    # real stack: ServerErrorMiddleware -> PrometheusMiddleware -> routing.
    _test_router = APIRouter()

    @_test_router.get("/_test_e2e_boom")
    async def _boom():
        raise RuntimeError("deliberate unhandled error for e2e test")

    app.include_router(_test_router)

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/_test_e2e_boom")

        assert resp.status_code == 500, (
            f"Expected 500 from unhandled exception handler, got {resp.status_code}. "
            f"Body: {resp.text}"
        )
        body = resp.json()
        assert body == {"detail": "Internal server error"}, (
            f"Expected error envelope, got: {body}"
        )
    finally:
        # Remove the throwaway route so it does not leak into other tests.
        app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/_test_e2e_boom"]


# ---------------------------------------------------------------------------
# Schema unit test
# ---------------------------------------------------------------------------

def test_error_envelope_schema():
    """ErrorEnvelope must serialize to the expected dict shape."""
    from app.schemas.error import ErrorEnvelope

    env = ErrorEnvelope(detail="Internal server error")
    assert env.model_dump() == {"detail": "Internal server error"}
