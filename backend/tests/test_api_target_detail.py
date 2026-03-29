import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.models import Target, Image


def make_image(
    target_id,
    date_str,
    filter_used="Ha",
    exposure=300.0,
    hfr=2.1,
    ecc=0.38,
    temp=-10.0,
    gain=100,
    camera="ZWO ASI2600MM",
    telescope="Esprit 150",
):
    img = MagicMock(spec=Image)
    img.image_type = "LIGHT"
    img.resolved_target_id = target_id
    img.capture_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
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

    images = [
        make_image(tid, "2026-03-20T21:00:00", "Ha"),
        make_image(tid, "2026-03-20T21:05:00", "OIII", hfr=2.3),
        make_image(tid, "2026-03-14T22:00:00", "SII", hfr=2.5),
    ]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)
    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images
    mock_session.execute = AsyncMock(return_value=mock_img_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override

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
        make_image(None, "2026-03-20T21:00:00", "Ha"),
    ]
    images[0].resolved_target_id = None
    images[0].raw_headers = {"OBJECT": "IC 1396"}

    mock_session = AsyncMock()
    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images
    mock_session.execute = AsyncMock(return_value=mock_img_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets/{tid}/detail")

    assert resp.status_code == 404

    app.dependency_overrides.clear()
