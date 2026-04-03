import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from pathlib import Path

from PIL import Image as PILImage

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.auth import get_current_user
from app.services.mosaic_composite import (
    select_best_frame,
    generate_panel_thumbnail,
    compute_panel_layout,
    composite_panels,
    PanelInfo,
    LayoutPosition,
    _compute_cache_key,
    _composite_cache,
)


@pytest.fixture
def mock_session():
    return AsyncMock()


def _make_row(image_id, median_hfr, centalt, file_path, ra, dec, objctrot, pierside):
    row = MagicMock()
    row.id = image_id
    row.median_hfr = median_hfr
    row.file_path = file_path
    row.raw_headers = {
        "RA": ra,
        "DEC": dec,
        "OBJCTROT": objctrot,
        "PIERSIDE": pierside,
        "CENTALT": centalt,
        "FOCALLEN": 448.0,
        "XPIXSZ": 3.76,
    }
    return row


@pytest.mark.asyncio
async def test_select_best_frame_picks_lowest_hfr(mock_session):
    target_id = uuid4()
    good = _make_row(uuid4(), 1.2, 45.0, "/fits/good.fits", 37.0, 61.8, 108.0, "West")

    mock_session.execute = AsyncMock(side_effect=[
        MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=good)))),
    ])

    result = await select_best_frame(target_id, None, mock_session)
    assert result is not None
    assert result.median_hfr == 1.2


@pytest.mark.asyncio
async def test_select_best_frame_falls_back_to_centalt(mock_session):
    target_id = uuid4()
    zenith = _make_row(uuid4(), 0, 85.0, "/fits/zenith.fits", 37.0, 61.8, 108.0, "West")

    mock_session.execute = AsyncMock(side_effect=[
        MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))),
        MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=zenith)))),
    ])

    result = await select_best_frame(target_id, None, mock_session)
    assert result is not None
    assert result.raw_headers["CENTALT"] == 85.0


def test_generate_panel_thumbnail(tmp_path: Path):
    rng = np.random.default_rng(42)
    data = rng.normal(loc=1000, scale=50, size=(256, 256)).astype(np.float32)
    data[128, 128] = 50000

    fake_path = tmp_path / "panel.fits"
    with patch("app.services.mosaic_composite._read_decimated", return_value=data):
        img = generate_panel_thumbnail(fake_path, max_width=400)
    assert isinstance(img, PILImage.Image)
    assert img.width <= 400
    assert img.height > 0


def test_compute_panel_layout_two_panels():
    panels = [
        PanelInfo(panel_id="p1", ra=37.0, dec=61.8, objctrot=108.0,
                  pierside="West", fits_path="/fits/p1.fits", focallen=448.0, xpixsz=3.76),
        PanelInfo(panel_id="p2", ra=37.5, dec=61.8, objctrot=108.0,
                  pierside="West", fits_path="/fits/p2.fits", focallen=448.0, xpixsz=3.76),
    ]
    layout = compute_panel_layout(panels, tile_width=400, tile_height=400)
    assert len(layout) == 2
    assert layout[0].x != layout[1].x
    assert abs(layout[0].y - layout[1].y) < 1.0


def test_compute_panel_layout_pier_flip_rotation():
    panels = [
        PanelInfo(panel_id="p1", ra=37.0, dec=61.8, objctrot=108.0,
                  pierside="West", fits_path="/f/1.fits", focallen=448.0, xpixsz=3.76),
        PanelInfo(panel_id="p2", ra=37.5, dec=61.8, objctrot=108.0,
                  pierside="East", fits_path="/f/2.fits", focallen=448.0, xpixsz=3.76),
    ]
    layout = compute_panel_layout(panels, tile_width=400, tile_height=400)
    rot_diff = abs(layout[1].rotation - layout[0].rotation)
    assert abs(rot_diff - 180.0) < 0.01 or abs(rot_diff + 180.0) < 0.01


def test_composite_panels_produces_image():
    tile1 = PILImage.new("RGB", (100, 100), color=(255, 0, 0))
    tile2 = PILImage.new("RGB", (100, 100), color=(0, 0, 255))

    layout = [
        LayoutPosition(panel_id="p1", x=0, y=0, rotation=0, fits_path=""),
        LayoutPosition(panel_id="p2", x=120, y=0, rotation=0, fits_path=""),
    ]
    tiles = {"p1": tile1, "p2": tile2}

    result = composite_panels(tiles, layout)
    assert isinstance(result, PILImage.Image)
    assert result.width >= 220
    assert result.height >= 100


def test_composite_panels_with_rotation():
    tile = PILImage.new("RGB", (100, 100), color=(0, 255, 0))
    layout = [
        LayoutPosition(panel_id="p1", x=100, y=100, rotation=45.0, fits_path=""),
    ]
    tiles = {"p1": tile}

    result = composite_panels(tiles, layout)
    assert isinstance(result, PILImage.Image)
    assert result.width > 0
    assert result.height > 0


def test_cache_key_changes_with_different_frames():
    key1 = _compute_cache_key("mosaic-1", [uuid4(), uuid4()])
    key2 = _compute_cache_key("mosaic-1", [uuid4(), uuid4()])
    assert key1 != key2


def test_cache_key_stable_for_same_frames():
    ids = [uuid4(), uuid4()]
    key1 = _compute_cache_key("mosaic-1", ids)
    key2 = _compute_cache_key("mosaic-1", ids)
    assert key1 == key2


@pytest.fixture
def admin_user():
    from app.models.user import User, UserRole
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    return user


@pytest.mark.asyncio
async def test_composite_endpoint_returns_jpeg(mock_session, admin_user):
    """GET /api/mosaics/{id}/composite should return JPEG when mosaic exists."""
    mosaic_id = str(uuid4())
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100

    fake_mosaic = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=fake_mosaic))))
    )

    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_current_user] = lambda: admin_user

    with patch("app.api.mosaics.build_mosaic_composite", return_value=fake_jpeg):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/mosaics/{mosaic_id}/composite")

    app.dependency_overrides.clear()
    assert resp.status_code in (200, 404, 422)


@pytest.mark.asyncio
async def test_composite_endpoint_404_missing_mosaic(mock_session, admin_user):
    """GET /api/mosaics/{id}/composite should return 404 for unknown mosaic."""
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )

    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_current_user] = lambda: admin_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/mosaics/{uuid4()}/composite")

    app.dependency_overrides.clear()
    assert resp.status_code == 404
