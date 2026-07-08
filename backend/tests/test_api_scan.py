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
        mock_redis.exists = AsyncMock(return_value=0)  # no scan already dispatched
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    mock_session.commit.assert_called_once()
    mock_redis.set.assert_any_call("scan:dispatched", "1", ex=60)

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
            mock_redis.exists = AsyncMock(return_value=0)  # no scan already dispatched
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


@pytest.mark.asyncio
async def test_db_summary_counts_catalog_cache_by_source():
    """db-summary must read live counts from catalog_cache, not the frozen
    per-source tables, and must count negative rows via the `negative` flag."""
    import os
    from sqlalchemy import text as _text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    db_url = os.environ["GALACTILOG_DATABASE_URL"]
    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    mark = "zzdbsummarytest"
    try:
        async with Session() as s:
            try:
                await s.execute(_text("SELECT 1 FROM catalog_cache LIMIT 1"))
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"test DB not reachable: {exc}")
            await s.execute(_text("DELETE FROM catalog_cache WHERE key LIKE :p"), {"p": f"{mark}%"})
            await s.execute(_text("""
                INSERT INTO catalog_cache (source, key, payload, negative)
                VALUES
                    ('simbad', :k1, '{"main_id": "M31"}'::jsonb, false),
                    ('simbad', :k2, NULL, true),
                    ('vizier', :k3, '{"vizier_catalog": "VII/118"}'::jsonb, false),
                    ('vizier', :k4, NULL, true),
                    ('sesame', :k5, '{"main_id": "NGC 224"}'::jsonb, false),
                    ('sesame', :k6, NULL, true)
            """), {
                "k1": f"{mark}_simbad_pos", "k2": f"{mark}_simbad_neg",
                "k3": f"{mark}_vizier_pos", "k4": f"{mark}_vizier_neg",
                "k5": f"{mark}_sesame_pos", "k6": f"{mark}_sesame_neg",
            })
            await s.commit()

            before = (await s.execute(_text("""
                SELECT
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'simbad'),
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'simbad' AND negative),
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'vizier'),
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'vizier' AND negative),
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'sesame'),
                    (SELECT COUNT(*) FROM catalog_cache WHERE source = 'sesame' AND negative)
            """))).one()

        async def override():
            async with Session() as session:
                yield session

        admin = _admin_user()
        app.dependency_overrides[get_session] = override
        app.dependency_overrides[get_current_user] = lambda: admin

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/scan/db-summary")

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Response shape/field names are unchanged.
        assert set(data.keys()) == {
            "total_images", "light_frames", "resolved_targets", "unresolved_images",
            "cached_simbad", "cached_negative", "pending_merges", "csv_enriched",
            "cached_vizier", "cached_vizier_negative", "cached_sesame", "cached_sesame_negative",
        }

        assert data["cached_simbad"] == before[0]
        assert data["cached_negative"] == before[1]
        assert data["cached_vizier"] == before[2]
        assert data["cached_vizier_negative"] == before[3]
        assert data["cached_sesame"] == before[4]
        assert data["cached_sesame_negative"] == before[5]
        assert data["cached_simbad"] >= 2
        assert data["cached_negative"] >= 1
    finally:
        async with Session() as s:
            await s.execute(_text("DELETE FROM catalog_cache WHERE key LIKE :p"), {"p": f"{mark}%"})
            await s.commit()
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_catalog_identity_queues_task():
    admin = _admin_user()
    app.dependency_overrides[require_admin] = lambda: admin

    fake_state = MagicMock()
    fake_state.state = "idle"

    try:
        with patch("app.api.scan.get_scan_state", new=AsyncMock(return_value=fake_state)), \
             patch("app.api.scan.backfill_catalog_identity") as task, \
             patch("app.api.scan.async_redis") as mock_redis_cm:
            task.delay.return_value = MagicMock(id="task-xyz")
            mock_redis = AsyncMock()
            mock_redis_cm.side_effect = _mock_async_redis(mock_redis)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/scan/backfill-catalog-identity")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "accepted"
        task.delay.assert_called_once()
    finally:
        app.dependency_overrides.clear()
