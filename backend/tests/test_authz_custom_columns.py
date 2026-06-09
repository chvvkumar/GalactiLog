"""Authorization tests for custom_columns write endpoints (SEC-2).

Viewer role must be read-only: state-changing endpoints require admin.
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
async def test_create_custom_column_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/custom-columns",
                json={"name": "Seeing", "column_type": "text", "applies_to": "target"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_custom_column_admin_allowed(admin_user):
    mock_session = AsyncMock()
    # _unique_slug + max display_order queries
    slug_result = MagicMock()
    slug_result.scalar_one_or_none.return_value = None
    order_result = MagicMock()
    order_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[slug_result, order_result])
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    created = {}

    async def _refresh(obj):
        # Populate server-side defaults the response model needs.
        obj.created_at = __import__("datetime").datetime.now()
        created["obj"] = obj

    mock_session.refresh = AsyncMock(side_effect=_refresh)

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/custom-columns",
                json={"name": "Seeing", "column_type": "text", "applies_to": "target"},
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["name"] == "Seeing"
    finally:
        app.dependency_overrides.clear()


def _make_column():
    from datetime import datetime
    from app.models.custom_column import CustomColumn, ColumnType, AppliesTo
    col = MagicMock(spec=CustomColumn)
    col.id = uuid.uuid4()
    col.name = "Seeing"
    col.slug = "seeing"
    col.column_type = ColumnType.text
    col.applies_to = AppliesTo.target
    col.dropdown_options = None
    col.display_order = 0
    col.created_by = uuid.uuid4()
    col.created_at = datetime.now()
    return col


@pytest.mark.asyncio
async def test_update_custom_column_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.patch(
                f"/api/custom-columns/{uuid.uuid4()}", json={"name": "x"}
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_custom_column_admin_allowed(admin_user):
    col = _make_column()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=col)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # display_order-only update avoids the slug uniqueness query.
            resp = await client.patch(
                f"/api/custom-columns/{col.id}", json={"display_order": 3}
            )
        assert resp.status_code == 200, resp.text
        assert col.display_order == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_custom_column_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/custom-columns/{uuid.uuid4()}")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_custom_column_admin_allowed(admin_user):
    col = _make_column()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=col)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/custom-columns/{col.id}")
        assert resp.status_code == 204, resp.text
        mock_session.delete.assert_awaited_once_with(col)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_set_custom_value_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/custom-columns/values",
                json={"column_id": str(uuid.uuid4()), "value": "1"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
