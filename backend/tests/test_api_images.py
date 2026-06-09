import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_list_images_empty():
    """GET /api/images returns 404 because no such route exists in the application.

    The /api/images endpoint was removed (or never shipped). This test documents
    that the route is absent so any future re-addition is an explicit decision.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/images")

    assert resp.status_code == 404
