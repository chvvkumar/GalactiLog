import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.models import Target, Image


def make_image(
    date_str,
    filter_used="Ha",
    exposure=300.0,
    hfr=2.1,
    ecc=0.38,
    temp=-10.0,
    gain=100,
):
    img = MagicMock(spec=Image)
    img.capture_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    img.filter_used = filter_used
    img.exposure_time = exposure
    img.median_hfr = hfr
    img.eccentricity = ecc
    img.sensor_temp = temp
    img.camera_gain = gain
    img.camera = "ZWO ASI2600MM"
    img.telescope = "Esprit 150"
    img.file_name = f"Light_{filter_used}_{date_str}.fits"
    img.thumbnail_path = None
    img.raw_headers = {"OBJECT": "M 42", "EXPTIME": "300"}
    return img


@pytest.mark.asyncio
async def test_session_detail_has_new_fields():
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"

    images = [
        make_image("2026-03-20T21:00:00", "Ha", hfr=1.8, ecc=0.31, temp=-10.0),
        make_image("2026-03-20T21:05:00", "Ha", hfr=2.1, ecc=0.38, temp=-10.0),
        make_image("2026-03-20T21:10:00", "OIII", hfr=2.4, ecc=0.45, temp=-9.5),
    ]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images

    mock_all_result = MagicMock()
    mock_all_result.scalars.return_value.all.return_value = images

    mock_session.execute = AsyncMock(side_effect=[mock_img_result, mock_all_result])

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets/{tid}/sessions/2026-03-20")

    assert resp.status_code == 200
    data = resp.json()

    assert "min_hfr" in data
    assert "max_hfr" in data
    assert data["min_hfr"] == 1.8
    assert data["max_hfr"] == 2.4
    assert data["min_eccentricity"] == 0.31
    assert data["max_eccentricity"] == 0.45
    assert data["sensor_temp"] is not None
    assert data["gain"] == 100
    assert data["exposure_time"] == 300.0
    assert data["first_frame_time"] is not None
    assert data["last_frame_time"] is not None

    assert len(data["filter_details"]) == 2
    ha_detail = next(f for f in data["filter_details"] if f["filter_name"] == "Ha")
    assert ha_detail["frame_count"] == 2

    assert len(data["frames"]) == 3
    assert data["frames"][0]["file_name"] == "Light_Ha_2026-03-20T21:00:00.fits"

    assert len(data["insights"]) > 0
    levels = {i["level"] for i in data["insights"]}
    assert "info" in levels

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_session_detail_hfr_outlier_insight():
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"

    images = [
        make_image("2026-03-20T21:00:00", "Ha", hfr=2.0),
        make_image("2026-03-20T21:05:00", "Ha", hfr=2.0),
        make_image("2026-03-20T21:10:00", "Ha", hfr=2.0),
        make_image("2026-03-20T21:15:00", "Ha", hfr=2.0),
        make_image("2026-03-20T21:20:00", "Ha", hfr=3.5),
        make_image("2026-03-20T21:25:00", "Ha", hfr=4.0),
    ]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images
    mock_all_result = MagicMock()
    mock_all_result.scalars.return_value.all.return_value = images
    mock_session.execute = AsyncMock(side_effect=[mock_img_result, mock_all_result])

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets/{tid}/sessions/2026-03-20")

    data = resp.json()
    messages = [i["message"] for i in data["insights"]]
    hfr_warning = [m for m in messages if "HFR" in m and "outlier" in m.lower()]
    assert len(hfr_warning) == 1

    app.dependency_overrides.clear()
