"""Tests for the WBPP export router."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from datetime import date

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole


def _admin():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4(); u.role = UserRole.admin; u.is_active = True
    return u


@pytest.mark.asyncio
async def test_wbpp_preview_empty_sessions():
    mock_session = AsyncMock()
    mock_result = MagicMock(); mock_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/wbpp/preview", json={
                "target_id": str(uuid.uuid4()),
                "session_dates": ["2024-01-01"],
                "library_root": "/mnt/astro",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["total_frame_count"] == 0
        assert data["target_os"] == "posix"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_generate_returns_ps1_for_windows_root():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [
        ("/app/data/fits/M31/2024-01-01/Light/frame.fits", date(2024, 1, 1), "M 31"),
    ]
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/wbpp/generate", json={
                "target_id": str(uuid.uuid4()),
                "target_name": "M 31",
                "session_dates": ["2024-01-01"],
                "library_root": "Z:\\Astro",
            })
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd and ".ps1" in cd
        assert "Copy-Item" in resp.text
    finally:
        app.dependency_overrides.clear()
