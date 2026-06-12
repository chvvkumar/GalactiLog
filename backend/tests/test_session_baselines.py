import uuid
import pytest
from datetime import datetime, timezone
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


def make_image(date_str, filter_used="Ha", hfr=2.1, ecc=0.38):
    img = MagicMock(spec=Image)
    img.capture_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    img.filter_used = filter_used
    img.exposure_time = 300.0
    img.median_hfr = hfr
    img.eccentricity = ecc
    img.sensor_temp = -10.0
    img.camera_gain = 100
    img.camera = "ZWO ASI2600MM"
    img.telescope = "Esprit 150"
    img.file_name = f"Light_{filter_used}_{date_str}.fits"
    img.file_path = f"/data/Light_{filter_used}_{date_str}.fits"
    img.pier_side = "W"
    img.thumbnail_path = None
    img.raw_headers = {"OBJECT": "M 42", "EXPTIME": "300"}
    img.fwhm = None
    img.hfr_stdev = None
    img.guiding_rms_arcsec = None
    img.guiding_rms_ra_arcsec = None
    img.guiding_rms_dec_arcsec = None
    img.detected_stars = None
    img.adu_stdev = None
    img.adu_mean = None
    img.adu_median = None
    img.adu_min = None
    img.adu_max = None
    img.focuser_position = None
    img.focuser_temp = None
    img.rotator_position = None
    img.airmass = None
    img.ambient_temp = None
    img.dew_point = None
    img.humidity = None
    img.pressure = None
    img.wind_speed = None
    img.wind_direction = None
    img.wind_gust = None
    img.cloud_cover = None
    img.sky_quality = None
    return img


@pytest.mark.asyncio
async def test_session_detail_returns_baselines():
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"

    images = [
        make_image("2026-03-20T21:00:00", "Ha", hfr=2.0, ecc=0.30),
        make_image("2026-03-20T21:05:00", "Ha", hfr=2.4, ecc=0.40),
    ]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    # img_q -> scalars().all()
    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images

    # avg_hfr_q -> scalar()
    mock_avg_result = MagicMock()
    mock_avg_result.scalar.return_value = 2.1

    # load_alias_maps -> scalar_one_or_none() None
    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    # all_hfr_q -> .all() rows of (session_date, median_hfr)
    mock_all_hfr_result = MagicMock()
    mock_all_hfr_result.all.return_value = [
        ("2026-03-20", 2.0), ("2026-03-20", 2.4),
    ]

    # note_q -> scalar_one_or_none()
    mock_note_result = MagicMock()
    mock_note_result.scalar_one_or_none.return_value = None

    # cv_q -> .all()
    mock_cv_result = MagicMock()
    mock_cv_result.all.return_value = []

    # target cross-session frames -> .all() of column rows
    # columns: telescope, camera, filter_used, median_hfr, fwhm, eccentricity,
    #          detected_stars, adu_median, guiding_rms_arcsec
    target_frame_rows = [
        ("Esprit 150", "ZWO ASI2600MM", "Ha", 2.0, None, 0.30, None, None, None),
        ("Esprit 150", "ZWO ASI2600MM", "Ha", 2.4, None, 0.40, None, None, None),
    ]
    mock_target_frames_result = MagicMock()
    mock_target_frames_result.all.return_value = target_frame_rows

    # catalog-wide frames -> .all() of column rows
    catalog_frame_rows = [
        ("Esprit 150", "ZWO ASI2600MM", "Ha", 2.1, None, 0.35, None, None, None),
    ]
    mock_catalog_frames_result = MagicMock()
    mock_catalog_frames_result.all.return_value = catalog_frame_rows

    mock_session.execute = AsyncMock(
        side_effect=[
            mock_img_result, mock_avg_result, mock_alias_result,
            mock_all_hfr_result, mock_note_result, mock_cv_result,
            mock_target_frames_result, mock_catalog_frames_result,
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
        resp = await client.get(f"/api/targets/{tid}/sessions/2026-03-20")

    assert resp.status_code == 200
    data = resp.json()

    assert "session_baselines" in data
    assert "rig_baselines" in data

    key = "Esprit 150|ZWO ASI2600MM|Ha"
    assert key in data["session_baselines"]
    sb = data["session_baselines"][key]
    assert sb["median_hfr"]["median"] == 2.2
    assert sb["median_hfr"]["n"] == 2
    assert "mad" in sb["median_hfr"]

    assert key in data["rig_baselines"]
    rb = data["rig_baselines"][key]
    assert "median_hfr" in rb
    assert "median" in rb["median_hfr"]

    app.dependency_overrides.clear()
