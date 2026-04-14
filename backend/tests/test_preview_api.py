"""Tests for the GET /api/preview/{image_id} endpoint.

These tests use dependency overrides on the FastAPI app so no real
Postgres or Redis connection is required.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session


@pytest.mark.asyncio
async def test_preview_endpoint_404_for_missing_image():
    """Endpoint returns 404 when no Image row exists for the given UUID."""

    async def _fake_session():
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result
        yield session

    app.dependency_overrides[get_session] = _fake_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/preview/{uuid.uuid4()}?resolution=400")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Image not found"
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_preview_endpoint_404_for_missing_file(tmp_path):
    """Endpoint returns 404 when the Image row exists but file_path is not on disk."""
    nonexistent = tmp_path / "does_not_exist.fits"

    fake_image = MagicMock()
    fake_image.file_path = str(nonexistent)

    call_count = 0

    async def _fake_session():
        nonlocal call_count
        session = AsyncMock()

        def _execute_side_effect(*args, **kwargs):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = fake_image
            else:
                result.scalar_one_or_none.return_value = None
            call_count += 1
            return result

        session.execute = AsyncMock(side_effect=_execute_side_effect)
        yield session

    app.dependency_overrides[get_session] = _fake_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/preview/{uuid.uuid4()}?resolution=400")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "File not found on disk"
    finally:
        app.dependency_overrides.pop(get_session, None)
