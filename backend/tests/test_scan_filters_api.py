"""API tests for /scan/filters endpoints.

The conftest does not provide an authenticated http client fixture, so each
test constructs an AsyncClient + ASGITransport and overrides auth/session
dependencies inline, following the pattern used in test_api_backup.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole


@pytest.fixture
def admin_user():
    user = MagicMock(spec=User)
    user.id = "00000000-0000-0000-0000-000000000001"
    user.username = "admin"
    user.role = UserRole.admin
    return user


def _override_admin(session_mock, admin_user):
    async def override_session():
        yield session_mock
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user


def _scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _make_session(settings_row=None):
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one_or_none(settings_row))
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_get_filters_unconfigured_by_default(admin_user):
    session = _make_session(settings_row=None)
    _override_admin(session, admin_user)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/scan/filters")
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is False
        assert body["filters"]["include_paths"] == []
        assert body["filters"]["exclude_paths"] == []
        assert body["filters"]["name_rules"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_filters_sets_configured(admin_user):
    session = _make_session(settings_row=None)
    _override_admin(session, admin_user)
    try:
        payload = {
            "include_paths": [],
            "exclude_paths": [],
            "name_rules": [{
                "id": "r1", "action": "exclude", "type": "glob",
                "pattern": "*_bad.fits", "target": "file", "enabled": True,
            }],
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put("/api/scan/filters", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert len(body["filters"]["name_rules"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_filters_rejects_invalid_regex(admin_user):
    session = _make_session(settings_row=None)
    _override_admin(session, admin_user)
    try:
        payload = {
            "include_paths": [], "exclude_paths": [],
            "name_rules": [{
                "id": "r1", "action": "exclude", "type": "regex",
                "pattern": "[unclosed", "target": "file", "enabled": True,
            }],
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put("/api/scan/filters", json=payload)
        assert r.status_code == 400
        assert "invalid regex" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_filters_rejects_path_outside_root(admin_user):
    session = _make_session(settings_row=None)
    _override_admin(session, admin_user)
    try:
        payload = {
            "include_paths": ["/etc"],
            "exclude_paths": [],
            "name_rules": [],
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put("/api/scan/filters", json=payload)
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_filters_requires_admin():
    """Without overriding require_admin, the endpoint must reject."""
    # Clear any lingering overrides
    app.dependency_overrides.clear()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put("/api/scan/filters", json={
                "include_paths": [], "exclude_paths": [], "name_rules": [],
            })
        assert r.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_test_path_endpoint(admin_user):
    # Pre-populate the session with an existing scan_filters row so the
    # endpoint can load them directly (avoids relying on PUT persistence).
    existing_row = MagicMock()
    existing_row.general = {
        "scan_filters": {
            "include_paths": [],
            "exclude_paths": [],
            "name_rules": [{
                "id": "e1", "action": "exclude", "type": "glob",
                "pattern": "*_bad.fits", "target": "file", "enabled": True,
            }],
        },
        "scan_filters_configured": True,
    }
    session = _make_session(settings_row=existing_row)
    _override_admin(session, admin_user)
    try:
        # Use a path under the configured fits_data_path (/tmp/test_fits per conftest)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/scan/filters/test",
                json={"path": "/tmp/test_fits/frame_bad.fits"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["verdict"] == "excluded_by_rule"
        assert "e1" in body["matched_rule_ids"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_apply_now_dry_run(admin_user):
    # First execute returns the settings row (None), subsequent call returns
    # paths_result iterable with .all() returning an empty list.
    empty_rows = MagicMock()
    empty_rows.all = MagicMock(return_value=[])
    settings_result = _scalar_one_or_none(None)

    session = AsyncMock()
    # Sequence: 1) settings lookup, 2) Image paths select
    session.execute = AsyncMock(side_effect=[settings_result, empty_rows])
    session.commit = AsyncMock()

    _override_admin(session, admin_user)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/scan/filters/apply-now?dry_run=true")
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert body["matched"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_browse_rejects_escape(admin_user):
    session = _make_session(settings_row=None)
    _override_admin(session, admin_user)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/scan/browse", params={"path": "/etc"})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()
