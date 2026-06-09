import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models.user_settings import SETTINGS_ROW_ID


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def _make_settings_row(general=None, filters=None, equipment=None, dismissed_suggestions=None, display=None, graph=None):
    row = MagicMock()
    row.id = SETTINGS_ROW_ID
    row.general = general if general is not None else {}
    row.filters = filters if filters is not None else {}
    row.equipment = equipment if equipment is not None else {}
    row.dismissed_suggestions = dismissed_suggestions if dismissed_suggestions is not None else []
    row.display = display if display is not None else {}
    row.graph = graph if graph is not None else {}
    return row


@pytest.mark.asyncio
async def test_get_settings_includes_graph_defaults():
    row = _make_settings_row()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    admin = _admin_user()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "graph" in data
        assert data["graph"]["enabled_metrics"] == ["hfr", "eccentricity", "fwhm", "guiding_rms"]
        assert data["graph"]["enabled_filters"] == ["overall"]
        assert data["graph"]["session_chart_expanded"] is False
        assert data["graph"]["target_chart_expanded"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_graph_settings():
    row = _make_settings_row()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def override():
        yield mock_session

    admin = _admin_user()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "enabled_metrics": ["hfr", "fwhm"],
                "enabled_filters": ["overall", "Ha"],
                "session_chart_expanded": True,
                "target_chart_expanded": False,
            }
            resp = await client.put("/api/settings/graph", json=payload)
        assert resp.status_code == 200
        # Verify the fields from the payload were persisted; row.graph may
        # include additional fields with defaults (e.g. default_chart_sessions).
        assert row.graph["enabled_metrics"] == payload["enabled_metrics"]
        assert row.graph["enabled_filters"] == payload["enabled_filters"]
        assert row.graph["session_chart_expanded"] == payload["session_chart_expanded"]
        assert row.graph["target_chart_expanded"] == payload["target_chart_expanded"]
    finally:
        app.dependency_overrides.clear()
