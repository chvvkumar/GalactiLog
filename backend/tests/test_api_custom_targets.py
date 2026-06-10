"""API tests for custom target creation."""
import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin
from app.models.target import Target
from app.models.merge_candidate import MergeCandidate


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


def _no_conflict_session():
    """Session whose scalar lookups find nothing (no name/identity conflicts)."""
    mock_session = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None
    empty.scalars.return_value.all.return_value = []
    empty.rowcount = 0
    mock_session.execute = AsyncMock(return_value=empty)
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()
    return mock_session


@pytest.mark.asyncio
async def test_custom_create_success(admin_user, monkeypatch):
    mock_session = _no_conflict_session()
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/custom", json={
                "primary_name": "Jupiter",
                "object_type": "Planet",
                "user_defined": True,
                "aliases": ["Jove"],
            })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["target_id"]
        # The created target must be flagged and name-locked.
        added = mock_session.add.call_args[0][0]
        assert added.user_defined is True
        assert added.name_locked is True
        assert added.ra is None and added.dec is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_name_conflict_409(admin_user):
    mock_session = AsyncMock()
    conflict = MagicMock(spec=Target)
    conflict.primary_name = "Jupiter"
    found = MagicMock()
    found.scalars.return_value.first.return_value = conflict
    mock_session.execute = AsyncMock(return_value=found)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/custom", json={"primary_name": "Jupiter"})
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_blank_name_422(admin_user):
    _override_session(_no_conflict_session())
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/custom", json={"primary_name": "   "})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_requires_admin():
    # No require_admin override: anonymous request must be rejected.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/targets/custom", json={"primary_name": "Jupiter"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_orphan_create_user_defined_skips_enrichment(admin_user, monkeypatch):
    """Orphan create with user_defined flags the target, locks the name, and
    skips catalog enrichment."""
    candidate = MagicMock(spec=MergeCandidate)
    candidate.status = "pending"
    candidate.source_name = "Jupiter"

    mock_session = _no_conflict_session()
    mock_session.get = AsyncMock(return_value=candidate)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user

    enrich_calls = []
    monkeypatch.setattr(
        "app.api.merges._enrich_new_target",
        lambda target_id: enrich_calls.append(target_id),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/orphan-create", json={
                "candidate_id": str(uuid.uuid4()),
                "primary_name": "Jupiter",
                "object_type": "Planet",
                "user_defined": True,
            })
        assert resp.status_code == 200, resp.text
        added = mock_session.add.call_args[0][0]
        assert added.user_defined is True
        assert added.name_locked is True
        assert enrich_calls == []
    finally:
        app.dependency_overrides.clear()
