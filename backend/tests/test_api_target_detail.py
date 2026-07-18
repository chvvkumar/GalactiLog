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
    img.eccentricity_source = None
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
    # object_type "Nebula" is not a SIMBAD code, so it categorizes to "Other"
    assert data["object_type"] == "Nebula"
    assert data["object_category"] == "Other"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_target_detail_derives_object_category():
    """Detail response must derive object_category from the stored SIMBAD code.

    Regression: the editor on TargetDetailPage reads object_category for both
    display and the <select> value. The detail endpoint previously never set
    object_category, so a saved object type (e.g. "G") never appeared and the
    inline editor looked like it reset on save.
    """
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "NGC 7331"
    target.aliases = []
    target.object_type = "G"  # SIMBAD code for Galaxy
    target.ra = 339.267
    target.dec = 34.416
    target.merged_into_id = None
    target.notes = None
    target.sac_description = None
    target.sac_notes = None
    target.reference_thumbnail_path = None
    target.name_locked = False

    images = [make_image(tid, "2026-03-20T21:00:00", filter_used="L")]

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

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
    assert data["object_type"] == "G"
    assert data["object_category"] == "Galaxy"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_target_detail_arcsec_fields():
    """Sessions and the target aggregate expose plate-scale-converted HFR.

    Frames whose raw headers carry XPIXSZ/FOCALLEN convert; frames without
    them are excluded from the arcsec aggregates (never compared in px).
    """
    tid = uuid.uuid4()
    target = MagicMock(spec=Target)
    target.id = tid
    target.primary_name = "M 42"
    target.aliases = []
    target.object_type = None
    target.ra = None
    target.dec = None
    target.merged_into_id = None
    target.notes = None
    target.sac_description = None
    target.sac_notes = None
    target.reference_thumbnail_path = None
    target.name_locked = False

    # 3.76 um at 530 mm -> ~1.4633 arcsec/px
    scaled = make_image(tid, "2026-03-20T21:00:00", hfr=2.0)
    scaled.raw_headers = {"OBJECT": "M 42", "XPIXSZ": "3.76", "FOCALLEN": "530"}
    unscaled = make_image(tid, "2026-03-14T22:00:00", hfr=3.0)  # no plate scale

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=target)

    mock_img_result = MagicMock()
    mock_img_result.all.return_value = [scaled, unscaled]
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

    # Aggregate: only the scaled frame contributes (2.0 px * 1.4633)
    assert data["avg_hfr_arcsec"] == pytest.approx(2.9265, abs=1e-3)
    # px aggregate still pools both frames (backward compat)
    assert data["avg_hfr"] == pytest.approx(2.5)

    sessions = {s["session_date"]: s for s in data["sessions"]}
    assert sessions["2026-03-20"]["hfr_arcsec"] == pytest.approx(2.9265, abs=1e-3)
    assert sessions["2026-03-14"]["hfr_arcsec"] is None
    assert sessions["2026-03-20"]["fwhm_arcsec"] is None  # no fwhm values

    # Both frames share eccentricity_source=None -> nothing excluded
    assert data["ecc_excluded_count"] == 0

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


def test_modal_source_ecc_tie_break_is_deterministic():
    """On a count tie, the lexicographically smaller source name wins, so the
    result does not depend on input ordering."""
    from app.services.target_detail import _modal_source_ecc

    # Two sources, equal counts (2 each). "csv" < "header" lexicographically.
    pairs = [
        ("header", 0.40),
        ("csv", 0.30),
        ("header", 0.50),
        ("csv", 0.20),
    ]
    mean_a, excluded_a = _modal_source_ecc(pairs)
    # Reversed input must produce the identical result.
    mean_b, excluded_b = _modal_source_ecc(list(reversed(pairs)))

    # "csv" values are 0.30 and 0.20 -> mean 0.25; the two "header" frames are
    # excluded.
    assert mean_a == pytest.approx(0.25)
    assert excluded_a == 2
    assert (mean_a, excluded_a) == (mean_b, excluded_b)
