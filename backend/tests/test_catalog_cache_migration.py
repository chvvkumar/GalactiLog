"""Tests for the catalog_cache table (model round-trip) and the 0017 data-copy
migration that backfills it from the five per-source cache tables.

Uses a real sync engine against the test DB (same _sync_session_factory
pattern as test_data_jobs.py / test_data_migrations.py) since the assertions
depend on real Postgres JSONB/ON CONFLICT semantics, not something a mocked
session could exercise meaningfully.
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


# ---------------------------------------------------------------------------
# Model round-trip
# ---------------------------------------------------------------------------

def test_catalog_cache_model_round_trip(db):
    from app.models.catalog_cache import CatalogCache

    Session = db
    s = Session()
    try:
        s.execute(text("DELETE FROM catalog_cache WHERE source = 'test_source'"))
        s.commit()

        row = CatalogCache(
            source="test_source",
            key="test_key",
            payload={"a": 1, "b": "two"},
            negative=False,
        )
        s.add(row)
        s.commit()

        fetched = s.get(CatalogCache, ("test_source", "test_key"))
        assert fetched is not None
        assert fetched.payload == {"a": 1, "b": "two"}
        assert fetched.negative is False
        assert fetched.fetched_at is not None

        neg_row = CatalogCache(
            source="test_source", key="test_key_negative", payload=None, negative=True,
        )
        s.add(neg_row)
        s.commit()

        fetched_neg = s.get(CatalogCache, ("test_source", "test_key_negative"))
        assert fetched_neg.payload is None
        assert fetched_neg.negative is True
    finally:
        s.execute(text("DELETE FROM catalog_cache WHERE source = 'test_source'"))
        s.commit()
        s.close()


# ---------------------------------------------------------------------------
# Migration data-copy: seed rows into the five old tables, re-run the 0017
# upgrade() copy SQL directly (idempotent, ON CONFLICT DO NOTHING), and
# assert matching counts + payload contents including a negative row per
# source.
# ---------------------------------------------------------------------------

TEST_MARK = "zzmigtest"


def _cleanup(session, gaia_ids=()):
    session.execute(text("DELETE FROM catalog_cache WHERE key LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM simbad_cache WHERE query_name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM sesame_cache WHERE query_name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM vizier_cache WHERE catalog_id LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM hyperleda_cache WHERE catalog_id LIKE :p"), {"p": f"{TEST_MARK}%"})
    if gaia_ids:
        session.execute(
            text("DELETE FROM gaia_cache WHERE target_id::text = ANY(:ids)"),
            {"ids": [str(i) for i in gaia_ids]},
        )
        session.execute(
            text("DELETE FROM catalog_cache WHERE source = 'gaia' AND key = ANY(:ids)"),
            {"ids": [str(i) for i in gaia_ids]},
        )
    session.commit()


@pytest.fixture
def seeded_gaia_ids():
    return [str(uuid.uuid4()), str(uuid.uuid4())]


def test_migration_copies_data_from_all_five_old_tables_with_matching_counts(db, seeded_gaia_ids):
    Session = db
    s = Session()
    gid_pos, gid_neg = seeded_gaia_ids
    try:
        _cleanup(s, seeded_gaia_ids)

        # simbad: one positive, one negative
        s.execute(text("""
            INSERT INTO simbad_cache (query_name, main_id, raw_aliases, ra, dec, object_type)
            VALUES (:k1, 'M31', ARRAY['Andromeda'], 10.5, 41.2, 'Galaxy'),
                   (:k2, NULL, ARRAY[]::varchar[], NULL, NULL, NULL)
        """), {"k1": f"{TEST_MARK}_simbad_pos", "k2": f"{TEST_MARK}_simbad_neg"})

        # sesame: one positive (with resolver), one negative
        s.execute(text("""
            INSERT INTO sesame_cache (query_name, main_id, raw_aliases, ra, dec, object_type, resolver)
            VALUES (:k1, 'NGC 224', ARRAY['M31'], 10.6, 41.3, 'Galaxy', 'simbad'),
                   (:k2, NULL, ARRAY[]::varchar[], NULL, NULL, NULL, NULL)
        """), {"k1": f"{TEST_MARK}_sesame_pos", "k2": f"{TEST_MARK}_sesame_neg"})

        # vizier: one positive, one negative (both size cols NULL)
        s.execute(text("""
            INSERT INTO vizier_cache (catalog_id, vizier_catalog, size_major, size_minor, constellation)
            VALUES (:k1, 'VII/118', 178.0, 63.0, 'And'),
                   (:k2, NULL, NULL, NULL, NULL)
        """), {"k1": f"{TEST_MARK}_vizier_pos", "k2": f"{TEST_MARK}_vizier_neg"})

        # hyperleda: one positive, one negative (both t_type/inclination NULL)
        s.execute(text("""
            INSERT INTO hyperleda_cache (catalog_id, t_type, inclination)
            VALUES (:k1, 3.0, 77.5),
                   (:k2, NULL, NULL)
        """), {"k1": f"{TEST_MARK}_hyperleda_pos", "k2": f"{TEST_MARK}_hyperleda_neg"})

        # gaia: one positive, one negative (distance_pc NULL); real target FK
        # is not enforced by the model so raw UUIDs are fine here.
        s.execute(text("""
            INSERT INTO gaia_cache (target_id, distance_pc, parallax_count)
            VALUES (:g1, 785.0, 12),
                   (:g2, NULL, NULL)
        """), {"g1": gid_pos, "g2": gid_neg})

        s.commit()

        # Run the migration's copy logic directly (same SQL as 0017 upgrade()),
        # bound to a real Operations context so the module's `op.*` calls have
        # something to talk to outside of a normal `alembic upgrade` run.
        from alembic.script import ScriptDirectory
        from alembic.config import Config as AlembicConfig
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        module = script.get_revision("0017").module

        _, engine = _sync_session_factory()
        try:
            with engine.connect() as connection:
                ctx = MigrationContext.configure(connection)
                op_obj = Operations(ctx)
                with Operations.context(op_obj):
                    module.upgrade()
                    # Re-run to prove idempotency (ON CONFLICT DO NOTHING).
                    module.upgrade()
                connection.commit()
        finally:
            engine.dispose()

        rows = {
            row.key: row
            for row in s.execute(
                text("SELECT source, key, payload, negative FROM catalog_cache WHERE key LIKE :p"),
                {"p": f"{TEST_MARK}%"},
            ).mappings()
        }
        # gaia rows are keyed by UUID text, not the TEST_MARK prefix; fetch separately.
        gaia_rows = {
            row["key"]: row
            for row in s.execute(
                text("SELECT source, key, payload, negative FROM catalog_cache WHERE source = 'gaia' AND key = ANY(:ids)"),
                {"ids": [gid_pos, gid_neg]},
            ).mappings()
        }

        assert len(rows) == 8  # 4 tables x 2 rows each (simbad/sesame/vizier/hyperleda)
        assert len(gaia_rows) == 2

        simbad_pos = rows[f"{TEST_MARK}_simbad_pos"]
        assert simbad_pos["source"] == "simbad"
        assert simbad_pos["negative"] is False
        assert simbad_pos["payload"] == {
            "main_id": "M31", "raw_aliases": ["Andromeda"], "ra": 10.5, "dec": 41.2,
            "object_type": "Galaxy",
        }
        simbad_neg = rows[f"{TEST_MARK}_simbad_neg"]
        assert simbad_neg["negative"] is True
        assert simbad_neg["payload"] is None

        sesame_pos = rows[f"{TEST_MARK}_sesame_pos"]
        assert sesame_pos["source"] == "sesame"
        assert sesame_pos["payload"]["resolver"] == "simbad"
        sesame_neg = rows[f"{TEST_MARK}_sesame_neg"]
        assert sesame_neg["negative"] is True
        assert sesame_neg["payload"] is None

        vizier_pos = rows[f"{TEST_MARK}_vizier_pos"]
        assert vizier_pos["source"] == "vizier"
        assert vizier_pos["payload"] == {
            "vizier_catalog": "VII/118", "size_major": 178.0, "size_minor": 63.0,
            "constellation": "And",
        }
        vizier_neg = rows[f"{TEST_MARK}_vizier_neg"]
        assert vizier_neg["negative"] is True
        assert vizier_neg["payload"] is None

        hyperleda_pos = rows[f"{TEST_MARK}_hyperleda_pos"]
        assert hyperleda_pos["source"] == "hyperleda"
        assert hyperleda_pos["payload"] == {"t_type": 3.0, "inclination": 77.5}
        hyperleda_neg = rows[f"{TEST_MARK}_hyperleda_neg"]
        assert hyperleda_neg["negative"] is True
        assert hyperleda_neg["payload"] is None

        gaia_pos = gaia_rows[gid_pos]
        assert gaia_pos["source"] == "gaia"
        assert gaia_pos["payload"] == {"distance_pc": 785.0, "parallax_count": 12}
        gaia_neg = gaia_rows[gid_neg]
        assert gaia_neg["negative"] is True
        assert gaia_neg["payload"] is None
    finally:
        _cleanup(s, seeded_gaia_ids)
        s.close()
