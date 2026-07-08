"""DB-backed tests for reversible target merges (AUD-005, AUD-018).

A merge now persists a merge_manifest recording the exact image id set moved,
plus the loser's session notes and non-conflicting custom column values that
were re-keyed/appended onto the winner. unmerge_target and
revert_merge_candidate replay the manifest to restore the precise pre-merge
state, including images attached via filename resolution (blank OBJECT header)
that the legacy OBJECT-text restore could never recover.

Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
Alembic schema applied. When the DB is unreachable the whole module skips,
matching the environment-dependent convention of the other DB-backed tests.
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Target, Image, SessionNote, MergeCandidate, MergeManifest,
    CustomColumn, CustomColumnValue, User, UserRole, ColumnType, AppliesTo,
)
from app.schemas.target import MergeRequest
from app.services.target_merge import merge_targets, unmerge_target
from app.api.merges import revert_merge_candidate

TEST_DB_URL = os.environ["GALACTILOG_DATABASE_URL"]


def _img(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        exposure_time=300.0,
        session_date=date(2024, 1, 10),
        raw_headers={},
    )
    defaults.update(kw)
    return Image(**defaults)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    try:
        async with engine.begin() as conn:
            for tbl in (
                "merge_manifests", "custom_column_values", "custom_columns",
                "session_notes", "merge_candidates", "images", "targets", "users",
            ):
                await conn.execute(text(f"DELETE FROM {tbl}"))
    except Exception as e:  # DB unreachable in this environment -> skip module.
        await engine.dispose()
        pytest.skip(f"Test DB unavailable: {e}")

    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session
    await engine.dispose()


async def _seed_admin(s):
    u = User(
        id=uuid.uuid4(), username="admin", password_hash="x",
        role=UserRole.admin, is_active=True,
    )
    s.add(u)
    return u


async def _seed_merge_pair(s):
    """Winner + loser with 3 OBJECT-matched frames and 2 filename-resolved
    frames (blank OBJECT header) on the loser."""
    winner = Target(id=uuid.uuid4(), primary_name="Orion Nebula", aliases=[])
    loser = Target(id=uuid.uuid4(), primary_name="M42", aliases=["NGC 1976"])
    s.add_all([winner, loser])
    # Flush the targets first: the self-referential merged_into_id FK defeats
    # SQLAlchemy's flush topo sort, so child rows could otherwise be inserted
    # before the targets and violate their FKs.
    await s.flush()

    # 3 frames whose OBJECT header matches the loser name.
    obj_ids = []
    for _ in range(3):
        img = _img(resolved_target_id=loser.id, raw_headers={"OBJECT": "M42"})
        obj_ids.append(img.id)
        s.add(img)
    # 2 filename-resolved frames: attached to the loser with a BLANK OBJECT
    # header, so an OBJECT-text restore could never recover them.
    fn_ids = []
    for _ in range(2):
        img = _img(resolved_target_id=loser.id, raw_headers={})
        fn_ids.append(img.id)
        s.add(img)
    return winner, loser, obj_ids, fn_ids


async def _count_on(s, target_id):
    return (await s.execute(
        select(Image.id).where(Image.resolved_target_id == target_id)
    )).scalars().all()


@pytest.mark.asyncio
async def test_merge_then_unmerge_restores_all_images(db_session):
    async with db_session() as s:
        winner, loser, obj_ids, fn_ids = await _seed_merge_pair(s)
        await s.commit()
        winner_id, loser_id = winner.id, loser.id
        all_ids = set(obj_ids) | set(fn_ids)

    async with db_session() as s:
        await merge_targets(MergeRequest(winner_id=winner_id, loser_id=loser_id), s)

    async with db_session() as s:
        # All 5 images (including the 2 filename-resolved) are now on the winner.
        assert set(await _count_on(s, winner_id)) == all_ids
        assert await _count_on(s, loser_id) == []
        # A manifest recording the exact moved set exists.
        manifest = (await s.execute(
            select(MergeManifest).where(MergeManifest.loser_id == loser_id)
        )).scalars().first()
        assert manifest is not None
        assert set(manifest.payload["image_ids"]) == {str(i) for i in all_ids}

    async with db_session() as s:
        await unmerge_target(loser_id, s)

    async with db_session() as s:
        # ALL 5 images return to the loser, including filename-resolved ones.
        assert set(await _count_on(s, loser_id)) == all_ids
        assert await _count_on(s, winner_id) == []
        # Manifest consumed.
        assert (await s.execute(
            select(MergeManifest).where(MergeManifest.loser_id == loser_id)
        )).scalars().first() is None


@pytest.mark.asyncio
async def test_merge_then_revert_candidate_restores_all_images(db_session):
    async with db_session() as s:
        winner, loser, obj_ids, fn_ids = await _seed_merge_pair(s)
        admin = await _seed_admin(s)
        cand = MergeCandidate(
            id=uuid.uuid4(), source_name="M42", source_image_count=5,
            suggested_target_id=winner.id, similarity_score=0.9,
            method="duplicate", status="pending",
        )
        s.add(cand)
        await s.commit()
        winner_id, loser_id, cand_id = winner.id, loser.id, cand.id
        all_ids = set(obj_ids) | set(fn_ids)

    async with db_session() as s:
        await merge_targets(MergeRequest(winner_id=winner_id, loser_id=loser_id), s)

    async with db_session() as s:
        await revert_merge_candidate(cand_id, session=s, user=admin)

    async with db_session() as s:
        # Revert restores every image to the loser, filename-resolved included.
        assert set(await _count_on(s, loser_id)) == all_ids
        assert await _count_on(s, winner_id) == []
        loser = await s.get(Target, loser_id)
        assert loser.merged_into_id is None


@pytest.mark.asyncio
async def test_legacy_merge_without_manifest_falls_back_to_object_match(db_session):
    """A merge made before manifests existed (no manifest row) unmerges via the
    legacy OBJECT-header match: OBJECT-tagged frames return, filename-resolved
    frames stay stranded. Documents the intentional fallback behavior."""
    async with db_session() as s:
        winner, loser, obj_ids, fn_ids = await _seed_merge_pair(s)
        await s.commit()
        winner_id, loser_id = winner.id, loser.id

    async with db_session() as s:
        await merge_targets(MergeRequest(winner_id=winner_id, loser_id=loser_id), s)

    # Simulate a legacy merge: drop the manifest that a modern merge recorded.
    async with db_session() as s:
        m = (await s.execute(
            select(MergeManifest).where(MergeManifest.loser_id == loser_id)
        )).scalars().first()
        await s.delete(m)
        await s.commit()

    async with db_session() as s:
        await unmerge_target(loser_id, s)

    async with db_session() as s:
        restored = set(await _count_on(s, loser_id))
        # Only OBJECT='M42' frames return; blank-OBJECT frames stay on winner.
        assert restored == set(obj_ids)
        assert set(await _count_on(s, winner_id)) == set(fn_ids)


@pytest.mark.asyncio
async def test_merge_moves_notes_to_winner_and_unmerge_restores(db_session):
    async with db_session() as s:
        winner, loser, _, _ = await _seed_merge_pair(s)
        d_shared = date(2024, 1, 10)
        d_only = date(2024, 2, 20)
        # Winner already has a note on the shared date.
        s.add(SessionNote(id=uuid.uuid4(), target_id=winner.id, session_date=d_shared, notes="winner night"))
        # Loser has a note on the same shared date (-> appended) and one on a
        # date the winner lacks (-> re-keyed/moved).
        s.add(SessionNote(id=uuid.uuid4(), target_id=loser.id, session_date=d_shared, notes="loser shared night"))
        s.add(SessionNote(id=uuid.uuid4(), target_id=loser.id, session_date=d_only, notes="loser solo night"))
        await s.commit()
        winner_id, loser_id = winner.id, loser.id

    async with db_session() as s:
        await merge_targets(MergeRequest(winner_id=winner_id, loser_id=loser_id), s)

    async with db_session() as s:
        winner_notes = {n.session_date: n.notes for n in (await s.execute(
            select(SessionNote).where(SessionNote.target_id == winner_id)
        )).scalars().all()}
        # Shared-date note appended; solo-date note now visible on winner.
        assert "loser shared night" in winner_notes[date(2024, 1, 10)]
        assert "winner night" in winner_notes[date(2024, 1, 10)]
        assert winner_notes[date(2024, 2, 20)] == "loser solo night"

    async with db_session() as s:
        await unmerge_target(loser_id, s)

    async with db_session() as s:
        winner_notes = {n.session_date: n.notes for n in (await s.execute(
            select(SessionNote).where(SessionNote.target_id == winner_id)
        )).scalars().all()}
        loser_notes = {n.session_date: n.notes for n in (await s.execute(
            select(SessionNote).where(SessionNote.target_id == loser_id)
        )).scalars().all()}
        # Winner note back to its pre-merge text; loser notes restored intact.
        assert winner_notes[date(2024, 1, 10)] == "winner night"
        assert loser_notes[date(2024, 1, 10)] == "loser shared night"
        assert loser_notes[date(2024, 2, 20)] == "loser solo night"


@pytest.mark.asyncio
async def test_merge_copies_custom_values_and_unmerge_restores(db_session):
    async with db_session() as s:
        winner, loser, _, _ = await _seed_merge_pair(s)
        admin = await _seed_admin(s)
        await s.flush()
        col = CustomColumn(
            id=uuid.uuid4(), name="Priority", slug="priority",
            column_type=ColumnType.text, applies_to=AppliesTo.target, created_by=admin.id,
        )
        s.add(col)
        await s.flush()
        # Loser has a target-level value; winner has none -> copied to winner.
        s.add(CustomColumnValue(
            id=uuid.uuid4(), column_id=col.id, target_id=loser.id,
            value="high", updated_by=admin.id,
        ))
        await s.commit()
        winner_id, loser_id, col_id = winner.id, loser.id, col.id

    async with db_session() as s:
        await merge_targets(MergeRequest(winner_id=winner_id, loser_id=loser_id), s)

    async with db_session() as s:
        winner_vals = (await s.execute(
            select(CustomColumnValue).where(CustomColumnValue.target_id == winner_id)
        )).scalars().all()
        assert [v.value for v in winner_vals] == ["high"]

    async with db_session() as s:
        await unmerge_target(loser_id, s)

    async with db_session() as s:
        loser_vals = (await s.execute(
            select(CustomColumnValue).where(CustomColumnValue.target_id == loser_id)
        )).scalars().all()
        winner_vals = (await s.execute(
            select(CustomColumnValue).where(CustomColumnValue.target_id == winner_id)
        )).scalars().all()
        assert [v.value for v in loser_vals] == ["high"]
        assert winner_vals == []
