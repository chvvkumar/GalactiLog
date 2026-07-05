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
    _migrate_v12_exposure_and_metric_split,
    _migrate_v13_enrich_created_targets,
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

    def test_v12_is_exposure_and_metric_split(self):
        assert 12 in MIGRATIONS
        desc, func = MIGRATIONS[12]
        assert func is _migrate_v12_exposure_and_metric_split

    def test_v13_is_enrich_created_targets(self):
        assert 13 in MIGRATIONS
        desc, func = MIGRATIONS[13]
        assert func is _migrate_v13_enrich_created_targets
        assert "enrichment" in desc.lower()
        assert DATA_VERSION == 13


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


class TestV12ExposureAndMetricSplit:
    """End-to-end backfill of exposure_time and FWHM reclassification (AUD-001/007)."""

    def test_backfills_exposure_and_splits_fwhm(self):
        from sqlalchemy import text
        from app.models import Image

        Session, engine = _sync_session_factory()
        session = Session()

        # Unique file paths so the rows are isolated from any existing data.
        tag = uuid.uuid4().hex[:8]
        p_exposure = f"/fits/{tag}/exposure_only.fits"
        p_fwhm = f"/fits/{tag}/fwhm_mislabeled.fits"
        p_real_hfr = f"/fits/{tag}/real_hfr.fits"
        p_exptime = f"/fits/{tag}/has_exptime.fits"
        ids = {}
        try:
            # Row 1: EXPOSURE-only header, exposure_time NULL (the AUD-001 bug).
            r1 = Image(
                file_path=p_exposure, file_name="exposure_only.fits",
                exposure_time=None,
                raw_headers={"EXPOSURE": 180.0, "OBJECT": "M31"},
            )
            # Row 2: FWHM stored in median_hfr, no HFR keyword (the AUD-007 bug).
            r2 = Image(
                file_path=p_fwhm, file_name="fwhm_mislabeled.fits",
                exposure_time=300.0, median_hfr=3.4, median_fwhm=None,
                raw_headers={"FWHM": 3.4, "OBJECT": "M31"},
            )
            # Row 3: genuine HFR -- must be left untouched.
            r3 = Image(
                file_path=p_real_hfr, file_name="real_hfr.fits",
                exposure_time=300.0, median_hfr=1.9, median_fwhm=None,
                raw_headers={"HFR": 1.9, "FWHM": 3.6, "OBJECT": "M31"},
            )
            # Row 4: already has exposure_time via EXPTIME -- unchanged.
            r4 = Image(
                file_path=p_exptime, file_name="has_exptime.fits",
                exposure_time=120.0,
                raw_headers={"EXPTIME": 120.0, "OBJECT": "M31"},
            )
            session.add_all([r1, r2, r3, r4])
            session.commit()
            for r in (r1, r2, r3, r4):
                ids[r.file_path] = r.id

            summary = _migrate_v12_exposure_and_metric_split(session)
            session.commit()

            # Row 1: exposure backfilled from EXPOSURE.
            got1 = session.get(Image, ids[p_exposure])
            assert got1.exposure_time == pytest.approx(180.0)

            # Row 2: value moved from median_hfr to median_fwhm.
            got2 = session.get(Image, ids[p_fwhm])
            assert got2.median_hfr is None
            assert got2.median_fwhm == pytest.approx(3.4)

            # Row 3: genuine HFR untouched.
            got3 = session.get(Image, ids[p_real_hfr])
            assert got3.median_hfr == pytest.approx(1.9)
            assert got3.median_fwhm is None

            # Row 4: exposure unchanged.
            got4 = session.get(Image, ids[p_exptime])
            assert got4.exposure_time == pytest.approx(120.0)

            assert "exposures backfilled" in summary
            assert "FWHM values moved" in summary
        finally:
            session.rollback()
            for fp in (p_exposure, p_fwhm, p_real_hfr, p_exptime):
                session.execute(
                    text("DELETE FROM images WHERE file_path = :fp"), {"fp": fp}
                )
            session.commit()
            session.close()
            engine.dispose()


class TestLoadReferenceCatalogs:
    """H1: static catalogs must load independently of the data-version gate.

    The v2.0 baseline seeds fresh databases at the current data_version, so
    the data migrations that used to load OpenNGC/SAC/Caldwell/etc. as a side
    effect (v3, v7, v13) never fire on a fresh install. load_reference_catalogs
    is the standalone replacement dispatched unconditionally from boot.
    """

    def test_fresh_db_loads_then_second_run_is_idempotent(self):
        from sqlalchemy import text
        from app.services.data_migrations import (
            reference_catalogs_are_empty, load_reference_catalogs,
        )
        from app.models.openngc import OpenNGCEntry
        from app.models.sac_catalog import SACEntry
        from app.models.caldwell_catalog import CaldwellEntry

        Session, engine = _sync_session_factory()
        session = Session()
        try:
            # Simulate a fresh install by wiping the catalog tables. This
            # never gets committed -- the whole test runs in one transaction
            # that is rolled back in `finally`, so whatever the rest of the
            # suite had already loaded is restored regardless of test order.
            for tbl in (
                "target_catalog_memberships",
                "openngc_catalog", "sac_catalog", "caldwell_catalog",
                "herschel400_catalog", "arp_catalog", "abell_catalog",
            ):
                session.execute(text(f"DELETE FROM {tbl}"))
            session.flush()

            assert reference_catalogs_are_empty(session) is True

            summary = load_reference_catalogs(session)
            session.flush()

            openngc_count = session.query(OpenNGCEntry).count()
            sac_count = session.query(SACEntry).count()
            caldwell_count = session.query(CaldwellEntry).count()
            assert openngc_count > 0, "OpenNGC catalog must be populated on a fresh DB"
            assert sac_count > 0, "SAC catalog must be populated on a fresh DB"
            assert caldwell_count > 0, "Caldwell catalog must be populated on a fresh DB"
            assert reference_catalogs_are_empty(session) is False
            assert "OpenNGC" in summary and "SAC" in summary

            # Second run must not duplicate rows: every loader upserts on a
            # natural key (see load_openngc_csv, load_sac_csv, load_catalog_csv,
            # upsert_membership), so re-running is a no-op on row counts.
            load_reference_catalogs(session)
            session.flush()

            assert session.query(OpenNGCEntry).count() == openngc_count
            assert session.query(SACEntry).count() == sac_count
            assert session.query(CaldwellEntry).count() == caldwell_count
        finally:
            session.rollback()
            session.close()
            engine.dispose()
