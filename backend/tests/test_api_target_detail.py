import uuid
import pytest
from datetime import datetime, timezone, date
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models import Target, Image
from app.models.user import User, UserRole


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def make_image(
    target_id,
    date_str,
    session_date_val=None,
    filter_used="Ha",
    exposure=300.0,
    hfr=2.1,
    ecc=0.38,
    temp=-10.0,
    gain=100,
    camera="ZWO ASI2600MM",
    telescope="Esprit 150",
):
    """Build a row-like mock for the projected column query in get_target_detail."""
    img = MagicMock()
    img.image_type = "LIGHT"
    img.resolved_target_id = target_id
    img.capture_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    # session_date must be a date object or string matching the grouping key
    img.session_date = session_date_val or date.fromisoformat(date_str[:10])
    img.filter_used = filter_used
    img.exposure_time = exposure
    img.median_hfr = hfr
    img.eccentricity = ecc
    img.sensor_temp = temp
    img.camera_gain = gain
    img.camera = camera
    img.telescope = telescope
    img.file_name = f"Light_{filter_used}_{date_str}.fits"
    img.thumbnail_path = None
    img.raw_headers = {"OBJECT": "M 42"}
    # Fields that must be None rather than MagicMock to avoid comparison errors
    img.fwhm = None
    img.guiding_rms_arcsec = None
    img.detected_stars = None
    img.rotator_position = None
    return img


@pytest.mark.asyncio
async def test_target_detail_resolved():
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"
    target.aliases = ["Orion Nebula"]
    target.object_type = "Nebula"
    target.ra = 83.822
    target.dec = -5.391
    target.merged_into_id = None
    target.notes = None
    target.sac_description = None
    target.sac_notes = None
    target.reference_thumbnail_path = None
    target.name_locked = False

    images = [
        make_image(tid, "2026-03-20T21:00:00", filter_used="Ha"),
        make_image(tid, "2026-03-20T21:05:00", filter_used="OIII", hfr=2.3),
        make_image(tid, "2026-03-14T22:00:00", filter_used="SII", hfr=2.5),
    ]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    # Execute call order: images, load_alias_maps (settings), note_dates_q, cv_q, memberships
    mock_img_result = MagicMock()
    mock_img_result.all.return_value = images

    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    mock_notes_result = MagicMock()
    mock_notes_result.all.return_value = []

    mock_cv_result = MagicMock()
    mock_cv_result.all.return_value = []

    mock_memberships_result = MagicMock()
    mock_memberships_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[
            mock_img_result, mock_alias_result, mock_notes_result,
            mock_cv_result, mock_memberships_result,
        ]
    )

    async def override():
        yield mock_session

    from app.services.normalization import invalidate_alias_cache
    invalidate_alias_cache()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin_user()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets/{tid}/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_name"] == "M 42"
    assert data["total_frames"] == 3
    assert data["session_count"] == 2
    assert len(data["sessions"]) == 2
    assert data["sessions"][0]["session_date"] == "2026-03-20"
    assert data["sessions"][0]["frame_count"] == 2

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_target_detail_unresolved():
    images = [
        make_image(None, "2026-03-20T21:00:00", filter_used="Ha"),  # noqa: E501
    ]
    images[0].resolved_target_id = None
    images[0].raw_headers = {"OBJECT": "IC 1396"}

    mock_session = AsyncMock()

    mock_img_result = MagicMock()
    mock_img_result.all.return_value = images

    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    # No note_dates_q or cv_q for obj: prefix targets (target_obj is None)
    mock_session.execute = AsyncMock(
        side_effect=[mock_img_result, mock_alias_result]
    )

    async def override():
        yield mock_session

    from app.services.normalization import invalidate_alias_cache
    invalidate_alias_cache()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin_user()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/targets/obj:IC 1396/detail")

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_name"] == "IC 1396"
    assert data["total_frames"] == 1

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_target_detail_not_found():
    tid = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin_user()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets/{tid}/detail")

    assert resp.status_code == 404

    app.dependency_overrides.clear()
