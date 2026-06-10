"""Tests for the data migrations module."""
import os
import uuid
from unittest.mock import patch

import pytest

# Ensure the DB URL is set so the integration test below can read it via
# os.environ[...] when this file is run standalone (matches the pattern in
# other integration test files like test_targets_aggregation.py).
os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

from app.services.data_migrations import (
    DATA_VERSION,
    MIGRATIONS,
    get_pending_migrations,
    _migrate_v11_hyperleda_galaxies,
)


class TestGetPendingMigrations:
    def test_returns_all_when_at_zero(self):
        pending = get_pending_migrations(0)
        assert len(pending) == len(MIGRATIONS)
        assert pending[0][0] == 1  # first version

    def test_returns_none_when_current(self):
        pending = get_pending_migrations(DATA_VERSION)
        assert len(pending) == 0

    def test_returns_subset_when_partially_migrated(self):
        if DATA_VERSION < 2:
            pytest.skip("Only one migration exists")
        pending = get_pending_migrations(1)
        assert all(ver > 1 for ver, _, _ in pending)

    def test_migrations_are_sequential(self):
        versions = sorted(MIGRATIONS.keys())
        for i, ver in enumerate(versions):
            assert ver == i + 1, f"Migration versions must be sequential: gap at {ver}"

    def test_all_migrations_are_callable(self):
        for ver, (desc, func) in MIGRATIONS.items():
            assert callable(func), f"Migration v{ver} is not callable"
            assert isinstance(desc, str) and len(desc) > 0, f"Migration v{ver} has no description"

    def test_data_version_matches_latest_migration(self):
        assert DATA_VERSION == max(MIGRATIONS.keys()), \
            "DATA_VERSION must equal the highest migration version"

    def test_v11_is_hyperleda_backfill(self):
        assert 11 in MIGRATIONS
        desc, func = MIGRATIONS[11]
        assert func is _migrate_v11_hyperleda_galaxies
        assert "hyperleda" in desc.lower()


def _sync_session_factory():
    """Build a sync Session bound to the test DB, or skip if unreachable."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = os.environ["GALACTILOG_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        conn = engine.connect()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test DB not reachable: {exc}")
    return sessionmaker(bind=engine), engine


class TestV11HyperledaBackfill:
    """End-to-end backfill of a real galaxy target against the test DB."""

    def test_enriches_galaxy_target(self):
        from sqlalchemy import text
        from app.models import Target
        from app.models.hyperleda_cache import HyperLEDACache

        Session, engine = _sync_session_factory()
        catalog_id = f"NGC TEST {uuid.uuid4().hex[:8]}"
        tid = uuid.uuid4()

        session = Session()
        try:
            # Clean slate so v11 (which scans all active targets) processes
            # only our seeded galaxy. Mirrors the wipe used by the integration
            # fixtures in test_targets_aggregation.py.
            for tbl in (
                "images",
                "target_catalog_memberships",
                "mosaic_panels",
                "mosaics",
                "targets",
                "hyperleda_cache",
            ):
                session.execute(text(f"DELETE FROM {tbl}"))
            session.commit()

            # Seed one galaxy target.
            session.add(Target(
                id=tid,
                primary_name=catalog_id,
                catalog_id=catalog_id,
                object_type="G",
            ))
            session.commit()

            data = {"t_type": 4.0, "inclination": 67.3}
            # Mock only the network call; the cache write and ORM updates run
            # for real against the DB.
            with patch(
                "app.services.hyperleda.query_hyperleda", return_value=data
            ) as mock_query:
                summary = _migrate_v11_hyperleda_galaxies(session)
                session.commit()

            # The wiring must have driven exactly one network query for the
            # single seeded galaxy (proves v11 calls the enricher, and that
            # the pacing pre-check counted a real query).
            assert mock_query.call_count == 1
            assert "1 network queries" in summary

            refreshed = session.get(Target, tid)
            assert refreshed.hubble_t_type == pytest.approx(4.0)
            assert refreshed.inclination == pytest.approx(67.3)

            cache_row = session.get(HyperLEDACache, catalog_id)
            assert cache_row is not None
            assert cache_row.t_type == pytest.approx(4.0)
            assert cache_row.inclination == pytest.approx(67.3)
        finally:
            # Cleanup seeded rows.
            session.rollback()
            session.execute(
                text("DELETE FROM targets WHERE id = :id"), {"id": tid}
            )
            session.execute(
                text("DELETE FROM hyperleda_cache WHERE catalog_id = :cid"),
                {"cid": catalog_id},
            )
            session.commit()
            session.close()
            engine.dispose()
