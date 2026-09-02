"""DB-backed tests for the public /api/v1 bearer-key API and its admin keys.

Covers four separately-built pieces:
  * api_keys table + services.api_keys (create / verify / revoke)
  * /api/apikeys admin endpoints (cookie session, admin only)
  * /api/v1 public router (Authorization: Bearer glg_..., router-level)
  * POST /api/v1/scan started / queued semantics

Requires the throwaway Postgres from CLAUDE.md
(test:test@localhost:5432/test_catalog) with `alembic upgrade head` applied,
including the api_keys revision.

The auth dependencies are deliberately NOT overridden: these tests drive the
real header parsing and the real key lookup, which is the only way the leak
and permission regressions can be caught.
"""
import importlib
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models import Image, Target
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.user import User, UserRole
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.api_keys import create_api_key, revoke_api_key, verify_api_key
from app.services.normalization import invalidate_alias_cache

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]

TID_A = uuid.UUID("aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa")
TID_B = uuid.UUID("bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb")
MID = uuid.UUID("cccccccc-3333-4333-8333-cccccccccccc")

D1 = date(2024, 5, 10)
D2 = date(2024, 5, 11)

SITE_LAT = "33.1"
SITE_LON = "-96.8"

# Internal-only keys that must never appear anywhere in a v1 payload. The
# first four are filesystem / raw-header leaks; matched_sessions is an
# internal filter artifact of the admin targets endpoint.
FORBIDDEN_KEYS = {
    "file_path",
    "source_relative",
    "thumbnail_file_path",
    "raw_reference_header",
    "matched_sessions",
}


def _all_keys(obj, acc=None):
    """Every dict key appearing anywhere in a decoded JSON document."""
    if acc is None:
        acc = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _all_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, acc)
    return acc


def _assert_no_leak(data, where):
    leaked = FORBIDDEN_KEYS & _all_keys(data)
    assert not leaked, f"{where} leaked internal keys: {sorted(leaked)}"


def _img(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        raw_headers={"SITELAT": SITE_LAT, "SITELONG": SITE_LON},
    )
    defaults.update(kw)
    return Image(**defaults)


@pytest_asyncio.fixture
async def v1env():
    """Seed the DB, mint three keys, and point the app at the test session.

    Keys are minted fresh per test so the per-key rate limit (120/min) cannot
    bleed between tests in this file.
    """
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM mosaic_panel_sessions"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM target_catalog_memberships"))
        await conn.execute(text("DELETE FROM session_notes"))
        await conn.execute(text("DELETE FROM targets"))
        await conn.execute(text("DELETE FROM user_settings"))
        await conn.execute(text("DELETE FROM api_keys"))

    async with Session() as s:
        # merge, not add: the settings row is a singleton and app code
        # (bootstrap, activity emit) can recreate it between the DELETE above
        # and here, which made this file order-dependent against other
        # DB-backed fixtures that seed the same row.
        await s.merge(UserSettings(id=SETTINGS_ROW_ID, filters={}, equipment={}, general={}))

        s.add(Target(
            id=TID_A, primary_name="M 42", catalog_id="M42",
            common_name="Orion Nebula", aliases=["NGC 1976"],
            ra=83.822, dec=-5.391, object_type="Neb", notes="original notes",
        ))
        s.add(Target(
            id=TID_B, primary_name="NGC 7000", catalog_id="NGC7000",
            aliases=[], ra=314.7, dec=44.3, object_type="Neb",
        ))

        for i, (d, hfr, fw) in enumerate([
            (D1, 2.0, 1.8), (D1, 2.2, 1.9), (D1, 2.1, 2.0), (D2, 3.0, 2.6),
        ]):
            s.add(_img(
                resolved_target_id=TID_A, session_date=d,
                capture_date=datetime(d.year, d.month, d.day, 20, i, tzinfo=timezone.utc),
                exposure_time=300.0, filter_used="Ha", camera="ASI2600MM",
                telescope="Esprit 100", median_hfr=hfr, fwhm=fw, eccentricity=0.4,
            ))

        s.add(_img(
            resolved_target_id=TID_B, session_date=D1,
            capture_date=datetime(2024, 5, 10, 23, 0, tzinfo=timezone.utc),
            exposure_time=120.0, filter_used="OIII", camera="ASI2600MM",
            telescope="Esprit 100",
        ))

        # Unresolved frame -> internal endpoints synthesize an "obj:IC 1318"
        # pseudo target. v1 must never surface those.
        s.add(_img(
            resolved_target_id=None, session_date=D2,
            capture_date=datetime(2024, 5, 11, 22, 0, tzinfo=timezone.utc),
            exposure_time=60.0, filter_used="Ha", camera="ASI2600MM",
            telescope="Esprit 100",
            raw_headers={"OBJECT": "IC 1318", "SITELAT": SITE_LAT, "SITELONG": SITE_LON},
        ))

        s.add(Mosaic(id=MID, name="Cygnus Wall"))
        await s.flush()
        s.add(MosaicPanel(mosaic_id=MID, target_id=TID_B, panel_label="Panel 1", sort_order=0))

        await s.commit()

    async with Session() as s:
        _, read_raw = await create_api_key(s, "read", can_write=False)
        _, write_raw = await create_api_key(s, "write", can_write=True)
        revoked, revoked_raw = await create_api_key(s, "revoked", can_write=True)
        await revoke_api_key(s, revoked.id)

    invalidate_alias_cache()

    async def _override_session():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session

    yield SimpleNamespace(
        read=read_raw, write=write_raw, revoked=revoked_raw,
        Session=Session, target=str(TID_A), target_b=str(TID_B), mosaic=str(MID),
    )

    app.dependency_overrides.clear()
    invalidate_alias_cache()
    await engine.dispose()


async def _call(method, path, key=None, **kw):
    headers = kw.pop("headers", {})
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kw)


async def _get_ok(path, key):
    resp = await _call("GET", path, key)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Bearer-key authentication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_authorization_header_is_401(v1env):
    resp = await _call("GET", "/api/v1/targets")
    assert resp.status_code == 401, resp.text
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


@pytest.mark.asyncio
async def test_bogus_key_is_401(v1env):
    resp = await _call("GET", "/api/v1/targets", "glg_" + "0" * 40)
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_non_bearer_scheme_is_401(v1env):
    resp = await _call("GET", "/api/v1/targets", headers={"Authorization": f"Basic {v1env.read}"})
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_revoked_key_is_401(v1env):
    resp = await _call("GET", "/api/v1/targets", v1env.revoked)
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_read_key_allowed_on_read(v1env):
    data = await _get_ok("/api/v1/targets", v1env.read)
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_read_key_forbidden_on_action(v1env):
    resp = await _call("PUT", f"/api/v1/targets/{v1env.target}/notes",
                       v1env.read, json={"notes": "nope"})
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_key_shape_and_service_verify(v1env):
    """create_api_key hands back glg_ + 40 hex; verify accepts it, rejects the
    revoked one and an unknown one."""
    assert v1env.read.startswith("glg_")
    assert len(v1env.read) == 44
    int(v1env.read[4:], 16)  # raises if not hex

    async with v1env.Session() as s:
        assert await verify_api_key(s, v1env.read) is not None
        assert await verify_api_key(s, v1env.revoked) is None
        assert await verify_api_key(s, "glg_" + "f" * 40) is None


# ---------------------------------------------------------------------------
# /api/apikeys admin endpoints (cookie session, admin only)
# ---------------------------------------------------------------------------

def _as_admin():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "admin"
    u.role = UserRole.admin
    u.is_active = True
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[require_admin] = lambda: u
    return u


@pytest.mark.asyncio
async def test_admin_create_returns_raw_key_once(v1env):
    _as_admin()
    resp = await _call("POST", "/api/apikeys", json={"name": "ci", "can_write": True})
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()

    raw = body["key"]
    assert raw.startswith("glg_") and len(raw) == 44
    assert body["prefix"] == raw[:12]
    assert "key_hash" not in body

    # The raw key really authenticates against v1, and its write bit holds.
    del app.dependency_overrides[get_current_user]
    del app.dependency_overrides[require_admin]
    assert (await _call("GET", "/api/v1/targets", raw)).status_code == 200


@pytest.mark.asyncio
async def test_admin_list_never_exposes_hash_or_raw_key(v1env):
    _as_admin()
    rows = await _get_ok("/api/apikeys", None)
    assert len(rows) >= 3
    for row in rows:
        assert "key_hash" not in row
        assert "key" not in row
        assert row["prefix"].startswith("glg_")


@pytest.mark.asyncio
async def test_admin_delete_revokes_key(v1env):
    _as_admin()
    created = (await _call("POST", "/api/apikeys", json={"name": "temp"})).json()
    raw, key_id = created["key"], created["id"]

    resp = await _call("DELETE", f"/api/apikeys/{key_id}")
    assert resp.status_code in (200, 204), resp.text

    rows = await _get_ok("/api/apikeys", None)
    row = next(r for r in rows if r["id"] == key_id)
    assert row["revoked_at"] is not None

    del app.dependency_overrides[get_current_user]
    del app.dependency_overrides[require_admin]
    assert (await _call("GET", "/api/v1/targets", raw)).status_code == 401


@pytest.mark.asyncio
async def test_admin_delete_unknown_key_is_404(v1env):
    _as_admin()
    resp = await _call("DELETE", f"/api/apikeys/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_admin_permanent_delete_revoked_key(v1env):
    _as_admin()
    created = (await _call("POST", "/api/apikeys", json={"name": "doomed"})).json()
    key_id = created["id"]
    assert (await _call("DELETE", f"/api/apikeys/{key_id}")).status_code == 204

    resp = await _call("DELETE", f"/api/apikeys/{key_id}/permanent")
    assert resp.status_code == 204, resp.text

    rows = await _get_ok("/api/apikeys", None)
    assert all(r["id"] != key_id for r in rows)


@pytest.mark.asyncio
async def test_admin_permanent_delete_active_key_is_409(v1env):
    _as_admin()
    created = (await _call("POST", "/api/apikeys", json={"name": "alive"})).json()
    key_id = created["id"]

    resp = await _call("DELETE", f"/api/apikeys/{key_id}/permanent")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Revoke the key first"

    rows = await _get_ok("/api/apikeys", None)
    assert any(r["id"] == key_id for r in rows)


@pytest.mark.asyncio
async def test_admin_permanent_delete_unknown_key_is_404(v1env):
    _as_admin()
    resp = await _call("DELETE", f"/api/apikeys/{uuid.uuid4()}/permanent")
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Read shapes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_targets_list_shape_and_pagination(v1env):
    data = await _get_ok("/api/v1/targets", v1env.read)
    assert set(["items", "page", "page_size", "total"]) <= set(data)
    # Only real targets are listable; the unresolved "obj:IC 1318" group is not.
    assert [t["name"] for t in data["items"]] and all(
        not str(t["id"]).startswith("obj:") for t in data["items"]
    ), data["items"]
    # `total` drives the client's page loop, so it must count what is listable.
    # Two real targets are seeded plus one unresolved OBJECT group.
    assert data["total"] == 2, data
    entry = next(t for t in data["items"] if t["name"] == "M 42")
    assert entry["other_names"] == ["NGC 1976"] or "NGC 1976" in entry["other_names"]
    assert entry["position"]["ra"] == pytest.approx(83.822)
    assert entry["position"]["dec"] == pytest.approx(-5.391)
    assert entry["total_integration_seconds"] == pytest.approx(1200.0)
    assert entry["total_frames"] == 4

    page = await _get_ok("/api/v1/targets?page=1&page_size=1", v1env.read)
    assert len(page["items"]) == 1
    assert page["page"] == 1 and page["page_size"] == 1 and page["total"] == 2


@pytest.mark.asyncio
async def test_no_internal_keys_leak_anywhere(v1env):
    """The leak regression: no filesystem or internal key in any v1 payload.

    Every JSON route is swept, not just the hand-picked ones: the routes that
    pass an internal model through are exactly the ones that grow a path field
    later, and nobody remembers to add the new route here.
    """
    for path in (
        "/api/v1/targets",
        f"/api/v1/targets/{v1env.target}",
        f"/api/v1/targets/{v1env.target}/sessions",
        f"/api/v1/targets/{v1env.target}/sessions/2024-05-10",
        f"/api/v1/targets/{v1env.target}/frames",
        f"/api/v1/targets/{v1env.target}/export",
        "/api/v1/search?q=M%2042",
        "/api/v1/nights?year=2024",
        "/api/v1/stats",
        "/api/v1/guiding",
        "/api/v1/mosaics",
        f"/api/v1/mosaics/{v1env.mosaic}",
        "/api/v1/scan/status",
    ):
        data = await _get_ok(path, v1env.read)
        # An empty payload would pass the key check vacuously.
        assert data not in ({}, [], None), f"{path} returned nothing to sweep"
        _assert_no_leak(data, path)


@pytest.mark.asyncio
async def test_thumbnail_serves_an_image_not_a_path(v1env):
    """The thumbnail route returns bytes; the sweep above cannot read it, so
    check it hands back an image (or 404s) rather than a filesystem path."""
    resp = await _call("GET", f"/api/v1/targets/{v1env.target}/thumbnail", v1env.read)
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        assert resp.headers["content-type"].startswith("image/"), resp.headers
    else:
        _assert_no_leak(resp.json(), "thumbnail 404 body")


@pytest.mark.asyncio
async def test_target_detail(v1env):
    data = await _get_ok(f"/api/v1/targets/{v1env.target}", v1env.read)
    assert data["name"] == "M 42"
    assert data["total_frames"] == 4


@pytest.mark.asyncio
async def test_session_detail_has_no_frames_array(v1env):
    data = await _get_ok(f"/api/v1/targets/{v1env.target}/sessions/2024-05-10", v1env.read)
    # A per-filter `frames` COUNT is fine; an embedded array of frame rows is
    # not - that is what /targets/{id}/frames is for.
    assert not isinstance(data.get("frames"), list), data
    assert data["date"] == "2024-05-10"


@pytest.mark.asyncio
async def test_frames_endpoint_rows_and_pagination(v1env):
    data = await _get_ok(f"/api/v1/targets/{v1env.target}/frames", v1env.read)
    assert data["total"] == 4
    row = data["items"][0]
    # FWHM is stored in arcsec and named so; HFR is in pixels.
    assert "fwhm_arcsec" in row and "hfr" in row, sorted(row)
    assert any(r["fwhm_arcsec"] is not None for r in data["items"])
    assert any(r["hfr"] is not None for r in data["items"])

    page = await _get_ok(f"/api/v1/targets/{v1env.target}/frames?page=2&page_size=3", v1env.read)
    assert page["total"] == 4
    assert len(page["items"]) == 1


@pytest.mark.asyncio
async def test_search_excludes_pseudo_object_ids(v1env):
    for q in ("IC", "IC%201318", "M%2042"):
        results = await _get_ok(f"/api/v1/search?q={q}", v1env.read)
        rows = results["items"] if isinstance(results, dict) else results
        for r in rows:
            assert not str(r.get("id", "")).startswith("obj:"), r

    results = await _get_ok("/api/v1/search?q=M%2042", v1env.read)
    rows = results["items"] if isinstance(results, dict) else results
    assert any(r.get("name") == "M 42" or r.get("primary_name") == "M 42" for r in rows), rows


@pytest.mark.asyncio
async def test_nights_returns_calendar_entries(v1env):
    # Without ?year the calendar window is the last 365 days, so the seeded
    # 2024 nights only appear when the year is asked for.
    assert isinstance(await _get_ok("/api/v1/nights", v1env.read), list)

    rows = await _get_ok("/api/v1/nights?year=2024", v1env.read)
    dates = {r["date"] for r in rows}
    assert "2024-05-10" in dates and "2024-05-11" in dates, dates
    night = next(r for r in rows if r["date"] == "2024-05-10")
    assert night["frames"] == 4  # 3 on M 42 + 1 on NGC 7000
    assert night["integration_seconds"] == pytest.approx(1020.0)


@pytest.mark.asyncio
async def test_stats_has_site_coords_and_no_storage(v1env):
    data = await _get_ok("/api/v1/stats", v1env.read)
    site = data.get("site")
    assert site is not None, sorted(data)
    assert site["latitude"] == pytest.approx(float(SITE_LAT))
    assert site["longitude"] == pytest.approx(float(SITE_LON))
    assert data["totals"]["frames"] == 6
    for internal in ("storage", "ingest_history", "total_size_bytes"):
        assert internal not in _all_keys(data), f"v1 /stats must not expose {internal}"


@pytest.mark.asyncio
async def test_mosaic_detail(v1env):
    data = await _get_ok(f"/api/v1/mosaics/{v1env.mosaic}", v1env.read)
    assert data["name"] == "Cygnus Wall"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_key_updates_notes(v1env):
    resp = await _call("PUT", f"/api/v1/targets/{v1env.target}/notes",
                       v1env.write, json={"notes": "seen from the driveway"})
    assert resp.status_code in (200, 204), resp.text

    detail = await _get_ok(f"/api/v1/targets/{v1env.target}", v1env.read)
    assert detail["notes"] == "seen from the driveway"


# ---------------------------------------------------------------------------
# 404s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_target_is_404(v1env):
    missing = uuid.uuid4()
    assert (await _call("GET", f"/api/v1/targets/{missing}", v1env.read)).status_code == 404
    assert (await _call("GET", f"/api/v1/targets/{missing}/frames", v1env.read)).status_code == 404
    resp = await _call("PUT", f"/api/v1/targets/{missing}/notes", v1env.write, json={"notes": "x"})
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_pseudo_object_id_is_404(v1env):
    resp = await _call("GET", "/api/v1/targets/obj:IC%201318", v1env.read)
    assert resp.status_code in (404, 422), resp.text


# ---------------------------------------------------------------------------
# POST /api/v1/scan: started vs queued
# ---------------------------------------------------------------------------

def _redis_cm(mock_redis):
    @asynccontextmanager
    async def _ctx():
        yield mock_redis
    return _ctx


def _fake_redis(state):
    r = AsyncMock()
    r.hgetall = AsyncMock(return_value=state)
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.setex = AsyncMock()
    r.hset = AsyncMock()
    r.persist = AsyncMock()
    r.expire = AsyncMock()
    r.delete = AsyncMock()
    r.exists = AsyncMock(return_value=0)
    r.lrange = AsyncMock(return_value=[])
    return r


def _running_state():
    import time
    return {
        "state": "ingesting", "total": "50", "completed": "10", "failed": "0",
        "started_at": str(time.time()), "completed_at": "",
    }


@pytest.mark.asyncio
async def test_scan_idle_returns_started(v1env):
    redis = _fake_redis({})
    with patch("app.config.async_redis") as cm:
        cm.side_effect = _redis_cm(redis)
        resp = await _call("POST", "/api/v1/scan", v1env.write)

    assert resp.status_code in (200, 202), resp.text
    assert resp.json()["status"] == "started"


@pytest.mark.asyncio
async def test_scan_running_returns_queued(v1env):
    redis = _fake_redis(_running_state())
    import time
    redis.get = AsyncMock(return_value=str(time.time()))  # recent heartbeat
    with patch("app.config.async_redis") as cm:
        cm.side_effect = _redis_cm(redis)
        resp = await _call("POST", "/api/v1/scan", v1env.write)

    assert resp.status_code in (200, 202), resp.text
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_scan_read_key_forbidden(v1env):
    resp = await _call("POST", "/api/v1/scan", v1env.read)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_request_scan_dispatches_when_idle():
    import app.services.scan_state as ss
    redis = _fake_redis({})
    tasks = importlib.import_module("app.worker.tasks")
    tasks.run_scan.delay.reset_mock()

    assert await ss.request_scan(redis) == "started"
    tasks.run_scan.delay.assert_called_once()


@pytest.mark.asyncio
async def test_repeat_requests_collapse_to_one_flag():
    """Two triggers while a scan is running leave exactly ONE pending flag,
    not a queue: the follow-up marker is a set on a single key, never a push."""
    import app.services.scan_state as ss
    import time

    redis = _fake_redis(_running_state())
    redis.get = AsyncMock(return_value=str(time.time()))
    tasks = importlib.import_module("app.worker.tasks")
    tasks.run_scan.delay.reset_mock()

    assert await ss.request_scan(redis) == "queued"
    assert await ss.request_scan(redis) == "queued"

    tasks.run_scan.delay.assert_not_called()
    redis.rpush.assert_not_called()
    redis.lpush.assert_not_called()

    pending = [c for c in redis.set.await_args_list if c.args[0] == ss.SCAN_PENDING_KEY]
    assert len(pending) == 2, "both requests should write the pending marker"
    assert {c.args[0] for c in pending} == {ss.SCAN_PENDING_KEY}, "pending marker must be one fixed key"


# ---------------------------------------------------------------------------
# The v1 sub-application: its own OpenAPI document and Swagger UI
#
# /api/v1 is a mounted FastAPI app rather than a router under /api, so it can
# publish a spec covering only the public surface. These tests pin the two
# things that mount buys (a v1-only spec, a Swagger UI that can authorize) and
# the three it must not break (unchanged paths, one auth pass per request, a
# real client address reaching the rate limiter).
# ---------------------------------------------------------------------------

V1_PATHS = {
    "/guiding",
    "/mosaics",
    "/mosaics/{mosaic_id}",
    "/nights",
    "/scan",
    "/scan/status",
    "/search",
    "/stats",
    "/targets",
    "/targets/{target_id}",
    "/targets/{target_id}/export",
    "/targets/{target_id}/frames",
    "/targets/{target_id}/notes",
    "/targets/{target_id}/point/nina",
    "/targets/{target_id}/point/stellarium",
    "/targets/{target_id}/sessions",
    "/targets/{target_id}/sessions/{date}",
    "/targets/{target_id}/sessions/{date}/notes",
    "/targets/{target_id}/thumbnail",
}


@pytest.mark.asyncio
async def test_v1_openapi_lists_only_v1_routes():
    """The spec is the public contract: 19 projected routes and nothing from
    the internal API. A leak here is a leak of the admin surface's shape."""
    resp = await _call("GET", "/api/v1/openapi.json")
    assert resp.status_code == 200, resp.text
    spec = resp.json()

    assert spec["info"]["title"] == "GalactiLog API v1"
    assert set(spec["paths"]) == V1_PATHS

    # Named because these are the routes most likely to be dragged in by a
    # regression that re-includes the internal router into the sub-app.
    joined = " ".join(spec["paths"])
    for internal in ("auth", "login", "settings", "apikeys", "bootstrap",
                     "activity", "logs", "backup", "custom-columns",
                     "merges", "wbpp", "phd2", "analysis", "preview"):
        assert internal not in joined, f"internal surface {internal!r} in v1 spec"

    # /api/v1/scan is the public trigger; the admin scan routes (stop, reset,
    # progress, activity) must not have come along with it.
    assert {m.lower() for m in spec["paths"]["/scan"]} == {"post"}
    assert {m.lower() for m in spec["paths"]["/scan/status"]} == {"get"}


@pytest.mark.asyncio
async def test_v1_openapi_servers_resolve_to_api_v1(v1env):
    """Paths are prefix-free and `servers` carries the mount point, so
    server + path is the URL that actually answers - which is what Swagger's
    try-out and any generated client will call."""
    spec = (await _call("GET", "/api/v1/openapi.json")).json()

    assert spec["servers"][0]["url"] == "/api/v1"
    assert all(not p.startswith("/api") for p in spec["paths"])

    base = spec["servers"][0]["url"]
    assert (await _call("GET", base + "/targets", v1env.read)).status_code == 200
    assert (await _call("GET", base + "/stats", v1env.read)).status_code == 200


@pytest.mark.asyncio
async def test_v1_openapi_declares_bearer_scheme_on_every_route():
    """Without a declared scheme Swagger has no Authorize button and the docs
    are read-only. Every operation must reference it, not just some."""
    spec = (await _call("GET", "/api/v1/openapi.json")).json()

    schemes = spec["components"]["securitySchemes"]
    assert schemes["HTTPBearer"]["type"] == "http"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"

    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("security") == [{"HTTPBearer": []}], f"{method} {path}"


@pytest.mark.asyncio
async def test_v1_docs_serves_swagger_pointing_at_the_v1_spec():
    resp = await _call("GET", "/api/v1/docs")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert "/api/v1/openapi.json" in resp.text


@pytest.mark.asyncio
async def test_v1_docs_and_spec_are_reachable_without_a_key():
    """Swagger has to load before anyone can paste a key into it, so the two
    doc routes are the only unauthenticated things under /api/v1 - and the
    data routes next to them are still shut."""
    assert (await _call("GET", "/api/v1/docs")).status_code == 200
    assert (await _call("GET", "/api/v1/openapi.json")).status_code == 200
    assert (await _call("GET", "/api/v1/targets")).status_code == 401
    assert (await _call("GET", "/api/v1/stats")).status_code == 401


@pytest.mark.asyncio
async def test_mount_does_not_double_apply_the_key_dependency(v1env):
    """require_write_key resolves through require_read_key, and FastAPI caches
    it per request. Mounting must not re-run it: a second pass would verify
    the key twice and charge the rate limit twice for one call."""
    import app.api.v1.deps as deps

    real = deps.verify_api_key
    calls = []

    async def counting(session, raw):
        calls.append(raw)
        return await real(session, raw)

    with patch.object(deps, "verify_api_key", counting):
        assert (await _call("GET", "/api/v1/targets", v1env.write)).status_code == 200
        assert len(calls) == 1, "read route verified the key more than once"

        calls.clear()
        resp = await _call("PUT", f"/api/v1/targets/{v1env.target}/notes",
                           v1env.write, json={"notes": "once"})
        assert resp.status_code == 200, resp.text
        assert len(calls) == 1, "write route verified the key more than once"


@pytest.mark.asyncio
async def test_client_address_still_reaches_the_rate_limiter_under_the_mount(v1env):
    """The bad-key budget is charged per client address. A mount rewrites the
    request's path and root_path but not its peer or headers, so the address
    the limiter sees must still be the one nginx forwarded."""
    import app.api.v1.deps as deps

    buckets = []

    async def spy(name, limit):
        buckets.append(name)
        return False

    with patch.object(deps, "_count_hit", spy), patch.object(deps, "_is_spent", spy):
        resp = await _call("GET", "/api/v1/targets", "glg_" + "0" * 40,
                           headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
        assert resp.status_code == 401, resp.text

    assert buckets == ["badkey:203.0.113.7", "badkey:203.0.113.7"], buckets
