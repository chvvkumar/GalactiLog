import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.models import Target


@pytest.mark.asyncio
async def test_search_targets():
    mock_target = MagicMock(spec=Target)
    mock_target.id = uuid.uuid4()
    mock_target.primary_name = "M 31"
    mock_target.object_type = "Galaxy"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_target]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/targets/search?q=M31")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["primary_name"] == "M 31"

    app.dependency_overrides.clear()
