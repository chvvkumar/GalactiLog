"""Tests for mosaic batch panel update endpoint and mosaic-level field persistence."""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.auth import get_current_user


def _make_admin_user():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    return user


def _make_target(name="NGC 1234"):
    from app.models import Target
    t = MagicMock(spec=Target)
    t.id = uuid.uuid4()
    t.primary_name = name
    t.ra = 42.0
    t.dec = -10.0
    return t


def _make_panel(mosaic_id, target, label="Panel 1", sort_order=0,
                grid_row=None, grid_col=None, rotation=0, flip_h=False,
                object_pattern=None):
    from app.models.mosaic_panel import MosaicPanel
    p = MagicMock(spec=MosaicPanel)
    p.id = uuid.uuid4()
    p.mosaic_id = mosaic_id
    p.target_id = target.id
    p.target = target
    p.panel_label = label
    p.sort_order = sort_order
    p.object_pattern = object_pattern
    p.grid_row = grid_row
    p.grid_col = grid_col
    p.rotation = rotation
    p.flip_h = flip_h
    return p


def _make_mosaic(name="Test Mosaic", panels=None, rotation_angle=0.0, pixel_coords=False):
    from app.models.mosaic import Mosaic
    m = MagicMock(spec=Mosaic)
    m.id = uuid.uuid4()
    m.name = name
    m.notes = None
    m.rotation_angle = rotation_angle
    m.pixel_coords = pixel_coords
    m.panels = panels or []
    return m


def _mock_session_for_batch(mosaic):
    """Create a mock session that returns the given mosaic for the first execute(),
    and empty result sets for subsequent stats queries."""
    mock_session = AsyncMock()

    # First execute call returns the mosaic (scalar_one_or_none);
    # all subsequent calls return empty result sets (for _batch_panel_stats queries).
    mosaic_result = MagicMock()
    mosaic_result.scalar_one_or_none.return_value = mosaic

    first_call = [True]

    async def _execute_side_effect(*args, **kwargs):
        if first_call[0]:
            first_call[0] = False
            return mosaic_result
        empty = MagicMock()
        empty.all.return_value = []
        empty.one.return_value = (0, 0, None)
        return empty

    mock_session.execute = AsyncMock(side_effect=_execute_side_effect)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    return mock_session


# ---------------------------------------------------------------------------
# 1. Batch endpoint happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_update_panels_happy_path():
    """Batch update positions/rotation/flip for all panels, verify 200 response."""
    admin = _make_admin_user()
    target = _make_target()
    mosaic = _make_mosaic()
    p1 = _make_panel(mosaic.id, target, "Panel 1", sort_order=0)
    p2 = _make_panel(mosaic.id, target, "Panel 2", sort_order=1)
    mosaic.panels = [p1, p2]

    mock_session = _mock_session_for_batch(mosaic)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    body = [
        {"panel_id": str(p1.id), "grid_row": 0, "grid_col": 0, "rotation": 90, "flip_h": True},
        {"panel_id": str(p2.id), "grid_row": 0, "grid_col": 1, "rotation": 180, "flip_h": False},
    ]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{mosaic.id}/panels/batch", json=body
            )

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Both panels returned
        assert len(data) == 2

        # Verify the mock panel objects were mutated
        assert p1.grid_row == 0
        assert p1.grid_col == 0
        assert p1.rotation == 90
        assert p1.flip_h is True
        assert p2.grid_row == 0
        assert p2.grid_col == 1
        assert p2.rotation == 180
        assert p2.flip_h is False
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Batch endpoint partial update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_update_partial_fields():
    """Send only grid_row for one panel; other fields remain unchanged."""
    admin = _make_admin_user()
    target = _make_target()
    mosaic = _make_mosaic()
    p1 = _make_panel(mosaic.id, target, "Panel 1", sort_order=0,
                     grid_row=5, grid_col=3, rotation=90, flip_h=True)
    mosaic.panels = [p1]

    mock_session = _mock_session_for_batch(mosaic)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    # Only update grid_row, leave everything else as-is
    body = [{"panel_id": str(p1.id), "grid_row": 2}]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{mosaic.id}/panels/batch", json=body
            )

        assert resp.status_code == 200

        # grid_row updated
        assert p1.grid_row == 2
        # Other fields unchanged
        assert p1.grid_col == 3
        assert p1.rotation == 90
        assert p1.flip_h is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Batch endpoint invalid panel_id (not in mosaic)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_update_invalid_panel_id():
    """A panel_id that doesn't belong to the mosaic should return 404."""
    admin = _make_admin_user()
    target = _make_target()
    mosaic = _make_mosaic()
    p1 = _make_panel(mosaic.id, target, "Panel 1")
    mosaic.panels = [p1]

    mock_session = _mock_session_for_batch(mosaic)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    bogus_id = str(uuid.uuid4())
    body = [{"panel_id": bogus_id, "grid_row": 0}]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{mosaic.id}/panels/batch", json=body
            )

        assert resp.status_code == 404
        assert "not found in mosaic" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Batch endpoint cross-mosaic rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_update_cross_mosaic_panel():
    """A panel_id from a different mosaic should return 404."""
    admin = _make_admin_user()
    target = _make_target()

    mosaic_a = _make_mosaic(name="Mosaic A")
    panel_a = _make_panel(mosaic_a.id, target, "Panel 1")
    mosaic_a.panels = [panel_a]

    mosaic_b = _make_mosaic(name="Mosaic B")
    panel_b = _make_panel(mosaic_b.id, target, "Panel 1")
    mosaic_b.panels = [panel_b]

    # Session returns mosaic_a when queried
    mock_session = _mock_session_for_batch(mosaic_a)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    # Try to update panel_b (belongs to mosaic_b) via mosaic_a's batch endpoint
    body = [{"panel_id": str(panel_b.id), "grid_row": 1}]

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{mosaic_a.id}/panels/batch", json=body
            )

        assert resp.status_code == 404
        assert "not found in mosaic" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. rotation_angle persistence via PUT /mosaics/{id} then GET
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotation_angle_persistence():
    """PUT rotation_angle on a mosaic, then GET and verify it is returned."""
    admin = _make_admin_user()
    target = _make_target()
    mosaic = _make_mosaic(rotation_angle=0.0)
    mosaic.panels = [_make_panel(mosaic.id, target, "Panel 1")]

    mock_session = AsyncMock()

    # For PUT: session.get returns the mosaic
    mock_session.get = AsyncMock(return_value=mosaic)
    mock_session.commit = AsyncMock()

    # For GET: session.execute returns the mosaic via scalar_one_or_none
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = mosaic
    mock_session.execute = AsyncMock(return_value=get_result)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Update rotation_angle
            put_resp = await client.put(
                f"/api/mosaics/{mosaic.id}",
                json={"rotation_angle": 45.5},
            )
            assert put_resp.status_code == 200

        # The endpoint sets mosaic.rotation_angle = 45.5 on the mock
        assert mosaic.rotation_angle == 45.5

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # GET to verify the value is returned in the response
            get_resp = await client.get(f"/api/mosaics/{mosaic.id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["rotation_angle"] == 45.5
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. pixel_coords persistence via PUT /mosaics/{id} then GET
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pixel_coords_persistence():
    """PUT pixel_coords=true on a mosaic, then GET and verify it is returned."""
    admin = _make_admin_user()
    target = _make_target()
    mosaic = _make_mosaic(pixel_coords=False)
    mosaic.panels = [_make_panel(mosaic.id, target, "Panel 1")]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mosaic)
    mock_session.commit = AsyncMock()

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = mosaic
    mock_session.execute = AsyncMock(return_value=get_result)

    async def override_session():
        yield mock_session
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: admin

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            put_resp = await client.put(
                f"/api/mosaics/{mosaic.id}",
                json={"pixel_coords": True},
            )
            assert put_resp.status_code == 200

        assert mosaic.pixel_coords is True

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            get_resp = await client.get(f"/api/mosaics/{mosaic.id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["pixel_coords"] is True
    finally:
        app.dependency_overrides.clear()
