import os
import sys
import uuid
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
from app.api.deps import get_current_user, require_admin  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.models.user_settings import SETTINGS_ROW_ID  # noqa: E402


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "admin"
    u.role = UserRole.admin
    u.is_active = True
    return u


def _settings_row(general=None):
    row = MagicMock()
    row.id = SETTINGS_ROW_ID
    row.general = general if general is not None else {}
    return row


def _session_returning(row):
    """AsyncMock session whose execute always returns a result with the row."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_get_activity_settings_defaults():
    row = _settings_row({"_migrated": True})
    session = _session_returning(row)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin_user()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/settings/activity")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_retention_days"] == 90
    assert body["app_log_capture_level"] == "warning"
    assert body["app_log_retention_days"] == 14
    assert body["app_log_max_rows"] == 50000


@pytest.mark.asyncio
async def test_put_activity_settings_updates_and_returns_shape():
    # Row mutates in place; the handler writes row.general then reads it back.
    row = _settings_row({"_migrated": True})
    session = _session_returning(row)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    admin = _admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put(
                "/api/settings/activity",
                json={"app_log_capture_level": "debug", "app_log_max_rows": 12000},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["app_log_capture_level"] == "debug"
    assert body["app_log_max_rows"] == 12000


@pytest.mark.asyncio
async def test_put_activity_settings_rejects_bad_capture_level():
    row = _settings_row({"_migrated": True})
    session = _session_returning(row)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    admin = _admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/settings/activity", json={"app_log_capture_level": "bogus"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_activity_settings_legacy_retention_days():
    row = _settings_row({"_migrated": True})
    session = _session_returning(row)

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    admin = _admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.put("/api/settings/activity", json={"retention_days": 30})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["activity_retention_days"] == 30
