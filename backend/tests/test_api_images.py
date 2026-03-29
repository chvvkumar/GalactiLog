import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def mock_session():
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_list_images_empty():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 0

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

    async def mock_get_session():
        yield mock_session

    app.dependency_overrides[_get_session_dep()] = mock_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/images")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0

    app.dependency_overrides.clear()


def _get_session_dep():
    from app.database import get_session
    return get_session
