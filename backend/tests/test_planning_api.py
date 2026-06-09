"""Tests for the GET /api/planning/night endpoint.

These tests use dependency overrides on the FastAPI app so no real
Postgres connection is required. The ephemeris computation is patched out.
"""
import pytest
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.deps import get_current_user


@pytest.mark.asyncio
async def test_planning_night_requires_auth():
    """Endpoint returns 401 when no access_token cookie is present."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/planning/night?date=2026-06-09")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_planning_night_authenticated_proceeds(viewer_user):
    """Authenticated request reaches the handler and returns ephemeris data."""
    app.dependency_overrides[get_current_user] = lambda: viewer_user

    class _Coords:
        latitude = 40.0
        longitude = -105.0

    class _FakeSessionCtx:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return False

    try:
        mock_ephemeris = {
            "date": "2026-06-09",
            "astro_dusk": None,
            "astro_dawn": None,
            "moon_phase": None,
            "moon_illumination": None,
            "moon_rise": None,
            "moon_set": None,
            "source_available": False,
        }
        with patch(
            "app.api.planning.async_session",
            return_value=_FakeSessionCtx(),
        ), patch(
            "app.api.planning._extract_site_coords",
            new=AsyncMock(return_value=_Coords()),
        ), patch(
            "app.api.planning.get_night_ephemeris",
            return_value=mock_ephemeris,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/planning/night?date=2026-06-09")
        assert resp.status_code == 200
        assert resp.json()["date"] == "2026-06-09"
        assert resp.json()["source_available"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
