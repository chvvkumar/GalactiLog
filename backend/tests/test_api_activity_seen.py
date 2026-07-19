import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole


def _user(role=UserRole.viewer):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "viewer"
    u.role = role
    u.is_active = True
    u.activity_seen_at = None
    return u


def _session_gen(mock_session):
    async def _gen():
        yield mock_session
    return _gen


def test_user_model_has_nullable_activity_seen_at():
    assert "activity_seen_at" in User.__table__.columns
    col = User.__table__.columns["activity_seen_at"]
    assert col.nullable is True


@pytest.mark.asyncio
async def test_mark_activity_seen_sets_timestamp_and_commits():
    user = _user()
    mock_session = AsyncMock()
    app.dependency_overrides[get_session] = _session_gen(mock_session)
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/activity/seen")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    returned = datetime.fromisoformat(resp.json()["activity_seen_at"])
    assert returned.tzinfo is not None
    assert user.activity_seen_at == returned
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_activity_seen_allowed_for_viewer_role():
    user = _user(UserRole.viewer)
    mock_session = AsyncMock()
    app.dependency_overrides[get_session] = _session_gen(mock_session)
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/activity/seen")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mark_activity_seen_requires_auth():
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/activity/seen")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_includes_activity_seen_at():
    user = _user()
    user.activity_seen_at = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/auth/me")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert datetime.fromisoformat(resp.json()["activity_seen_at"]) == user.activity_seen_at


@pytest.mark.asyncio
async def test_me_activity_seen_at_null_when_never_marked():
    user = _user()
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/auth/me")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["activity_seen_at"] is None
