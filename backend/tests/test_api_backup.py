import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_session
from app.api.deps import require_admin
from app.models.user import User, UserRole
from app.services.backup import CURRENT_BACKUP_SCHEMA_VERSION, APP_VERSION


@pytest.fixture
def admin_user():
    user = MagicMock(spec=User)
    user.id = "00000000-0000-0000-0000-000000000001"
    user.username = "admin"
    user.role = UserRole.admin
    return user


@pytest.fixture
def mock_session():
    return AsyncMock()


def _override_deps(mock_session, admin_user):
    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin_user


@pytest.mark.asyncio
async def test_create_backup(mock_session, admin_user):
    """POST /api/backup/create returns a downloadable JSON file."""
    _override_deps(mock_session, admin_user)

    fake_export = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": "2026-04-09T00:00:00+00:00",
        },
        "settings": {},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    try:
        with patch("app.api.backup.export_backup", return_value=fake_export):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/backup/create")

        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert resp.headers["content-type"] == "application/json"
        body = resp.json()
        assert body["meta"]["schema_version"] == CURRENT_BACKUP_SCHEMA_VERSION
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validate_backup(mock_session, admin_user):
    """POST /api/backup/validate returns validation preview."""
    _override_deps(mock_session, admin_user)

    backup_data = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": "2026-04-09T00:00:00+00:00",
        },
        "settings": {"general": {}},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/backup/validate",
                files={"file": ("backup.json", json.dumps(backup_data).encode(), "application/json")},
                data={"mode": "merge"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validate_rejects_invalid_json(mock_session, admin_user):
    """POST /api/backup/validate rejects non-JSON files."""
    _override_deps(mock_session, admin_user)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/backup/validate",
                files={"file": ("backup.json", b"not json", "application/json")},
                data={"mode": "merge"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restore_happy_path(mock_session, admin_user):
    """POST /api/backup/restore commits on success."""
    _override_deps(mock_session, admin_user)

    backup_data = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": "2026-04-09T00:00:00+00:00",
        },
        "settings": {"general": {}},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    fake_result = {
        "success": True,
        "applied": {"settings": {"add": 0, "update": 1, "skip": 0, "unchanged": 0}},
        "temporary_passwords": {},
        "warnings": [],
    }

    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    try:
        with patch("app.api.backup.restore_backup", return_value=fake_result):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/backup/restore",
                    files={"file": ("backup.json", json.dumps(backup_data).encode(), "application/json")},
                    data={"mode": "merge"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restore_rolls_back_on_exception(mock_session, admin_user):
    """POST /api/backup/restore rolls back and returns error on exception."""
    _override_deps(mock_session, admin_user)

    backup_data = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": "2026-04-09T00:00:00+00:00",
        },
        "settings": {"general": {}},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    try:
        with patch("app.api.backup.restore_backup", side_effect=boom):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/backup/restore",
                    files={"file": ("backup.json", json.dumps(backup_data).encode(), "application/json")},
                    data={"mode": "merge"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "failed" in body["error"].lower()
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restore_rejects_invalid_backup(mock_session, admin_user):
    """POST /api/backup/restore rejects backup that fails validation."""
    _override_deps(mock_session, admin_user)

    # Backup from a future schema version
    backup_data = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION + 99,
            "app_version": "99.0.0",
            "exported_at": "2099-01-01T00:00:00+00:00",
        },
        "settings": {},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/backup/restore",
                files={"file": ("backup.json", json.dumps(backup_data).encode(), "application/json")},
                data={"mode": "merge"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] is not None
        mock_session.commit.assert_not_called()
    finally:
        app.dependency_overrides.clear()
