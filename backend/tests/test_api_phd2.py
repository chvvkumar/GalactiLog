"""Contract tests for /api/phd2. The frontend is written against these shapes."""
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.database import get_session
from app.main import app
from app.models.user import User, UserRole


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def _override_user(user):
    async def _dep():
        return user
    return _dep


def _override_session(session):
    async def _dep():
        yield session
    return _dep


def _session_row(**kw):
    base = dict(
        id=uuid.uuid4(),
        started_at_utc=datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc),
        ended_at_utc=datetime(2026, 7, 15, 1, 44, 27, tzinfo=timezone.utc),
        duration_s=120.0,
        frame_count=240,
        equipment_profile="AM5n_OAG_ASI174M",
        telescope="140APO",
        pixel_scale_arcsec=1.54,
        rms_ra_arcsec=0.71,
        rms_dec_arcsec=0.55,
        rms_total_arcsec=0.9,
        peak_ra_arcsec=2.4,
        peak_dec_arcsec=1.9,
        drop_count=3,
        max_drop_run=2,
        unguided_seconds=4.5,
        dither_count=6,
        settle_count=6,
        settle_failed_count=1,
        settle_median_s=3.5,
        snr_mean=28.4,
        star_mass_mean=1712.0,
        last_cal_issue="None",
        pier_side="West",
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _alias_map(monkeypatch):
    """No equipment grouping unless a test says otherwise.

    The route resolves its `telescope` argument through the alias map, and
    that reader caches in-process, so leaving it unpatched would let another
    module's cached map decide what these tests match.
    """
    from app.services import normalization

    tel_map: dict[str, str] = {}

    async def _load(_session):
        return {}, {}, tel_map

    monkeypatch.setattr(normalization, "load_alias_maps", _load)
    return tel_map


def _result_with(scalars_all=None, all_rows=None, scalar_one=None):
    result = MagicMock()
    result.scalars.return_value.all.return_value = scalars_all or []
    result.all.return_value = all_rows or []
    result.scalar_one_or_none.return_value = scalar_one
    return result


@pytest.mark.asyncio
async def test_sessions_requires_authentication():
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/phd2/sessions?session_date=2026-07-14")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sessions_returns_the_summary_contract():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[_session_row()]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=140APO"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"sessions"}
    s = body["sessions"][0]
    assert set(s) == {
        "id", "started_at", "ended_at", "duration_s", "frame_count",
        "equipment_profile", "telescope", "pixel_scale_arcsec",
        "rms_ra_arcsec", "rms_dec_arcsec", "rms_total_arcsec",
        "peak_ra_arcsec", "peak_dec_arcsec", "drop_count", "max_drop_run",
        "unguided_seconds", "dither_count", "settle_count",
        "settle_failed_count", "settle_median_s", "snr_mean",
        "star_mass_mean", "last_cal_issue", "pier_side", "gated",
    }
    assert s["telescope"] == "140APO"
    assert s["frame_count"] == 240
    assert s["gated"] is False
    assert isinstance(s["id"], str)


@pytest.mark.asyncio
async def test_short_session_is_reported_as_gated():
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_result_with(scalars_all=[_session_row(frame_count=42)])
    )
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/phd2/sessions?session_date=2026-07-14")
    app.dependency_overrides.clear()
    assert resp.json()["sessions"][0]["gated"] is True


@pytest.mark.asyncio
async def test_sessions_fall_back_to_the_nights_sole_unmapped_profile():
    """Same rule as the session-detail night summary. Before any profile is
    mapped every stored telescope is NULL, and a strict equality filter here
    returned an empty graph under a populated guiding panel."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[
        _session_row(telescope=None), _session_row(telescope=None),
    ]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=140APO"
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 2


@pytest.mark.asyncio
async def test_sessions_attribute_nothing_when_two_profiles_are_unmapped():
    """Guessing which of two rigs a target used would attach the wrong guiding
    numbers to real data, which is worse than showing none."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[
        _session_row(telescope=None, equipment_profile="AM5n_OAG_ASI174M"),
        _session_row(telescope=None, equipment_profile="ASI220mm_30F5_AM5"),
    ]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=140APO"
        )
    app.dependency_overrides.clear()
    assert resp.json()["sessions"] == []


@pytest.mark.asyncio
async def test_sessions_prefer_mapped_rows_over_the_fallback():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[
        _session_row(telescope="140APO"),
        _session_row(telescope="RedCat 51", equipment_profile="ASI220mm_30F5_AM5"),
    ]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=140APO"
        )
    app.dependency_overrides.clear()
    sessions = resp.json()["sessions"]
    assert [s["telescope"] for s in sessions] == ["140APO"]


@pytest.mark.asyncio
async def test_sessions_do_not_borrow_a_profile_mapped_to_another_rig():
    """The night's sole profile is mapped, but to a different telescope. The
    fallback exists for the unmapped, pre-configuration state; borrowing here
    would draw the guided rig's graph on the unguided rig's card."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[
        _session_row(telescope="RedCat 51", equipment_profile="ASI220mm_30F5_AM5"),
    ]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=140APO"
        )
    app.dependency_overrides.clear()
    assert resp.json()["sessions"] == []


@pytest.mark.asyncio
async def test_sessions_match_a_profile_map_holding_an_aliased_name(_alias_map):
    """The card asks for the canonical rig name while the profile map still
    holds the name it had before the rig was grouped. Grouping equipment never
    re-keys that map, so the route has to accept either form."""
    _alias_map["SVBony SV503 80mm"] = "SVBony 80ED"
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalars_all=[
        _session_row(telescope="SVBony SV503 80mm", equipment_profile="ASI220mm_30F5_AM5"),
    ]))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/phd2/sessions?session_date=2026-07-14&telescope=SVBony+80ED"
        )
    app.dependency_overrides.clear()
    assert [s["telescope"] for s in resp.json()["sessions"]] == ["SVBony SV503 80mm"]


@pytest.mark.asyncio
async def test_frames_endpoint_requires_authentication():
    """Auth is declared per endpoint by project design, so each route needs its
    own negative test: nothing else would notice a missing dependency."""
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/phd2/sessions/{uuid.uuid4()}/frames")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_frames_endpoint_converts_pixels_to_arcsec_and_returns_events():
    session_id = uuid.uuid4()
    parent = SimpleNamespace(
        pixel_scale_arcsec=2.0,
        started_at_utc=datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc),
        events=[{"type": "dither", "t": 7.381, "detail": "3.4, -1.2"}],
    )
    frames = [
        SimpleNamespace(
            time_offset=1.228, ra_raw=0.5, dec_raw=-0.25,
            ra_duration_ms=98, ra_direction="W",
            dec_duration_ms=0, dec_direction="",
            snr=28.59, star_mass=1713.0, dropped=False,
        ),
        SimpleNamespace(
            time_offset=2.093, ra_raw=None, dec_raw=None,
            ra_duration_ms=0, ra_direction="",
            dec_duration_ms=0, dec_direction="",
            snr=19.23, star_mass=929.0, dropped=True,
        ),
    ]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result_with(scalar_one=parent),
        _result_with(scalars_all=frames),
    ])
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/phd2/sessions/{session_id}/frames")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"pixel_scale_arcsec", "started_at", "frames", "events"}
    assert body["pixel_scale_arcsec"] == 2.0
    first = body["frames"][0]
    assert set(first) == {
        "t", "ra", "dec", "ra_pulse_ms", "ra_dir", "dec_pulse_ms", "dec_dir",
        "snr", "mass", "dropped",
    }
    assert first["t"] == 1.228
    assert first["ra"] == 1.0     # 0.5 px * 2.0 arcsec/px
    assert first["dec"] == -0.5
    assert first["ra_pulse_ms"] == 98
    assert first["ra_dir"] == "W"
    assert body["frames"][1]["ra"] is None
    assert body["frames"][1]["dropped"] is True
    assert body["events"] == [{"type": "dither", "t": 7.381, "detail": "3.4, -1.2"}]


@pytest.mark.asyncio
async def test_frames_endpoint_404s_for_an_unknown_session():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result_with(scalar_one=None))
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/phd2/sessions/{uuid.uuid4()}/frames")
    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_profiles_endpoint_reports_helper_metadata_and_mapping():
    rows = [(
        "AM5n_OAG_ASI174M", "ZWO ASI174MM Mini", 784.0, 1.54,
        412, date(2026, 1, 14), date(2026, 7, 14),
    )]
    settings_row = SimpleNamespace(
        general={"phd2_profile_map": {"AM5n_OAG_ASI174M": "140APO"}}
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        _result_with(all_rows=rows),
        _result_with(scalar_one=settings_row),
    ])
    app.dependency_overrides[get_session] = _override_session(db)
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/phd2/profiles")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"profiles"}
    p = body["profiles"][0]
    assert set(p) == {
        "name", "guide_camera", "focal_length_mm", "pixel_scale_arcsec",
        "session_count", "first_seen", "last_seen", "mapped_telescope",
    }
    assert p["name"] == "AM5n_OAG_ASI174M"
    assert p["guide_camera"] == "ZWO ASI174MM Mini"
    assert p["session_count"] == 412
    assert p["first_seen"] == "2026-01-14"
    assert p["mapped_telescope"] == "140APO"


@pytest.mark.asyncio
async def test_profiles_endpoint_maps_a_legacy_and_an_object_map_alike():
    """`phd2_profile_map` is stored as `{"Rig A": "Askar 120"}` on installs
    that predate per-rig timezones and as `{"Rig A": {"telescope": ...,
    "timezone": ..., "latitude": ..., "longitude": ...}}` on ones that have
    saved through the settings panel since. Both must resolve `mapped_telescope`
    to the same plain string; routing the object form straight into the
    response field used to put a dict into a `str | None` and 500."""
    rows = [(
        "AM5n_OAG_ASI174M", "ZWO ASI174MM Mini", 784.0, 1.54,
        412, date(2026, 1, 14), date(2026, 7, 14),
    )]

    async def _profiles_body(stored_map):
        settings_row = SimpleNamespace(general={"phd2_profile_map": stored_map})
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _result_with(all_rows=rows),
            _result_with(scalar_one=settings_row),
        ])
        app.dependency_overrides[get_session] = _override_session(db)
        app.dependency_overrides[get_current_user] = _override_user(_admin_user())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/phd2/profiles")
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        return resp.json()

    legacy_body = await _profiles_body({"AM5n_OAG_ASI174M": "140APO"})
    object_body = await _profiles_body({
        "AM5n_OAG_ASI174M": {
            "telescope": "140APO",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        }
    })
    assert legacy_body == object_body
    assert legacy_body["profiles"][0]["mapped_telescope"] == "140APO"


@pytest.mark.asyncio
async def test_profiles_endpoint_requires_authentication():
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/phd2/profiles")
    assert resp.status_code == 401
