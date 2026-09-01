"""DB-backed tests for GET /api/targets/search (fuzzy target search).

Written against the search rework spec:
  1. Exact/substring tier with compact normalization (M31 == M 31 == m 31).
  2. No fuzzy padding when an exact hit exists.
  3. A shared word like "nebula" in an alias must not drag unrelated targets
     in when another target matched exactly.
  4. Fuzzy tier (per-name word_similarity, threshold 0.4) fires only when
     nothing exact matched; primary_name is fuzzy-searchable.
  5. Common-name table (Stellarium names.dat + COMMON_NAME_MAP) consulted;
     fragments of 3 chars or fewer must not match via that tier.
  6. Ordering: exact name (1.0) > prefix (0.9) > substring (0.8).
  7. match_source populated on every target hit with the matched text.
  8. "%" and "_" in the query are literal.
  9. limit respected, including with include_unresolved=true.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied (pg_trgm installed by migration 0015).
"""
import os
import sys
import uuid
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


TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]

# Fixed UUIDs so assertions are deterministic.
TID_M31 = uuid.UUID("11111111-1111-4111-8111-111111111111")
TID_SH129 = uuid.UUID("22222222-2222-4222-8222-222222222222")
TID_SH131 = uuid.UUID("22222222-2222-4222-8222-222222222223")
TID_SH188 = uuid.UUID("22222222-2222-4222-8222-222222222224")
TID_N7000 = uuid.UUID("33333333-3333-4333-8333-333333333333")
TID_N7619 = uuid.UUID("33333333-3333-4333-8333-333333333334")
TID_N891 = uuid.UUID("33333333-3333-4333-8333-333333333335")
TID_CAVE = uuid.UUID("44444444-4444-4444-8444-444444444444")
TID_LION = uuid.UUID("44444444-4444-4444-8444-444444444445")
TID_WIZARD = uuid.UUID("44444444-4444-4444-8444-444444444446")
TID_CATS_EYE = uuid.UUID("55555555-5555-4555-8555-555555555555")
TID_BARNARD_LOOP = uuid.UUID("66666666-6666-4666-8666-666666666666")
TID_PELICAN = uuid.UUID("77777777-7777-4777-8777-777777777771")
TID_PELICAN_NEB = uuid.UUID("77777777-7777-4777-8777-777777777772")
TID_BABY_PELICAN = uuid.UUID("77777777-7777-4777-8777-777777777773")


def _img(**kw):
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

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM images"))
        await conn.execute(text("DELETE FROM target_catalog_memberships"))
        await conn.execute(text("DELETE FROM mosaic_panels"))
        await conn.execute(text("DELETE FROM mosaics"))
        await conn.execute(text("DELETE FROM targets"))

    async with Session() as s:
        s.add_all([
            # Spec 1: compact normalization
            Target(id=TID_M31, primary_name="M 31 - Andromeda Galaxy",
                   catalog_id="M 31", common_name="Andromeda Galaxy",
                   aliases=["NGC 224"], object_type="G"),
            Target(id=TID_SH129, primary_name="SH 2-129",
                   catalog_id="Sh2-129", aliases=[], object_type="HII"),
            # Spec 2: no fuzzy padding
            Target(id=TID_SH131, primary_name="SH 2-131", catalog_id="Sh2-131", aliases=[]),
            Target(id=TID_SH188, primary_name="SH 2-188", catalog_id="Sh2-188", aliases=[]),
            Target(id=TID_N7000, primary_name="NGC 7000", catalog_id="NGC 7000", aliases=[]),
            Target(id=TID_N7619, primary_name="NGC 7619", catalog_id="NGC 7619", aliases=[]),
            Target(id=TID_N891, primary_name="NGC 891", catalog_id="NGC 891", aliases=[]),
            # Spec 3: shared "NEBULA" word across aliases
            Target(id=TID_CAVE, primary_name="SH 2-155", catalog_id="Sh2-155",
                   aliases=["CAVE NEBULA"]),
            Target(id=TID_LION, primary_name="SH 2-132", catalog_id="Sh2-132",
                   aliases=["LION NEBULA"]),
            Target(id=TID_WIZARD, primary_name="NGC 7380", catalog_id="NGC 7380",
                   aliases=["WIZARD NEBULA"]),
            # Spec 5: common-name map targets, no colloquial text in any name
            Target(id=TID_CATS_EYE, primary_name="NGC 6543", catalog_id="NGC 6543", aliases=[]),
            # Spec 4: ONLY primary_name, no catalog_id / common_name / aliases
            Target(id=TID_BARNARD_LOOP, primary_name="Barnard Loop", aliases=[]),
            # Spec 6: ordering trio
            Target(id=TID_PELICAN, primary_name="Pelican", aliases=[]),
            Target(id=TID_PELICAN_NEB, primary_name="Pelican Nebula", aliases=[]),
            Target(id=TID_BABY_PELICAN, primary_name="Baby Pelican Nebula", aliases=[]),
        ])
        # Spec 9: unresolved OBJECT-name groups for include_unresolved
        for n in range(1, 4):
            s.add(_img(resolved_target_id=None,
                       raw_headers={"OBJECT": f"Pelican Panel {n}"}))
        await s.commit()

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
    await engine.dispose()


async def _search(q: str, **params):
    transport = ASGITransport(app=app)
    qp = "&".join(f"{k}={v}" for k, v in params.items())
    from urllib.parse import quote
    url = f"/api/targets/search?q={quote(q)}" + (f"&{qp}" if qp else "")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(url)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(results):
    """Target UUIDs in the result, excluding unresolved obj: pseudo entries."""
    return [r["id"] for r in results if not r.get("unresolved")]


# ---------------------------------------------------------------------------
# Spec 1: compact normalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["M31", "M 31", "m 31"])
async def test_compact_normalization_messier(seeded_db, q):
    results = await _search(q)
    assert str(TID_M31) in _ids(results), f"query {q!r} did not find M 31"


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["sh2-129", "SH2 129", "sh 2-129"])
async def test_compact_normalization_sharpless(seeded_db, q):
    results = await _search(q)
    assert str(TID_SH129) in _ids(results), f"query {q!r} did not find SH 2-129"


# ---------------------------------------------------------------------------
# Spec 2: no fuzzy padding when an exact hit exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_sharpless_hit_has_no_fuzzy_extras(seeded_db):
    results = await _search("sh2-129")
    assert _ids(results) == [str(TID_SH129)], (
        f"expected exactly SH 2-129, got {[(r['primary_name'], r['similarity_score']) for r in results]}"
    )


@pytest.mark.asyncio
async def test_exact_ngc_hit_has_no_fuzzy_extras(seeded_db):
    results = await _search("ngc 7000")
    assert _ids(results) == [str(TID_N7000)], (
        f"expected exactly NGC 7000, got {[(r['primary_name'], r['similarity_score']) for r in results]}"
    )


# ---------------------------------------------------------------------------
# Spec 3: shared alias word must not drag unrelated targets in
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shared_nebula_word_does_not_drag_others(seeded_db):
    results = await _search("cave nebula")
    ids = _ids(results)
    assert str(TID_CAVE) in ids
    assert str(TID_LION) not in ids
    assert str(TID_WIZARD) not in ids
    assert str(TID_PELICAN_NEB) not in ids
    assert str(TID_BABY_PELICAN) not in ids
    assert ids == [str(TID_CAVE)], f"expected only the Cave target, got {ids}"


@pytest.mark.asyncio
async def test_alias_hit_reports_alias_as_match_source(seeded_db):
    results = await _search("cave nebula")
    cave = next(r for r in results if r["id"] == str(TID_CAVE))
    assert cave["match_source"] == "CAVE NEBULA"


# ---------------------------------------------------------------------------
# Spec 4: fuzzy tier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typo_finds_andromeda_via_fuzzy(seeded_db):
    results = await _search("andromedda")
    ids = _ids(results)
    assert str(TID_M31) in ids, f"typo query found {ids} instead"
    hit = next(r for r in results if r["id"] == str(TID_M31))
    assert hit["similarity_score"] < 1.0
    assert hit["match_source"] is not None
    assert "andromed" in hit["match_source"].lower()


@pytest.mark.asyncio
async def test_primary_name_is_fuzzy_searchable(seeded_db):
    # Target has ONLY a primary_name: no catalog_id, common_name, or aliases.
    results = await _search("barnad loop")
    ids = _ids(results)
    assert str(TID_BARNARD_LOOP) in ids, (
        "typo on a primary_name-only target found nothing: fuzzy tier must "
        f"cover primary_name (got {ids})"
    )
    hit = next(r for r in results if r["id"] == str(TID_BARNARD_LOOP))
    assert hit["match_source"] is not None


# ---------------------------------------------------------------------------
# Spec 5: common-name table (Stellarium names.dat + COMMON_NAME_MAP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_common_name_flying_bat_finds_sh2_129(seeded_db):
    # names.dat: SH2 129 -> "Flying Bat Nebula". The target carries no
    # "flying bat" text anywhere, so only the common-name tier can find it.
    results = await _search("flying bat nebula")
    assert str(TID_SH129) in _ids(results)


@pytest.mark.asyncio
async def test_common_name_cats_eye_finds_ngc_6543(seeded_db):
    # names.dat: NGC 6543 -> "Cat's Eye Nebula".
    results = await _search("cat's eye nebula")
    assert str(TID_CATS_EYE) in _ids(results)


@pytest.mark.asyncio
async def test_common_name_fragment_min_length(seeded_db):
    # "eye" is a fragment of "cat's eye nebula" but 3 chars or fewer must not
    # match via the common-name tier.
    results = await _search("eye")
    assert str(TID_CATS_EYE) not in _ids(results), (
        "3-char fragment 'eye' matched NGC 6543 via the common-name tier"
    )


# ---------------------------------------------------------------------------
# Spec 6: ordering exact > prefix > substring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ordering_exact_prefix_substring(seeded_db):
    results = await _search("pelican")
    ids = _ids(results)
    assert ids == [str(TID_PELICAN), str(TID_PELICAN_NEB), str(TID_BABY_PELICAN)], (
        f"order wrong: {[(r['primary_name'], r['similarity_score']) for r in results]}"
    )
    by_id = {r["id"]: r for r in results}
    assert by_id[str(TID_PELICAN)]["similarity_score"] == pytest.approx(1.0)
    assert by_id[str(TID_PELICAN_NEB)]["similarity_score"] == pytest.approx(0.9)
    assert by_id[str(TID_BABY_PELICAN)]["similarity_score"] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_ordering_is_deterministic(seeded_db):
    first = await _search("pelican")
    second = await _search("pelican")
    assert [r["id"] for r in first] == [r["id"] for r in second]


# ---------------------------------------------------------------------------
# Spec 7: match_source populated on every hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["pelican", "sh2-129", "cave nebula", "m 31",
                               "andromedda", "barnad loop"])
async def test_match_source_populated_on_every_hit(seeded_db, q):
    results = await _search(q)
    assert results, f"query {q!r} returned nothing"
    for r in results:
        if r.get("unresolved"):
            continue
        assert r["match_source"], (
            f"query {q!r}: hit {r['primary_name']!r} has empty match_source"
        )


# ---------------------------------------------------------------------------
# Spec 8: "%" and "_" are literal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["%", "%%%", "____"])
async def test_wildcard_characters_are_literal(seeded_db, q):
    # A raw ILIKE would turn these into match-everything patterns.
    results = await _search(q)
    assert results == [], (
        f"wildcard query {q!r} exploded into {len(results)} rows: "
        f"{[r['primary_name'] for r in results[:5]]}"
    )


# ---------------------------------------------------------------------------
# Spec 9: limit respected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limit_respected(seeded_db):
    results = await _search("pelican", limit=2)
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_limit_respected_with_unresolved(seeded_db):
    # 3 pelican targets + 3 unresolved "Pelican Panel N" OBJECT groups seeded;
    # total rows must still fit the limit.
    results = await _search("pelican", limit=4, include_unresolved="true")
    assert len(results) <= 4, (
        f"limit=4 returned {len(results)} rows: {[r['primary_name'] for r in results]}"
    )


@pytest.mark.asyncio
async def test_include_unresolved_appends_object_groups(seeded_db):
    results = await _search("pelican", limit=10, include_unresolved="true")
    unresolved = [r for r in results if r.get("unresolved")]
    assert len(unresolved) == 3
    assert {r["primary_name"] for r in unresolved} == {
        "Pelican Panel 1", "Pelican Panel 2", "Pelican Panel 3",
    }
    for r in unresolved:
        assert r["id"].startswith("obj:")
        assert r["image_count"] == 1
