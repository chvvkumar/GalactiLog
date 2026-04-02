"""Tests for timeline granularity in /stats endpoint."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User


def _make_admin_user():
    from app.models.user import UserRole
    user = MagicMock(spec=User)
    user.id = __import__("uuid").uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    return user


def _make_mock_session_for_stats():
    """Build a mock session that returns plausible empty results for all get_stats queries."""
    session = AsyncMock()

    def _empty_result():
        r = MagicMock()
        r.one.return_value = (0, 0, 0)
        r.all.return_value = []
        r.first.return_value = None
        r.scalar_one.return_value = 0
        r.scalar_one_or_none.return_value = None
        return r

    # Overview returns (total_seconds, target_count, total_frames)
    overview_result = MagicMock()
    overview_result.one.return_value = (0, 0, 0)

    # All subsequent queries return empty
    def _side_effect(*args, **kwargs):
        r = MagicMock()
        r.one.return_value = (0, 0, 0)
        r.all.return_value = []
        r.first.return_value = None
        r.scalar_one.return_value = 0
        r.scalar_one_or_none.return_value = None
        return r

    session.execute = AsyncMock(side_effect=lambda *a, **kw: _side_effect())
    return session


@pytest.mark.asyncio
async def test_stats_has_timeline_fields():
    """Verify /stats returns all three timeline granularities and site_coords."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")

        assert resp.status_code == 200
        data = resp.json()

        assert "timeline" in data
        assert isinstance(data["timeline"], list)

        assert "timeline_monthly" in data
        assert "timeline_weekly" in data
        assert "timeline_daily" in data
        assert "site_coords" in data

        assert isinstance(data["timeline_monthly"], list)
        assert isinstance(data["timeline_weekly"], list)
        assert isinstance(data["timeline_daily"], list)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_timeline_detail_entry_shape():
    """Verify TimelineDetailEntry has period, integration_seconds, efficiency_pct."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats")

        data = resp.json()

        for key in ("timeline_monthly", "timeline_weekly", "timeline_daily"):
            for entry in data[key]:
                assert "period" in entry
                assert "integration_seconds" in entry
                assert "efficiency_pct" in entry
    finally:
        app.dependency_overrides.clear()
