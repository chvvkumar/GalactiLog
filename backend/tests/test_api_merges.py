"""API tests for merge endpoints after the service extraction (ARCH-1/ARCH-7).

Exercises representative merge endpoints via dependency overrides for the DB
session and admin auth, asserting response shapes/status codes are preserved.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin, get_current_user
from app.models.target import Target


def _make_target(name="M 31", aliases=None, merged_into_id=None):
    t = MagicMock(spec=Target)
    t.id = uuid.uuid4()
    t.primary_name = name
    t.object_type = "Galaxy"
    t.constellation = "And"
    t.aliases = aliases or []
    t.merged_into_id = merged_into_id
    t.merged_at = None
    return t


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_merge_winner_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(uuid.uuid4()), "loser_id": str(uuid.uuid4())},
            )
        assert resp.status_code == 404
        assert "Winner" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_missing_loser_returns_400(admin_user):
    winner = _make_target()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(winner.id)},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_by_loser_name_returns_status_ok(admin_user):
    winner = _make_target(aliases=["NGC 224"])
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)
    mock_session.execute = AsyncMock(return_value=MagicMock())
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/targets/merge",
                json={"winner_id": str(winner.id), "loser_name": "Andromeda"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
        # The unresolved name should have been appended as an alias.
        assert "Andromeda" in winner.aliases
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unmerge_not_merged_returns_400(admin_user):
    loser = _make_target(merged_into_id=None)
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=loser)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/targets/{loser.id}/unmerge")
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unmerge_target_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/targets/{uuid.uuid4()}/unmerge")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_candidate_count_returns_count(viewer_user):
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 7
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/targets/merge-candidates/count")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"count": 7}
    finally:
        app.dependency_overrides.clear()
