"""Authorization tests for mosaics write endpoints (SEC-2).

Viewer role must be read-only: state-changing mosaic endpoints require admin.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user


def _override_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_create_mosaic_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "M31 Mosaic"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_mosaic_admin_allowed(admin_user):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "M31 Mosaic"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "M31 Mosaic"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_mosaic_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/mosaics/{uuid.uuid4()}")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_detection_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics/detect")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_clear_reviews_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics/clear-reviews")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
