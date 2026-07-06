"""Tests for Image.panel_label / Image.panel_id (0018 migration + model).

Uses a real sync engine against the test DB (same pattern as
test_catalog_cache_migration.py) since the FK/index behavior and the backfill
semantics depend on real Postgres, not something a mocked session could
exercise meaningfully. Seeds real Target/Mosaic/MosaicPanel/Image rows and
runs the migration's backfill function directly.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzpanelmemtest"


def _sync_session_factory():
    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


@pytest.fixture
def db():
    Session, engine = _sync_session_factory()
    yield Session
    engine.dispose()


def _migration_module():
    from alembic.script import ScriptDirectory
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    return script.get_revision("0018").module


def _cleanup(session):
    session.execute(text("DELETE FROM images WHERE file_path LIKE :p"), {"p": f"/{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaic_panels WHERE panel_label LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaics WHERE name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM targets WHERE primary_name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.commit()


# ---------------------------------------------------------------------------
# Model round-trip: columns exist, correct types, FK ON DELETE SET NULL works.
# ---------------------------------------------------------------------------

def test_image_panel_columns_round_trip_and_fk_set_null(db):
    from app.models.image import Image
    from app.models.mosaic import Mosaic
    from app.models.mosaic_panel import MosaicPanel
    from app.models.target import Target

    Session = db
    s = Session()
    try:
        _cleanup(s)

        target = Target(primary_name=f"{TEST_MARK}_target", aliases=[])
        s.add(target)
        s.flush()

        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic")
        s.add(mosaic)
        s.flush()

        panel = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target.id, panel_label=f"{TEST_MARK}_Panel 1",
        )
        s.add(panel)
        s.flush()

        image = Image(
            file_path=f"/{TEST_MARK}/round_trip.fits",
            file_name="round_trip.fits",
            resolved_target_id=target.id,
            image_type="LIGHT",
            panel_label=panel.panel_label,
            panel_id=panel.id,
        )
        s.add(image)
        s.commit()

        fetched = s.get(Image, image.id)
        assert fetched.panel_label == f"{TEST_MARK}_Panel 1"
        assert fetched.panel_id == panel.id

        # Column type/nullability sanity check via information_schema.
        cols = {
            row.column_name: row
            for row in s.execute(text(
                "SELECT column_name, is_nullable, data_type, character_maximum_length "
                "FROM information_schema.columns WHERE table_name = 'images' "
                "AND column_name IN ('panel_label', 'panel_id')"
            ))
        }
        assert cols["panel_label"].is_nullable == "YES"
        assert cols["panel_label"].data_type == "character varying"
        assert cols["panel_label"].character_maximum_length == 100
        assert cols["panel_id"].is_nullable == "YES"
        assert cols["panel_id"].data_type == "uuid"

        # FK ON DELETE SET NULL: deleting the panel must null out panel_id,
        # not fail or cascade-delete the Image row.
        s.delete(panel)
        s.commit()

        refetched = s.get(Image, image.id)
        assert refetched is not None
        assert refetched.panel_id is None
        # panel_label is untouched by the FK action (only panel_id is a FK).
        assert refetched.panel_label == f"{TEST_MARK}_Panel 1"
    finally:
        _cleanup(s)
        s.close()


def test_images_panel_id_and_target_panel_label_indexes_exist(db):
    Session = db
    s = Session()
    try:
        index_names = {
            row[0]
            for row in s.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'images'"
            ))
        }
        assert "ix_images_panel_id" in index_names
        assert "ix_images_target_panel_label" in index_names
    finally:
        s.close()


# ---------------------------------------------------------------------------
# downgrade() cleanly reverses upgrade()'s schema changes. Run inside a
# transaction that is rolled back afterwards so the shared test DB keeps the
# columns other tests (and later phase tasks) depend on.
# ---------------------------------------------------------------------------

def test_downgrade_reverses_upgrade_schema_changes(db):
    """Run the real ``alembic downgrade``/``upgrade`` CLI round trip.

    Exercising downgrade()/upgrade() through Operations() constructed by hand
    (mirroring test_catalog_cache_migration.py's pattern) hits an alembic
    internals quirk unrelated to this migration: op.drop_index(table_name=...)
    needs a MigrationContext whose `.opts` carries target_metadata, and the
    module-level `op` proxy does not pick up the manually-built context the
    same way real `env.py`-driven runs do (op.add_column/create_index, used
    by upgrade(), don't hit that code path and work fine either way -- this
    is specific to drop_index's reflection lookup). Shelling out to the real
    CLI proves the exact code path production/ops actually exercise. The test
    DB has no real data to lose here, so downgrading and re-upgrading in
    place is safe.
    """
    import subprocess
    import sys

    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    env = dict(os.environ)

    def _run(args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic"] + args,
            cwd=backend_dir, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{args} failed:\n{result.stdout}\n{result.stderr}"

    Session, engine = _sync_session_factory()
    try:
        _run(["downgrade", "0017"])
        with engine.connect() as connection:
            cols = {
                row[0]
                for row in connection.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'images' AND column_name IN ('panel_label', 'panel_id')"
                ))
            }
            assert cols == set()
            index_names = {
                row[0]
                for row in connection.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'images'"
                ))
            }
            assert "ix_images_panel_id" not in index_names
            assert "ix_images_target_panel_label" not in index_names
    finally:
        _run(["upgrade", "head"])
        with engine.connect() as connection:
            cols = {
                row[0]
                for row in connection.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'images' AND column_name IN ('panel_label', 'panel_id')"
                ))
            }
            assert cols == {"panel_label", "panel_id"}
        engine.dispose()


# ---------------------------------------------------------------------------
# Re-run safety: the batched backfill commits per batch, persisting the DDL
# before alembic stamps 0018 -- a crash mid-backfill leaves the columns in
# place at revision 0017. upgrade() must therefore tolerate the schema
# already existing (existence guards) instead of failing DuplicateColumn.
# ---------------------------------------------------------------------------

def test_upgrade_rerun_on_existing_schema_is_safe(db):
    """Reproduce the crash state exactly via the real alembic CLI.

    The test DB is at 0018 with the columns present. Stamping back to 0017
    without touching the schema is precisely what a mid-backfill crash
    leaves behind (DDL committed, version stamp lost); `upgrade head` from
    that state must skip the existing DDL via the guards, re-run the
    idempotent backfill, and stamp 0018.
    """
    import subprocess
    import sys

    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    env = dict(os.environ)

    def _run(args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic"] + args,
            cwd=backend_dir, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{args} failed:\n{result.stdout}\n{result.stderr}"

    Session, engine = _sync_session_factory()
    try:
        _run(["stamp", "0017"])
        _run(["upgrade", "head"])
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0018"
            cols = {
                row[0]
                for row in connection.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'images' AND column_name IN ('panel_label', 'panel_id')"
                ))
            }
            assert cols == {"panel_label", "panel_id"}
    finally:
        # Whatever happened above, leave the DB stamped at head for the
        # other tests / later phase tasks.
        _run(["stamp", "head"])
        engine.dispose()


# ---------------------------------------------------------------------------
# Tokenizer parity: the migration inlines a copy of match_panel_token_full /
# _panel_label (to avoid importing app.services.mosaic_detection, which pulls
# in fitsio via mosaic_composite purely for unrelated helpers). Guard against
# the two drifting apart.
# ---------------------------------------------------------------------------

def test_migration_tokenizer_matches_mosaic_detection_tokenizer():
    from app.services.mosaic_detection import match_panel_token_full as real_match
    from app.services.mosaic_detection import _panel_label as real_label

    import app.services.mosaic_detection as detection

    module = _migration_module()
    keywords = ["Panel", "P"]

    # Structural parity: the regex pattern strings themselves must be
    # byte-identical, so any tokenizer drift fails for ALL inputs, not just
    # the sampled cases below.
    assert module._TILE_RE.pattern == detection._TILE_RE.pattern
    assert module._TILE_RE.flags == detection._TILE_RE.flags
    assert (
        module._keyword_regex(keywords).pattern
        == detection._keyword_regex(keywords).pattern
    )
    assert (
        module._keyword_regex(keywords).flags
        == detection._keyword_regex(keywords).flags
    )

    cases = [
        "M31 Panel 3",
        "IC1805 P 12",
        "Sh2 119 Panel 1",
        "IC1805_1-1",
        "NGC 7000",
        "",
        None,
        "Veil Nebula Panel 12",
        "Veil Nebula-Panel-2",
    ]
    for name in cases:
        assert module.match_panel_token_full(name, keywords) == real_match(name, keywords)

    for num in ["1", "12", "03"]:
        assert module._panel_label(num) == real_label(num)


# ---------------------------------------------------------------------------
# Backfill semantics
# ---------------------------------------------------------------------------

def test_backfill_panel_membership_token_match_no_match_and_simple_fallback(db):
    from app.models.image import Image
    from app.models.mosaic import Mosaic
    from app.models.mosaic_panel import MosaicPanel
    from app.models.target import Target

    module = _migration_module()

    Session = db
    s = Session()
    try:
        _cleanup(s)

        # Target A: has an existing "Panel 1" MosaicPanel (token panel, has an
        # object_pattern) -- an Image whose OBJECT parses to "Panel 1" should
        # link straight to it.
        target_a = Target(primary_name=f"{TEST_MARK}_A", aliases=[])
        # Target B: has a token ("Panel 2") that parses fine but no matching
        # MosaicPanel exists yet -- panel_label set, panel_id stays NULL.
        target_b = Target(primary_name=f"{TEST_MARK}_B", aliases=[])
        # Target C: has no panel token at all, but exactly one "simple" panel
        # (no object_pattern) -- should link via the simple-panel fallback.
        target_c = Target(primary_name=f"{TEST_MARK}_C", aliases=[])
        # Target D: no panel token, no MosaicPanel at all -- both stay NULL.
        target_d = Target(primary_name=f"{TEST_MARK}_D", aliases=[])
        s.add_all([target_a, target_b, target_c, target_d])
        s.flush()

        mosaic = Mosaic(name=f"{TEST_MARK}_mosaic")
        s.add(mosaic)
        s.flush()

        # panel_label must match the derived label format ("Panel {num}"),
        # not the raw OBJECT string -- the tokenizer strips the target/base
        # name off, same as detect_mosaic_panels' _panel_label(num).
        panel_a1 = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target_a.id,
            panel_label="Panel 1", object_pattern="%A%Panel%1%",
        )
        panel_c_simple = MosaicPanel(
            mosaic_id=mosaic.id, target_id=target_c.id,
            panel_label=f"{TEST_MARK}_C simple", object_pattern=None,
        )
        s.add_all([panel_a1, panel_c_simple])
        s.flush()

        images = [
            Image(
                file_path=f"/{TEST_MARK}/a1.fits", file_name="a1.fits",
                resolved_target_id=target_a.id, image_type="LIGHT",
                raw_headers={"OBJECT": f"{TEST_MARK}_A Panel 1"},
            ),
            Image(
                file_path=f"/{TEST_MARK}/b2.fits", file_name="b2.fits",
                resolved_target_id=target_b.id, image_type="LIGHT",
                raw_headers={"OBJECT": f"{TEST_MARK}_B Panel 2"},
            ),
            Image(
                file_path=f"/{TEST_MARK}/c.fits", file_name="c.fits",
                resolved_target_id=target_c.id, image_type="LIGHT",
                raw_headers={"OBJECT": f"{TEST_MARK}_C"},
            ),
            Image(
                file_path=f"/{TEST_MARK}/d.fits", file_name="d.fits",
                resolved_target_id=target_d.id, image_type="LIGHT",
                raw_headers={"OBJECT": f"{TEST_MARK}_D"},
            ),
        ]
        s.add_all(images)
        s.commit()
        image_ids = {img.file_name: img.id for img in images}

        _, engine = _sync_session_factory()
        try:
            with engine.connect() as connection:
                updated_first = module.backfill_panel_membership(connection)
                connection.commit()
        finally:
            engine.dispose()

        assert updated_first >= 3  # a1 (token+match), b2 (token, no match), c (simple fallback)

        def _fetch(name):
            return s.execute(
                text("SELECT panel_label, panel_id FROM images WHERE id = :id"),
                {"id": image_ids[name]},
            ).first()

        a1 = _fetch("a1.fits")
        assert a1.panel_label == "Panel 1"
        assert a1.panel_id == panel_a1.id

        b2 = _fetch("b2.fits")
        assert b2.panel_label == "Panel 2"
        assert b2.panel_id is None

        c = _fetch("c.fits")
        assert c.panel_label is None
        assert c.panel_id == panel_c_simple.id

        d = _fetch("d.fits")
        assert d.panel_label is None
        assert d.panel_id is None

        # Idempotency: re-running must not change any already-set values
        # (rows with panel_label or panel_id already set are skipped by the
        # selection query) and must not error on the still-NULL/NULL rows.
        _, engine2 = _sync_session_factory()
        try:
            with engine2.connect() as connection:
                updated_second = module.backfill_panel_membership(connection)
                connection.commit()
        finally:
            engine2.dispose()

        assert updated_second == 0

        a1_again = _fetch("a1.fits")
        assert a1_again.panel_label == a1.panel_label
        assert a1_again.panel_id == a1.panel_id
        d_again = _fetch("d.fits")
        assert d_again.panel_label is None
        assert d_again.panel_id is None
    finally:
        _cleanup(s)
        s.close()
