import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.main import app  # noqa: E402
from app.database import get_session  # noqa: E402
from app.api.deps import require_admin  # noqa: E402
from app.api.logs import _encode_cursor, _decode_cursor  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


def _admin():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "admin"
    u.role = UserRole.admin
    u.is_active = True
    return u


def _make_logs(n=5):
    from app.models.app_log import AppLog
    base = datetime(2026, 6, 11, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        r = AppLog(
            level="warning" if i % 2 else "error",
            source="api",
            logger="app.x",
            message=f"msg{i}",
            traceback="Traceback (most recent call last)..." if i == 0 else None,
        )
        r.id = n - i  # newest first => highest id first
        r.timestamp = base - timedelta(minutes=i)
        rows.append(r)
    return rows


def _list_session(rows, total):
    """AsyncMock session: first execute -> count, second -> items scalars."""
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    scalars_result = MagicMock()
    scalars_result.all.return_value = rows
    call = [0]

    async def _execute(stmt, *a, **kw):
        call[0] += 1
        if call[0] == 1:
            return count_result
        r = MagicMock()
        r.scalars.return_value = scalars_result
        return r

    session = AsyncMock()
    session.execute = _execute
    return session


def _download_session(rows):
    scalars_result = MagicMock()
    scalars_result.all.return_value = rows

    async def _execute(stmt, *a, **kw):
        r = MagicMock()
        r.scalars.return_value = scalars_result
        return r

    session = AsyncMock()
    session.execute = _execute
    return session


@pytest.mark.asyncio
async def test_list_logs_admin():
    rows = _make_logs(5)
    session = _list_session(rows, total=5)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/logs?limit=10")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["items"][0]["message"] == "msg0"  # newest first
    assert body["items"][0]["traceback"] is not None
    assert body["next_cursor"] is None  # fewer rows than limit


@pytest.mark.asyncio
async def test_list_logs_next_cursor_when_full_page():
    rows = _make_logs(2)
    session = _list_session(rows, total=10)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/logs?limit=2")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["next_cursor"] is not None


@pytest.mark.asyncio
async def test_clear_requires_admin():
    from fastapi import HTTPException

    async def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")

    app.dependency_overrides[require_admin] = _deny
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/logs")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_clear_logs_admin():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/api/logs")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"


@pytest.mark.asyncio
async def test_download_returns_text():
    rows = _make_logs(5)
    session = _download_session(rows)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/logs/download")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "msg0" in resp.text
    assert "[ERROR]" in resp.text
    assert resp.headers["content-disposition"].endswith("galactilog-app.log")


def test_cursor_round_trip():
    ts = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
    cur = _encode_cursor(ts, 42)
    decoded = _decode_cursor(cur)
    assert decoded is not None
    dts, did = decoded
    assert did == 42
    assert dts == ts


def test_cursor_decode_garbage():
    assert _decode_cursor("not-a-cursor!!!") is None
