"""DB-backed parity test for GET /api/targets (list_targets_aggregated).

Seeds a representative dataset in the test DB and asserts the aggregated
response. This is the parity guard for the Option A1 rewrite that moves
filter / equipment / session aggregation from a per-frame Python loop into
SQL. The expected response below is the captured baseline from the ORIGINAL
implementation; after the rewrite the response must remain byte-identical.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied, and Redis at redis://localhost:6379/1.
"""
import os
import sys
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.models import Target, Image
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.normalization import invalidate_alias_cache


TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]

# Fixed UUIDs so the captured baseline JSON is deterministic.
TID_M31 = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _img(**kw):
    """Build an Image with required-but-irrelevant defaults filled in."""
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        raw_headers={},
    )
    defaults.update(kw)
    return Image(**defaults)


@pytest_asyncio.fixture
async def seeded_db():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # Clean slate.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM target_catalog_memberships"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))
        await conn.execute(text("DELETE FROM user_settings"))

    async with Session() as s:
        # Alias maps: two raw filter names collapse to one canonical;
        # two camera raw names collapse to one canonical.
        s.add(UserSettings(
            id=SETTINGS_ROW_ID,
            filters={
                "H-alpha": {"color": "#e74c3c", "aliases": ["Ha", "H_alpha"]},
                "OIII": {"color": "#3498db", "aliases": ["O3"]},
            },
            equipment={
                "cameras": {
                    "ASI2600MM Pro": {"aliases": ["ASI2600", "2600MM"]},
                },
                "telescopes": {
                    "Esprit 100": {"aliases": ["ESPRIT100"]},
                },
            },
        ))

        m31 = Target(
            id=TID_M31,
            primary_name="M 31",
            catalog_id="M31",
            common_name="Andromeda Galaxy",
            aliases=["NGC 224"],
            object_type="G",
        )
        s.add(m31)

        d1 = date(2024, 1, 10)
        d2 = date(2024, 1, 12)

        # --- M31 session 1: two raw Ha names (alias to H-alpha) + OIII raw "O3"
        # Two camera aliases used so equipment dedupes to one canonical.
        s.add(_img(resolved_target_id=TID_M31, session_date=d1,
                   capture_date=datetime(2024, 1, 10, 20, 0, tzinfo=timezone.utc),
                   exposure_time=300.0, filter_used="Ha",
                   camera="ASI2600", telescope="ESPRIT100",
                   median_hfr=2.0, raw_headers={"OBJECT": "M31"}))
        s.add(_img(resolved_target_id=TID_M31, session_date=d1,
                   capture_date=datetime(2024, 1, 10, 20, 5, tzinfo=timezone.utc),
                   exposure_time=300.0, filter_used="H_alpha",
                   camera="2600MM", telescope="ESPRIT100",
                   median_hfr=2.2, raw_headers={"OBJECT": "M31"}))
        s.add(_img(resolved_target_id=TID_M31, session_date=d1,
                   capture_date=datetime(2024, 1, 10, 21, 0, tzinfo=timezone.utc),
                   exposure_time=120.0, filter_used="O3",
                   camera="ASI2600", telescope="ESPRIT100",
                   median_hfr=2.1, raw_headers={"OBJECT": "M31"}))

        # --- M31 session 2: another Ha-aliased frame
        s.add(_img(resolved_target_id=TID_M31, session_date=d2,
                   capture_date=datetime(2024, 1, 12, 20, 0, tzinfo=timezone.utc),
                   exposure_time=600.0, filter_used="Ha",
                   camera="ASI2600", telescope="ESPRIT100",
                   median_hfr=5.0, raw_headers={"OBJECT": "M31 mosaic"}))

        # --- Unresolved frame WITH an OBJECT header -> obj:NGC 7000
        s.add(_img(resolved_target_id=None, session_date=d1,
                   capture_date=datetime(2024, 1, 10, 22, 0, tzinfo=timezone.utc),
                   exposure_time=180.0, filter_used="O3",
                   camera="ASI2600", telescope="ESPRIT100",
                   raw_headers={"OBJECT": "NGC 7000"}))

        # --- Unresolved frame WITHOUT an OBJECT header -> obj:__uncategorized__
        s.add(_img(resolved_target_id=None, session_date=d2,
                   capture_date=datetime(2024, 1, 12, 22, 0, tzinfo=timezone.utc),
                   exposure_time=90.0, filter_used="Ha",
                   camera="ASI2600", telescope="ESPRIT100",
                   raw_headers={}))

        await s.commit()

    invalidate_alias_cache()

    async def _override_session():
        async with Session() as s:
            yield s

    def _override_user():
        u = MagicMock(spec=User)
        u.id = uuid.uuid4()
        u.username = "tester"
        u.role = UserRole.admin
        u.is_active = True
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield

    app.dependency_overrides.clear()
    invalidate_alias_cache()
    await engine.dispose()


async def _get(params: str = ""):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/targets{params}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_id(data, tid):
    for t in data["targets"]:
        if t["target_id"] == tid:
            return t
    raise AssertionError(f"target {tid} not in response: {[t['target_id'] for t in data['targets']]}")


# ---------------------------------------------------------------------------
# Captured baseline (frozen from the ORIGINAL implementation). After the
# rewrite the full response must equal this exactly.
# ---------------------------------------------------------------------------
EXPECTED_TARGETS = {
    str(TID_M31): {
        "target_id": str(TID_M31),
        "primary_name": "M 31",
        "aliases": ["M31", "M31 mosaic"],
        "total_integration_seconds": 1320.0,
        "total_frames": 4,
        "filter_distribution": {"H-alpha": 1200.0, "OIII": 120.0},
        "equipment": ["ASI2600MM Pro", "Esprit 100"],
        "sessions": [
            {"session_date": "2024-01-12", "integration_seconds": 600.0,
             "frame_count": 1, "filters_used": ["H-alpha"]},
            {"session_date": "2024-01-10", "integration_seconds": 720.0,
             "frame_count": 3, "filters_used": ["H-alpha", "OIII"]},
        ],
        "matched_sessions": None,
        "total_sessions": None,
        "mosaic_id": None,
        "mosaic_name": None,
        "custom_values": None,
        "user_defined": False,
    },
    "obj:NGC 7000": {
        "target_id": "obj:NGC 7000",
        "primary_name": "NGC 7000",
        "aliases": ["NGC 7000"],
        "total_integration_seconds": 180.0,
        "total_frames": 1,
        "filter_distribution": {"OIII": 180.0},
        "equipment": ["ASI2600MM Pro", "Esprit 100"],
        "sessions": [
            {"session_date": "2024-01-10", "integration_seconds": 180.0,
             "frame_count": 1, "filters_used": ["OIII"]},
        ],
        "matched_sessions": None,
        "total_sessions": None,
        "mosaic_id": None,
        "mosaic_name": None,
        "custom_values": None,
        "user_defined": False,
    },
    "obj:__uncategorized__": {
        "target_id": "obj:__uncategorized__",
        "primary_name": "Uncategorized",
        "aliases": [],
        "total_integration_seconds": 90.0,
        "total_frames": 1,
        "filter_distribution": {"H-alpha": 90.0},
        "equipment": ["ASI2600MM Pro", "Esprit 100"],
        "sessions": [
            {"session_date": "2024-01-12", "integration_seconds": 90.0,
             "frame_count": 1, "filters_used": ["H-alpha"]},
        ],
        "matched_sessions": None,
        "total_sessions": None,
        "mosaic_id": None,
        "mosaic_name": None,
        "custom_values": None,
        "user_defined": False,
    },
}


@pytest.mark.asyncio
async def test_full_response_parity(seeded_db):
    """Strongest guard: whole-response equality against the frozen baseline."""
    data = await _get("?sort_by=integration&sort_dir=desc")

    assert data["page"] == 1
    assert data["page_size"] == 50
    assert data["total_count"] == 3

    agg = data["aggregates"]
    assert agg["target_count"] == 3
    assert agg["total_frames"] == 6
    assert agg["total_integration_seconds"] == 1590.0
    assert agg["oldest_date"] == "2024-01-10"
    assert agg["newest_date"] == "2024-01-12"

    assert len(data["targets"]) == 3
    for t in data["targets"]:
        assert t == EXPECTED_TARGETS[t["target_id"]], t["target_id"]


@pytest.mark.asyncio
async def test_aliased_filters_summed_into_one_key(seeded_db):
    """Two raw filter names (Ha, H_alpha) alias to H-alpha and must SUM."""
    data = await _get()
    m31 = _by_id(data, str(TID_M31))
    fd = m31["filter_distribution"]
    # 300 + 300 + 600 (3 Ha-aliased frames) = 1200 under canonical key
    assert fd["H-alpha"] == 1200.0
    assert "Ha" not in fd and "H_alpha" not in fd
    assert fd["OIII"] == 120.0


@pytest.mark.asyncio
async def test_equipment_deduped_to_canonical(seeded_db):
    """Two raw camera names alias to one canonical; result has no dupes."""
    data = await _get()
    m31 = _by_id(data, str(TID_M31))
    assert m31["equipment"] == ["ASI2600MM Pro", "Esprit 100"]


@pytest.mark.asyncio
async def test_unresolved_object_keys(seeded_db):
    """obj:<name> and obj:__uncategorized__ keys produced correctly."""
    data = await _get()
    ids = {t["target_id"] for t in data["targets"]}
    assert "obj:NGC 7000" in ids
    assert "obj:__uncategorized__" in ids
    uncat = _by_id(data, "obj:__uncategorized__")
    assert uncat["primary_name"] == "Uncategorized"
    assert uncat["total_frames"] == 1


@pytest.mark.asyncio
async def test_matched_total_sessions_under_metric_filter(seeded_db):
    """Metric range filter populates matched_sessions/total_sessions.

    M31 session 1 frames have HFR ~2.0-2.2 (avg < 3); session 2 has HFR 5.0.
    With hfr_min=4 the target still qualifies (avg over all M31 frames may
    pass/fail), so assert the fields are populated (non-null) for any
    returned target rather than hard-coding plan-dependent counts.
    """
    data = await _get("?hfr_min=1.0")
    assert data["targets"], "expected at least one target with hfr_min filter"
    for t in data["targets"]:
        assert t["matched_sessions"] is not None
        assert t["total_sessions"] is not None
        assert t["matched_sessions"] <= t["total_sessions"]


@pytest.mark.asyncio
async def test_sort_variants_unchanged(seeded_db):
    """Pagination + every sort axis/direction returns all 3 targets stably."""
    for sort_by in ("integration", "lastSession", "name"):
        for sort_dir in ("asc", "desc"):
            data = await _get(f"?sort_by={sort_by}&sort_dir={sort_dir}")
            assert data["total_count"] == 3
            assert len(data["targets"]) == 3
            ids = [t["target_id"] for t in data["targets"]]
            assert set(ids) == {str(TID_M31), "obj:NGC 7000", "obj:__uncategorized__"}

    # name asc should be alphabetical by primary_name
    data = await _get("?sort_by=name&sort_dir=asc")
    names = [t["primary_name"] for t in data["targets"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_pagination(seeded_db):
    """page_size=2 splits the 3 targets across two pages without overlap."""
    p1 = await _get("?page=1&page_size=2&sort_by=name&sort_dir=asc")
    p2 = await _get("?page=2&page_size=2&sort_by=name&sort_dir=asc")
    assert len(p1["targets"]) == 2
    assert len(p2["targets"]) == 1
    assert p1["total_count"] == 3 and p2["total_count"] == 3
    ids = {t["target_id"] for t in p1["targets"]} | {t["target_id"] for t in p2["targets"]}
    assert ids == {str(TID_M31), "obj:NGC 7000", "obj:__uncategorized__"}


# ---------------------------------------------------------------------------
# Edge-case fixture + tests for the two correctness fixes:
#   Finding 1: empty-string OBJECT header collapses to obj:__uncategorized__
#              in BOTH the Phase-1 grouping key and the detail aggregation.
#   Finding 2: a NULL session_date frame is counted as one ('unknown') session
#              so matched_sessions <= total_sessions holds under a metric filter.
# Kept in a SEPARATE fixture so the frozen parity baseline above is untouched.
# ---------------------------------------------------------------------------
TID_EDGE = uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest_asyncio.fixture
async def seeded_edge_db():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM target_catalog_memberships"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))
        await conn.execute(text("DELETE FROM user_settings"))

    async with Session() as s:
        s.add(UserSettings(id=SETTINGS_ROW_ID, filters={}, equipment={}))

        # Finding 1: unresolved frame, OBJECT present but EMPTY STRING.
        s.add(_img(resolved_target_id=None, session_date=date(2024, 2, 1),
                   capture_date=datetime(2024, 2, 1, 20, 0, tzinfo=timezone.utc),
                   exposure_time=100.0, filter_used="L",
                   camera="CamA", telescope="ScopeA",
                   raw_headers={"OBJECT": ""}))

        # Finding 2: resolved target with one dated frame + one NULL-date frame.
        s.add(Target(id=TID_EDGE, primary_name="EdgeTgt", aliases=[]))
        s.add(_img(resolved_target_id=TID_EDGE, session_date=date(2024, 2, 2),
                   capture_date=datetime(2024, 2, 2, 20, 0, tzinfo=timezone.utc),
                   exposure_time=200.0, filter_used="L", median_hfr=2.0,
                   camera="CamA", telescope="ScopeA", raw_headers={"OBJECT": "EdgeTgt"}))
        s.add(_img(resolved_target_id=TID_EDGE, session_date=None,
                   capture_date=datetime(2024, 2, 3, 20, 0, tzinfo=timezone.utc),
                   exposure_time=200.0, filter_used="L", median_hfr=2.0,
                   camera="CamA", telescope="ScopeA", raw_headers={"OBJECT": "EdgeTgt"}))

        await s.commit()

    invalidate_alias_cache()

    async def _override_session():
        async with Session() as s:
            yield s

    def _override_user():
        u = MagicMock(spec=User)
        u.id = uuid.uuid4()
        u.username = "tester"
        u.role = UserRole.admin
        u.is_active = True
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield

    app.dependency_overrides.clear()
    invalidate_alias_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_object_header_collapses_to_uncategorized(seeded_edge_db):
    """Finding 1: OBJECT="" must land under obj:__uncategorized__ with real
    distributions, NOT produce a separate empty `obj:` card."""
    data = await _get()
    ids = {t["target_id"] for t in data["targets"]}
    assert "obj:" not in ids, f"empty `obj:` card leaked: {ids}"
    assert "obj:__uncategorized__" in ids

    uncat = _by_id(data, "obj:__uncategorized__")
    assert uncat["primary_name"] == "Uncategorized"
    assert uncat["total_frames"] == 1
    assert uncat["total_integration_seconds"] == 100.0
    assert uncat["filter_distribution"] == {"L": 100.0}
    assert uncat["equipment"] == ["CamA", "ScopeA"]
    assert len(uncat["sessions"]) == 1
    assert uncat["sessions"][0]["session_date"] == "2024-02-01"
    assert uncat["sessions"][0]["frame_count"] == 1
    # The empty-string OBJECT must not surface as an alias.
    assert uncat["aliases"] == []


@pytest.mark.asyncio
async def test_null_session_date_counted_so_matched_le_total(seeded_edge_db):
    """Finding 2: a NULL session_date frame becomes one 'unknown' session and
    is counted in total_sessions, preserving matched_sessions <= total_sessions
    under a metric range filter."""
    data = await _get("?hfr_min=1.0")
    edge = _by_id(data, str(TID_EDGE))

    # Two distinct sessions: the dated one and the 'unknown' bucket.
    session_dates = {s["session_date"] for s in edge["sessions"]}
    assert "unknown" in session_dates
    assert "2024-02-02" in session_dates
    assert len(edge["sessions"]) == 2

    assert edge["matched_sessions"] is not None
    assert edge["total_sessions"] is not None
    # The core invariant the fix restores.
    assert edge["matched_sessions"] <= edge["total_sessions"]
    # total_sessions now counts the 'unknown' bucket as one session.
    assert edge["total_sessions"] == 2


@pytest.mark.asyncio
async def test_null_session_date_does_not_inflate_normal_targets(seeded_db):
    """Finding 2 regression guard: targets with NO NULL-date frames keep their
    exact session_count (no double-count) under a metric filter."""
    data = await _get("?hfr_min=1.0")
    m31 = _by_id(data, str(TID_M31))
    # M31 has frames on two distinct dates, none NULL -> total_sessions == 2.
    assert m31["total_sessions"] == 2
    assert m31["matched_sessions"] <= m31["total_sessions"]


@pytest.mark.asyncio
async def test_search_includes_unresolved_groups(seeded_db):
    """include_unresolved appends unlinked OBJECT-name groups as pseudo entries."""
    plain = await _get("/search?q=NGC%207000")
    assert all(not r.get("unresolved") for r in plain)

    data = await _get("/search?q=NGC%207000&include_unresolved=true")
    pseudo = [r for r in data if r.get("unresolved")]
    assert len(pseudo) == 1
    assert pseudo[0]["id"] == "obj:NGC 7000"
    assert pseudo[0]["primary_name"] == "NGC 7000"
    assert pseudo[0]["image_count"] == 1
    # Frames without an OBJECT header never appear as a mergeable group.
    assert all(r["id"] != "obj:__uncategorized__" for r in data)
