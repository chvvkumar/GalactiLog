import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session


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

    app.dependency_overrides[get_session] = override

    with patch("app.api.scan.run_scan") as mock_run_scan, \
         patch("app.api.scan.get_async_redis") as mock_redis_factory:
        mock_run_scan.delay = MagicMock()
        # Mock Redis returning idle state
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock()
        mock_redis.persist = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.aclose = AsyncMock()
        mock_redis_factory.return_value = mock_redis

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
    with patch("app.api.scan.get_async_redis") as mock_redis_factory:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.aclose = AsyncMock()
        mock_redis_factory.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/scan/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "idle"
    assert data["total"] == 0
    assert data["completed"] == 0
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_scan_status_ingesting():
    with patch("app.api.scan.get_async_redis") as mock_redis_factory:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "ingesting",
            "total": "100",
            "completed": "42",
            "failed": "3",
            "started_at": "1711000000.0",
            "completed_at": "",
        })
        mock_redis.aclose = AsyncMock()
        mock_redis_factory.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/scan/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "ingesting"
    assert data["total"] == 100
    assert data["completed"] == 42
    assert data["failed"] == 3


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

    app.dependency_overrides[get_session] = override

    with patch("app.api.scan.get_async_redis") as mock_redis_factory:
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "ingesting",
            "total": "50",
            "completed": "10",
            "failed": "0",
            "started_at": "1711000000.0",
            "completed_at": "",
        })
        mock_redis.aclose = AsyncMock()
        mock_redis_factory.return_value = mock_redis

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"

    app.dependency_overrides.clear()
