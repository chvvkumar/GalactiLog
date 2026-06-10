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
async def test_custom_create_success(admin_user):
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
        # Normalized uppercase forms of the primary name and aliases must be
        # stored so the scanner links OBJECT=JUPITER / OBJECT=JOVE / OBJECT=Jove.
        assert "JUPITER" in added.aliases
        assert "Jove" in added.aliases
        assert "JOVE" in added.aliases
        # The literal primary string itself is not stored as an alias.
        assert "Jupiter" not in added.aliases
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_mixed_case_alias_conflict_409(admin_user):
    """A new name colliding with an existing mixed-case alias must 409.

    The conflict check is case-insensitive, so the EXISTS/unnest subquery is
    what surfaces the collision; this test guards against a regression to the
    exact-match aliases.any() form.
    """
    mock_session = AsyncMock()
    conflict = MagicMock(spec=Target)
    conflict.primary_name = "Some Galaxy"
    found = MagicMock()
    found.scalars.return_value.first.return_value = conflict
    mock_session.execute = AsyncMock(return_value=found)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/custom", json={"primary_name": "jupiter"})
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_out_of_range_coords_422(admin_user):
    _override_session(_no_conflict_session())
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp_ra = await client.post("/api/targets/custom", json={"primary_name": "X", "ra": 400})
            resp_dec = await client.post("/api/targets/custom", json={"primary_name": "X", "dec": -120})
        assert resp_ra.status_code == 422
        assert resp_dec.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_custom_create_integrity_error_maps_to_409(admin_user):
    """A unique-constraint violation on commit returns 409, not 500."""
    from sqlalchemy.exc import IntegrityError

    mock_session = _no_conflict_session()
    mock_session.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
    mock_session.rollback = AsyncMock()
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/custom", json={"primary_name": "Jupiter"})
        assert resp.status_code == 409
        mock_session.rollback.assert_awaited()
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


@pytest.mark.asyncio
async def test_orphan_create_stores_stripped_name_and_normalized_aliases(admin_user, monkeypatch):
    """orphan_create persists the stripped primary name and normalized aliases."""
    candidate = MagicMock(spec=MergeCandidate)
    candidate.status = "pending"
    candidate.source_name = "jupiter"

    mock_session = _no_conflict_session()
    mock_session.get = AsyncMock(return_value=candidate)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    monkeypatch.setattr("app.api.merges._enrich_new_target", lambda target_id: None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/orphan-create", json={
                "candidate_id": str(uuid.uuid4()),
                "primary_name": "  Jupiter  ",
                "user_defined": True,
                "aliases": ["Jove"],
            })
        assert resp.status_code == 200, resp.text
        added = mock_session.add.call_args[0][0]
        assert added.primary_name == "Jupiter"  # stripped, not "  Jupiter  "
        assert "JUPITER" in added.aliases  # normalized primary
        assert "JOVE" in added.aliases  # normalized alias
        assert "jupiter" in added.aliases  # candidate source name as-typed
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_orphan_create_blank_name_422(admin_user):
    candidate = MagicMock(spec=MergeCandidate)
    candidate.status = "pending"
    candidate.source_name = "x"
    mock_session = _no_conflict_session()
    mock_session.get = AsyncMock(return_value=candidate)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/orphan-create", json={
                "candidate_id": str(uuid.uuid4()),
                "primary_name": "   ",
            })
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_orphan_create_name_conflict_409(admin_user):
    """Creating from an orphan whose name matches an existing target must 409
    and point the user at the merge flow, not crash with a unique violation.

    Regression: orphan-create on a "Moon" candidate 500ed against an existing
    custom Moon target because it had no conflict pre-check.
    """
    candidate = MagicMock(spec=MergeCandidate)
    candidate.status = "pending"
    candidate.source_name = "Moon"

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=candidate)
    conflict = MagicMock(spec=Target)
    conflict.primary_name = "Moon"
    found = MagicMock()
    found.scalars.return_value.first.return_value = conflict
    mock_session.execute = AsyncMock(return_value=found)
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/orphan-create", json={
                "candidate_id": str(uuid.uuid4()),
                "primary_name": "Moon",
            })
        assert resp.status_code == 409
        assert "Merge into Existing" in resp.json()["detail"]
        mock_session.add.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_orphan_create_integrity_error_maps_to_409(admin_user):
    """A unique-constraint violation on commit returns 409, not 500."""
    from sqlalchemy.exc import IntegrityError

    candidate = MagicMock(spec=MergeCandidate)
    candidate.status = "pending"
    candidate.source_name = "Moon"

    mock_session = _no_conflict_session()
    mock_session.get = AsyncMock(return_value=candidate)
    mock_session.commit = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("dup")))
    mock_session.rollback = AsyncMock()
    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/orphan-create", json={
                "candidate_id": str(uuid.uuid4()),
                "primary_name": "Moon",
            })
        assert resp.status_code == 409
        mock_session.rollback.assert_awaited()
    finally:
        app.dependency_overrides.clear()
