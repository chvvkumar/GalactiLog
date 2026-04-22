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


def _make_target(name="M 31", object_type="Galaxy", constellation="And", aliases=None):
    t = MagicMock(spec=Target)
    t.id = uuid.uuid4()
    t.primary_name = name
    t.object_type = object_type
    t.constellation = constellation
    t.aliases = aliases or []
    t.merged_into_id = None
    return t


def _stats_row(image_count=5, session_count=3, integration_seconds=3600.0):
    row = MagicMock()
    row.image_count = image_count
    row.session_count = session_count
    row.integration_seconds = integration_seconds
    return row


@pytest.mark.asyncio
async def test_merge_preview_with_loser_id_returns_200():
    winner = _make_target("M 31", aliases=["NGC 224"])
    loser = _make_target("Andromeda Galaxy", aliases=["And Gal"])
    admin = _make_admin()

    winner_stats = _stats_row(image_count=10, session_count=4, integration_seconds=7200.0)
    loser_stats = _stats_row(image_count=5, session_count=2, integration_seconds=3000.0)
    panel_scalar = MagicMock()
    panel_scalar.scalar_one.return_value = 2

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # winner image stats
            result.one.return_value = winner_stats
        elif call_count == 2:
            # loser image stats
            result.one.return_value = loser_stats
        elif call_count == 3:
            # mosaic panel count
            result.scalar_one.return_value = 2
        return result

    mock_session = AsyncMock()
    # session.get called twice: winner, loser
    mock_session.get = AsyncMock(side_effect=[winner, loser])
    mock_session.execute = mock_execute

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/targets/merge-preview",
                json={
                    "winner_id": str(winner.id),
                    "loser_id": str(loser.id),
                },
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["winner"]["primary_name"] == "M 31"
        assert data["winner"]["image_count"] == 10
        assert data["winner"]["session_count"] == 4
        assert data["winner"]["integration_seconds"] == 7200.0

        assert data["loser"]["primary_name"] == "Andromeda Galaxy"
        assert data["loser"]["image_count"] == 5
        assert data["loser"]["session_count"] == 2

        assert data["images_to_move"] == 5
        assert data["mosaic_panels_to_move"] == 2

        # loser primary_name and loser alias should be in aliases_to_add
        assert "Andromeda Galaxy" in data["aliases_to_add"]
        assert "And Gal" in data["aliases_to_add"]

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_preview_winner_not_found_returns_404():
    admin = _make_admin()

    mock_session = AsyncMock()
    # session.get returns None for winner
    mock_session.get = AsyncMock(return_value=None)

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/targets/merge-preview",
                json={
                    "winner_id": str(uuid.uuid4()),
                    "loser_id": str(uuid.uuid4()),
                },
            )

        assert resp.status_code == 404
        assert "Winner" in resp.json()["detail"]

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_preview_missing_loser_returns_400():
    admin = _make_admin()

    mock_session = AsyncMock()

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/targets/merge-preview",
                json={"winner_id": str(uuid.uuid4())},
            )

        assert resp.status_code == 400

    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_preview_with_loser_name_returns_200():
    winner = _make_target("M 31", aliases=["NGC 224"])
    admin = _make_admin()

    winner_stats = _stats_row(image_count=10, session_count=4, integration_seconds=7200.0)

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # winner image stats
            result.one.return_value = winner_stats
        elif call_count == 2:
            # unresolved count for loser_name
            result.scalar_one.return_value = 3
        return result

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=winner)
    mock_session.execute = mock_execute

    async def override_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = lambda: admin

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/targets/merge-preview",
                json={
                    "winner_id": str(winner.id),
                    "loser_name": "Andromeda",
                },
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["loser"]["primary_name"] == "Andromeda"
        assert data["loser"]["image_count"] == 3
        assert data["images_to_move"] == 3
        assert data["mosaic_panels_to_move"] == 0
        assert "Andromeda" in data["aliases_to_add"]

    finally:
        app.dependency_overrides.clear()
