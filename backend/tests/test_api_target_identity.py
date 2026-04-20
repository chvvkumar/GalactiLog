import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin
from app.models.target import Target
from app.models.user import User, UserRole


def _make_admin():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    return user


def _make_target(name="NGC 7000", object_type="HII", catalog_id="NGC 7000", common_name="North America Nebula", aliases=None, name_locked=False):
    t = MagicMock(spec=Target)
    t.id = uuid.uuid4()
    t.primary_name = name
    t.object_type = object_type
    t.catalog_id = catalog_id
    t.common_name = common_name
    t.aliases = aliases or []
    t.merged_into_id = None
    t.name_locked = name_locked
    return t


@pytest.mark.asyncio
async def test_rename_sets_name_locked():
    target = _make_target(name="NGC 7000", name_locked=False)
    admin = _make_admin()

    # After commit+refresh the target reflects the updated values
    updated_target = MagicMock(spec=Target)
    updated_target.id = target.id
    updated_target.primary_name = "My Custom Name"
    updated_target.object_type = target.object_type
    updated_target.catalog_id = target.catalog_id
    updated_target.common_name = target.common_name
    updated_target.merged_into_id = None
    updated_target.name_locked = True

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda t: None)

    # After refresh, the target object should reflect updated state
    # We simulate by having the target mutated during the endpoint call
    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                f"/api/targets/{target.id}/identity",
                json={"primary_name": "My Custom Name"},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["primary_name"] == "My Custom Name"
        assert data["name_locked"] is True

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rename_with_object_type_maps_category():
    target = _make_target(name="NGC 7000", object_type="HII", name_locked=False)
    admin = _make_admin()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda t: None)

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                f"/api/targets/{target.id}/identity",
                json={"object_type": "Galaxy"},
            )

        assert resp.status_code == 200, resp.text
        # The endpoint should have set target.object_type to "G"
        assert target.object_type == "G"

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_identity_endpoint_returns_404_for_missing_target():
    admin = _make_admin()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                f"/api/targets/{uuid.uuid4()}/identity",
                json={"primary_name": "Whatever"},
            )

        assert resp.status_code == 404

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_identity_endpoint_returns_404_for_merged_target():
    target = _make_target()
    target.merged_into_id = uuid.uuid4()  # target is merged
    admin = _make_admin()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                f"/api/targets/{target.id}/identity",
                json={"primary_name": "Whatever"},
            )

        assert resp.status_code == 404

    finally:
        app.dependency_overrides.clear()
