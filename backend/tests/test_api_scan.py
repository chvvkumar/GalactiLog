import uuid
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def _mock_async_redis(mock_redis):
    """Create an async context manager mock that yields the given mock_redis."""
    @asynccontextmanager
    async def _ctx():
        yield mock_redis
    return _ctx


@pytest.mark.asyncio
async def test_trigger_scan_accepted():
    """POST /api/scan persists include_calibration and returns accepted status."""
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None  # no existing row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=settings_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    async def override():
        yield mock_session

    admin = _admin_user()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin

    with patch("app.api.scan.run_scan") as mock_run_scan, \
         patch("app.api.scan.async_redis") as mock_redis_cm:
        mock_run_scan.delay = MagicMock()
        # Mock Redis returning idle state
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock()
        mock_redis.persist = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # lock acquired
        mock_redis.delete = AsyncMock()
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    mock_session.commit.assert_called_once()

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scan_status_idle():
    admin = _admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        with patch("app.api.scan.async_redis") as mock_redis_cm:
            mock_redis = AsyncMock()
            mock_redis.hgetall = AsyncMock(return_value={})
            mock_redis.get = AsyncMock(return_value=None)  # no stale-scan progress key
            mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/scan/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "idle"
        assert data["total"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scan_status_ingesting():
    admin = _admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        with patch("app.api.scan.async_redis") as mock_redis_cm:
            import time as _time
            mock_redis = AsyncMock()
            mock_redis.hgetall = AsyncMock(return_value={
                "state": "ingesting",
                "total": "100",
                "completed": "42",
                "failed": "3",
                "started_at": str(_time.time()),
                "completed_at": "",
            })
            mock_redis.get = AsyncMock(return_value=str(_time.time()))  # recent progress
            mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/scan/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "ingesting"
        assert data["total"] == 100
        assert data["completed"] == 42
        assert data["failed"] == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scan_rejects_when_already_running():
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = None  # no existing row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=settings_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    async def override():
        yield mock_session

    admin = _admin_user()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin

    with patch("app.api.scan.async_redis") as mock_redis_cm:
        import time as _time
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "ingesting",
            "total": "50",
            "completed": "10",
            "failed": "0",
            "started_at": str(_time.time()),
            "completed_at": "",
        })
        mock_redis.get = AsyncMock(return_value=str(_time.time()))  # recent progress
        mock_redis.set = AsyncMock(return_value=True)  # lock acquired
        mock_redis.delete = AsyncMock()
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_old_scan_activity_routes_removed():
    from app.main import app as _app
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/api/scan/activity")
        r2 = await c.delete("/api/scan/activity")
    assert r1.status_code == 404
    assert r2.status_code == 404
