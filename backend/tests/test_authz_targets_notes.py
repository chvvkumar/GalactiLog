"""Authorization tests for targets notes write endpoints (SEC-2).

Viewer role must be read-only: note-update endpoints require admin.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user


def _override_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_update_target_notes_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/targets/{uuid.uuid4()}/notes", json={"notes": "hello"}
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_target_notes_admin_allowed(admin_user):
    from app.models import Target

    target = MagicMock(spec=Target)
    target.id = uuid.uuid4()
    target.notes = None

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/targets/{target.id}/notes", json={"notes": "observed"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"
        assert target.notes == "observed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_session_notes_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/targets/{uuid.uuid4()}/sessions/2026-01-01/notes",
                json={"notes": "clear skies"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_session_notes_admin_allowed(admin_user):
    target_id = uuid.uuid4()

    # No existing session note -> endpoint inserts a new SessionNote.
    note_result = MagicMock()
    note_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=note_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/targets/{target_id}/sessions/2026-01-01/notes",
                json={"notes": "clear skies"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"
        mock_session.add.assert_called_once()
    finally:
        app.dependency_overrides.clear()
