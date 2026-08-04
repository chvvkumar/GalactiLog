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


def make_image(
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
    img.file_path = f"/data/Light_{filter_used}_{date_str}.fits"
    img.pier_side = "W"
    img.thumbnail_path = None
    img.raw_headers = {"OBJECT": "M 42", "EXPTIME": "300"}
    # Numeric optional fields must be None to prevent MagicMock comparison errors
    img.fwhm = None
    img.hfr_stdev = None
    img.guiding_rms_arcsec = None
    img.guiding_rms_ra_arcsec = None
    img.guiding_rms_dec_arcsec = None
    img.guiding_rms_source = None
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

    # load_alias_maps makes an extra execute() for UserSettings; return None row
    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    # all_hfr_q fetches (session_date, hfr, xpixsz, focallen) rows; .all()
    mock_all_hfr_result = MagicMock()
    mock_all_hfr_result.all.return_value = []

    # note_q: session note for this date; scalar_one_or_none
    mock_note_result = MagicMock()
    mock_note_result.scalar_one_or_none.return_value = None

    # cv_q: custom column values; .all()
    mock_cv_result = MagicMock()
    mock_cv_result.all.return_value = []

    # catalog-wide frames for the rig baseline; .all()
    mock_catalog_frames_result = MagicMock()
    mock_catalog_frames_result.all.return_value = []

    # phd2 night sessions; scalars().all(). Empty: these tests cover the
    # no-guide-log case, so the summary comes back None.
    mock_phd2_result = MagicMock()
    mock_phd2_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[
            mock_img_result, mock_alias_result,
            mock_all_hfr_result, mock_note_result, mock_cv_result,
            mock_catalog_frames_result, mock_phd2_result,
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

    assert "min_hfr" in data
    assert "max_hfr" in data
    assert data["min_hfr"] == 1.8
    assert data["max_hfr"] == 2.4
    assert data["min_eccentricity"] == 0.31
    assert data["max_eccentricity"] == 0.45
    assert data["sensor_temp"] is not None
    assert data["gain"] == 100
    assert 300.0 in data["exposure_times"]
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

    # load_alias_maps makes an extra execute() for UserSettings; return None row
    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    # all_hfr_q fetches (session_date, hfr, xpixsz, focallen) rows; .all()
    mock_all_hfr_result = MagicMock()
    mock_all_hfr_result.all.return_value = []

    # note_q: scalar_one_or_none
    mock_note_result = MagicMock()
    mock_note_result.scalar_one_or_none.return_value = None

    # cv_q: .all()
    mock_cv_result = MagicMock()
    mock_cv_result.all.return_value = []

    # catalog-wide frames for the rig baseline; .all()
    mock_catalog_frames_result = MagicMock()
    mock_catalog_frames_result.all.return_value = []

    # phd2 night sessions; scalars().all(). Empty: no guide log for this night.
    mock_phd2_result = MagicMock()
    mock_phd2_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[
            mock_img_result, mock_alias_result,
            mock_all_hfr_result, mock_note_result, mock_cv_result,
            mock_catalog_frames_result, mock_phd2_result,
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

    data = resp.json()
    insights = data["insights"]
    hfr_outliers = [i for i in insights if i["kind"] == "hfr_outliers"]
    assert len(hfr_outliers) == 1
    # median HFR 2.0 -> threshold 3.0 -> the 3.5 and 4.0 frames trip it. HFR is
    # unbounded, so the 1.5x-median rule is always reachable and is kept as-is.
    assert hfr_outliers[0]["level"] == "warning"
    assert hfr_outliers[0]["message"] == "2 frames with HFR outliers (> 3.0)"

    app.dependency_overrides.clear()


async def _fetch_session(images, catalog_rows=None, avg_hfr=2.0, tid=None):
    """Drive GET /api/targets/{tid}/sessions/{date} against mocked DB results.

    `catalog_rows` are the rows the "this rig overall" baseline query returns:
    (telescope, camera, filter_used, median_hfr, fwhm, eccentricity,
     detected_stars, adu_median, guiding_rms_arcsec).
    """
    tid = tid or uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    mock_img_result = MagicMock()
    mock_img_result.scalars.return_value.all.return_value = images

    mock_alias_result = MagicMock()
    mock_alias_result.scalar_one_or_none.return_value = None

    mock_all_hfr_result = MagicMock()
    mock_all_hfr_result.all.return_value = []

    mock_note_result = MagicMock()
    mock_note_result.scalar_one_or_none.return_value = None

    mock_cv_result = MagicMock()
    mock_cv_result.all.return_value = []

    mock_catalog_frames_result = MagicMock()
    mock_catalog_frames_result.all.return_value = catalog_rows or []

    # phd2 night sessions; scalars().all(). Empty: no guide log for this night.
    mock_phd2_result = MagicMock()
    mock_phd2_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[
            mock_img_result, mock_alias_result,
            mock_all_hfr_result, mock_note_result, mock_cv_result,
            mock_catalog_frames_result, mock_phd2_result,
        ]
    )

    async def override():
        yield mock_session

    from app.services.normalization import invalidate_alias_cache
    invalidate_alias_cache()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin_user()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/targets/{tid}/sessions/2026-03-20")
        assert resp.status_code == 200
        return resp.json()
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def no_baseline_cache(monkeypatch):
    """Bypass the Redis-backed rig-baseline cache.

    Without this the rig baseline is shared across tests (and across runs) via a
    real Redis if one is up, which would make these assertions order-dependent.
    """
    import app.services.cache as cache_mod

    async def passthrough(key, ttl, compute):
        return await compute()

    monkeypatch.setattr(cache_mod, "cached_json", passthrough)


def _ecc_session(eccs, **kwargs):
    return [
        make_image(f"2026-03-20T21:{i:02d}:00", ecc=e, **kwargs)
        for i, e in enumerate(eccs)
    ]


@pytest.mark.asyncio
async def test_session_detail_eccentricity_outlier_insight(no_baseline_cache):
    # Eight frames, tight spread, one blown frame. Note the median is 0.335, so
    # the old `median * 1.5` rule would have used a 0.50 threshold; the MAD rule
    # keys off dispersion instead.
    images = _ecc_session([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.90])
    data = await _fetch_session(images)

    ecc = [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"]
    assert len(ecc) == 1
    assert ecc[0]["level"] == "warning"
    assert ecc[0]["message"] == "1 frame with eccentricity outlier (≥ 3 MAD above the group median)"


@pytest.mark.asyncio
async def test_session_detail_eccentricity_insight_reachable_above_two_thirds(no_baseline_cache):
    # median 0.70. The old rule's threshold would be 1.05 -- unreachable, since
    # eccentricity is bounded [0, 1]. The rule went dark exactly when frames were
    # worst. This must now fire.
    images = _ecc_session([0.68, 0.69, 0.70, 0.70, 0.71, 0.72, 0.70, 0.95])
    data = await _fetch_session(images)

    ecc = [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"]
    assert len(ecc) == 1
    assert ecc[0]["message"].startswith("1 frame with eccentricity outlier")


@pytest.mark.asyncio
async def test_session_detail_no_eccentricity_insight_on_uniform_session(no_baseline_cache):
    images = _ecc_session([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37])
    data = await _fetch_session(images)
    assert [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"] == []


@pytest.mark.asyncio
async def test_session_detail_no_eccentricity_insight_when_group_sparse(no_baseline_cache):
    # Six frames < MIN_GROUP (8): no trustworthy MAD, so no claim. The old rule
    # fired here on three frames.
    images = _ecc_session([0.30, 0.31, 0.32, 0.33, 0.34, 0.90])
    data = await _fetch_session(images)
    assert [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"] == []


@pytest.mark.asyncio
async def test_session_detail_whole_night_eccentricity_insight(no_baseline_cache):
    # Every frame elongated. Per-frame z cannot see this (the session median
    # moves with the frames), so only the rig-history comparison catches it.
    images = _ecc_session([0.68, 0.70, 0.71, 0.72, 0.69, 0.73, 0.70, 0.71])
    # Rig history: 20 well-behaved frames on the same telescope|camera|filter.
    catalog_rows = [
        ("Esprit 150", "ZWO ASI2600MM", "Ha", 2.0, None, e, None, None, None)
        for e in [0.32, 0.34, 0.36, 0.38] * 5
    ]
    data = await _fetch_session(images, catalog_rows=catalog_rows)

    assert [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"] == []
    night = [i for i in data["insights"] if i["kind"] == "eccentricity_vs_rig"]
    assert len(night) == 1
    assert night[0]["level"] == "warning"
    assert "Whole session is elongated" in night[0]["message"]


@pytest.mark.asyncio
async def test_session_detail_no_whole_night_insight_when_night_is_typical(no_baseline_cache):
    images = _ecc_session([0.32, 0.34, 0.36, 0.38, 0.33, 0.35, 0.37, 0.34])
    catalog_rows = [
        ("Esprit 150", "ZWO ASI2600MM", "Ha", 2.0, None, e, None, None, None)
        for e in [0.32, 0.34, 0.36, 0.38] * 5
    ]
    data = await _fetch_session(images, catalog_rows=catalog_rows)
    assert [i for i in data["insights"] if i["kind"] == "eccentricity_vs_rig"] == []


@pytest.mark.asyncio
async def test_session_detail_no_whole_night_insight_without_rig_history(no_baseline_cache):
    images = _ecc_session([0.68, 0.70, 0.71, 0.72, 0.69, 0.73, 0.70, 0.71])
    data = await _fetch_session(images, catalog_rows=[])
    assert [i for i in data["insights"] if i["kind"] == "eccentricity_vs_rig"] == []


@pytest.mark.asyncio
async def test_session_detail_per_rig_insights_for_multi_rig_session(no_baseline_cache):
    # Two rigs the same night: rig A clean, rig B with one blown frame. Nothing
    # in the suite built a multi-rig session before, so the per-rig block was
    # entirely untested.
    rig_a = [
        make_image(f"2026-03-20T21:{i:02d}:00", ecc=e, hfr=2.0,
                   telescope="Esprit 150", camera="ZWO ASI2600MM")
        for i, e in enumerate([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37])
    ]
    rig_b = [
        make_image(f"2026-03-20T22:{i:02d}:00", ecc=e, hfr=2.0,
                   telescope="RedCat 51", camera="ZWO ASI533MC")
        for i, e in enumerate([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.90])
    ]
    data = await _fetch_session(rig_a + rig_b, avg_hfr=2.0)

    ecc = [i for i in data["insights"] if i["kind"] == "eccentricity_outliers"]
    # One per-rig insight for rig B only. Rig A is clean, and the session-level
    # rule is silent too: each frame is graded against its own train+filter
    # group, so rig B's outlier surfaces once at session level as well.
    prefixed = [i for i in ecc if i["message"].startswith("[RedCat 51 / ZWO ASI533MC] ")]
    assert len(prefixed) == 1
    assert prefixed[0]["message"].endswith("1 frame with eccentricity outlier (≥ 3 MAD above the group median)")
    assert not any(i["message"].startswith("[Esprit 150") for i in ecc)


@pytest.mark.asyncio
async def test_session_detail_insight_levels_and_kinds_are_within_the_schema(no_baseline_cache):
    images = _ecc_session([0.30, 0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.90])
    data = await _fetch_session(images)

    assert data["insights"]
    for i in data["insights"]:
        # The frontend keys INSIGHT_STYLES/INSIGHT_ICONS off `level`; an unknown
        # value renders an undefined class.
        assert i["level"] in {"info", "good", "warning"}
        assert i["kind"] in {
            "session_duration", "hfr_vs_target", "sensor_temp",
            "hfr_outliers", "eccentricity_outliers", "eccentricity_vs_rig",
        }
