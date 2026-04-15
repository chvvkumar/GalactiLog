import os, sys, uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole


def _user(role=UserRole.admin):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "admin"
    u.role = role
    u.is_active = True
    return u


def _session_with_events(events, total):
    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    scalars_result = MagicMock()
    scalars_result.all.return_value = events
    call_count = [0]

    async def _execute(stmt, *a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return count_result
        r = MagicMock()
        r.scalars.return_value = scalars_result
        return r

    mock_session.execute = _execute

    async def _gen():
        yield mock_session

    return _gen


@pytest.mark.asyncio
async def test_get_activity_returns_200():
    from app.models.activity_event import ActivityEvent
    ev = ActivityEvent(id=1, severity="info", category="scan",
                       event_type="scan_complete", message="done",
                       details=None, target_id=None, actor="system", duration_ms=None)
    ev.timestamp = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    app.dependency_overrides[get_session] = _session_with_events([ev], 1)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "next_cursor" in data


@pytest.mark.asyncio
async def test_get_activity_severity_filter():
    app.dependency_overrides[get_session] = _session_with_events([], 0)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity?severity=error")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_activity_since_filter():
    app.dependency_overrides[get_session] = _session_with_events([], 0)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity?since=2026-04-15T12:00:00Z")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_activity_requires_admin():
    from fastapi import HTTPException
    async def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")
    app.dependency_overrides[require_admin] = _deny
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_activity_clears_all():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen
    app.dependency_overrides[require_admin] = lambda: _user()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"
