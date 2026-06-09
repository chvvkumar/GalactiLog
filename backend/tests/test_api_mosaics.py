"""API tests for mosaic endpoints after the service extraction (ARCH-1/ARCH-7).

These exercise representative endpoints via dependency overrides for the DB
session and auth, asserting response shapes are unchanged by the refactor.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_list_mosaics_empty_returns_200(viewer_user):
    """list_mosaics delegates to the service; empty DB yields an empty list."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_mosaic_returns_summary_shape(admin_user):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "Veil Mosaic"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Veil Mosaic"
        assert data["panel_count"] == 0
        assert data["total_integration_seconds"] == 0
        assert data["total_frames"] == 0
        assert data["completion_pct"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_mosaic_detail_not_found_returns_404(viewer_user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/mosaics/{uuid.uuid4()}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_mosaic_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{uuid.uuid4()}", json={"name": "Renamed"}
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_mosaic_returns_status_ok(admin_user):
    mosaic = MagicMock()
    mosaic.name = "Old"
    mosaic.notes = None
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mosaic)
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{uuid.uuid4()}", json={"name": "New name"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_add_panel_mosaic_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/mosaics/{uuid.uuid4()}/panels",
                json={"target_id": str(uuid.uuid4()), "panel_label": "Panel 1"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
