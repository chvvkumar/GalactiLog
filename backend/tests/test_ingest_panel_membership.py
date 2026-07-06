"""Tests for panel-membership parsing at ingest time (Phase 5, Task 2).

Real DB-backed: _do_ingest is invoked directly (heavy I/O -- fitsio header
read, thumbnail generation, target resolution -- mocked) with the worker's
`_sync_engine` pointed at the real test Postgres DB, so `Image.panel_label`/
`Image.panel_id` assignment is exercised against real `Target`/`Mosaic`/
`MosaicPanel` rows and the real `resolve_panel_membership` helper in
`app.services.mosaic_detection`, not a mock.
"""
import os
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzingestpaneltest"


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
    yield Session, engine
    engine.dispose()


def _cleanup(session):
    session.execute(text("DELETE FROM images WHERE file_path LIKE :p"), {"p": f"%{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaic_panels WHERE panel_label LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM mosaics WHERE name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.execute(text("DELETE FROM targets WHERE primary_name LIKE :p"), {"p": f"{TEST_MARK}%"})
    session.commit()


def _bootstrap_tasks():
    """Load the real app.worker.tasks module, patching create_engine at import
    time so it doesn't attempt a live DB connection before we swap in the
    real test-DB engine below (same pattern as test_tasks.py)."""
    import sys as _sys
    mod = _sys.modules.get("app.worker.tasks")
    if mod is not None and not isinstance(mod, MagicMock):
        return mod
    _sys.modules.pop("app.worker.tasks", None)
    mock_engine = MagicMock()
    with patch("sqlalchemy.create_engine", return_value=mock_engine):
        import app.worker.tasks as tasks_mod
    return tasks_mod


@pytest.fixture
def seeded(db):
    """Create a Target, a Mosaic, and (optionally) MosaicPanel rows used by
    the ingest-time lookups. Returns a dict of ids for the test to consume."""
    Session, engine = db
    s = Session()
    from app.models.target import Target
    from app.models.mosaic import Mosaic
    from app.models.mosaic_panel import MosaicPanel

    _cleanup(s)

    target_matched = Target(primary_name=f"{TEST_MARK}_matched", aliases=[])
    target_unmatched = Target(primary_name=f"{TEST_MARK}_unmatched", aliases=[])
    target_no_token = Target(primary_name=f"{TEST_MARK}_notoken", aliases=[])
    target_simple = Target(primary_name=f"{TEST_MARK}_simple", aliases=[])
    target_calib = Target(primary_name=f"{TEST_MARK}_calib", aliases=[])
    s.add_all([target_matched, target_unmatched, target_no_token, target_simple, target_calib])
    s.flush()

    mosaic = Mosaic(name=f"{TEST_MARK}_mosaic")
    s.add(mosaic)
    s.flush()

    panel_matched = MosaicPanel(
        mosaic_id=mosaic.id, target_id=target_matched.id,
        panel_label="Panel 1", object_pattern=f"%{TEST_MARK}%Panel%1%",
    )
    panel_simple = MosaicPanel(
        mosaic_id=mosaic.id, target_id=target_simple.id,
        panel_label=f"{TEST_MARK}_simple panel", object_pattern=None,
    )
    s.add_all([panel_matched, panel_simple])
    s.commit()

    ids = {
        "target_matched": str(target_matched.id),
        "target_unmatched": str(target_unmatched.id),
        "target_no_token": str(target_no_token.id),
        "target_simple": str(target_simple.id),
        "target_calib": str(target_calib.id),
        "panel_matched_id": panel_matched.id,
        "panel_simple_id": panel_simple.id,
    }
    s.close()
    yield ids

    s2 = Session()
    _cleanup(s2)
    s2.close()


def _run_ingest(tasks_mod, engine, tmp_path, meta, target_id, fn=None):
    """Invoke tasks_mod._do_ingest (or the given callable, e.g. reingest)
    against the real test-DB engine with heavy I/O mocked out. Returns the
    resulting Image row (or None if the row wasn't created)."""
    fits_root = tmp_path / "fits"
    thumbs = tmp_path / "thumbs"
    fits_root.mkdir(exist_ok=True)
    thumbs.mkdir(exist_ok=True)
    fits_path = Path(meta["file_path"])
    fits_path.parent.mkdir(parents=True, exist_ok=True)
    fits_path.write_bytes(b"stub")

    def _fake_gen_thumb(path, thumb_path, max_width=None):
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.write_bytes(b"thumbnail-bytes")
        return thumb_path

    from app.schemas.settings import GeneralSettings
    general = GeneralSettings(use_imaging_night=False, mosaic_keywords=["Panel", "P"])

    patchers = [
        patch.object(tasks_mod, "_sync_engine", engine),
        patch.object(tasks_mod.settings, "fits_data_path", str(fits_root)),
        patch.object(tasks_mod.settings, "thumbnails_path", str(thumbs)),
        patch.object(tasks_mod, "fitsio", MagicMock()),
        patch.object(tasks_mod, "extract_metadata", MagicMock(return_value=meta)),
        patch.object(tasks_mod, "generate_thumbnail", _fake_gen_thumb),
        patch.object(tasks_mod, "resolve_target", MagicMock(return_value=target_id)),
        patch.object(tasks_mod, "_get_cached_general_settings", MagicMock(return_value=general)),
        patch.object(tasks_mod, "_redis", MagicMock()),
        patch.object(tasks_mod, "increment_completed_sync", MagicMock()),
        patch.object(tasks_mod, "increment_csv_enriched_sync", MagicMock()),
        patch.object(tasks_mod, "increment_skipped_calibration_sync", MagicMock()),
        patch.object(tasks_mod, "add_skipped_path_sync", MagicMock()),
    ]

    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        target = fn or tasks_mod._do_ingest
        target(str(fits_path), include_calibration=True)

    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        row = s.execute(
            select(*[c for c in tasks_mod.Image.__table__.c]).where(
                tasks_mod.Image.file_path == meta["file_path"]
            )
        ).mappings().first()
        return dict(row) if row else None
    finally:
        s.close()


def _meta(tmp_path, name, object_name, image_type="LIGHT"):
    fits_path = tmp_path / "fits" / f"{TEST_MARK}_{name}.fits"
    return {
        "file_path": str(fits_path),
        "file_name": fits_path.name,
        "object_name": object_name,
        "image_type": image_type,
        "raw_headers": {"OBJECT": object_name} if object_name else {},
        "capture_date": None,
    }


class TestIngestPanelMembership:
    def test_token_with_matching_panel_sets_both_columns(self, db, seeded, tmp_path):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        meta = _meta(tmp_path, "matched", f"{TEST_MARK} Panel 1")

        row = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_matched"])

        assert row is not None
        assert row["panel_label"] == "Panel 1"
        assert row["panel_id"] == seeded["panel_matched_id"]

    def test_token_without_matching_panel_sets_label_only(self, db, seeded, tmp_path):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        meta = _meta(tmp_path, "unmatched", f"{TEST_MARK} Panel 7")

        row = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_unmatched"])

        assert row is not None
        assert row["panel_label"] == "Panel 7"
        assert row["panel_id"] is None

    def test_no_token_and_no_simple_panel_leaves_both_null(self, db, seeded, tmp_path):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        meta = _meta(tmp_path, "notoken", f"{TEST_MARK}_notoken")

        row = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_no_token"])

        assert row is not None
        assert row["panel_label"] is None
        assert row["panel_id"] is None
        # Normal (non-mosaic) ingest fields are unaffected.
        assert row["resolved_target_id"] is not None

    def test_no_token_with_unambiguous_simple_panel_sets_panel_id_only(self, db, seeded, tmp_path):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        meta = _meta(tmp_path, "simple", f"{TEST_MARK}_simple")

        row = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_simple"])

        assert row is not None
        assert row["panel_label"] is None
        assert row["panel_id"] == seeded["panel_simple_id"]

    def test_calibration_frame_never_gets_panel_even_if_object_looks_panel_like(
        self, db, seeded, tmp_path
    ):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        # Calibration frames skip target resolution entirely in _do_ingest (no
        # OBJECT-based SIMBAD lookup for BIAS/DARK/FLAT/etc.), so target_id is
        # None regardless of what OBJECT says -- confirming the LIGHT-only
        # guard is load-bearing even for a panel-shaped OBJECT string.
        meta = _meta(tmp_path, "calib", f"{TEST_MARK} Panel 1", image_type="DARK")

        row = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_calib"])

        assert row is not None
        assert row["panel_label"] is None
        assert row["panel_id"] is None
        assert row["image_type"] == "DARK"

    def test_reingest_changed_file_matches_fresh_ingest_panel_assignment(
        self, db, seeded, tmp_path
    ):
        Session, engine = db
        tasks_mod = _bootstrap_tasks()
        meta = _meta(tmp_path, "reingest", f"{TEST_MARK} Panel 1")

        first = _run_ingest(tasks_mod, engine, tmp_path, meta, seeded["target_matched"])
        assert first["panel_label"] == "Panel 1"
        assert first["panel_id"] == seeded["panel_matched_id"]

        # Re-ingest the same (now "changed") file via reingest_changed_file,
        # which deletes the existing row and re-runs the shared _do_ingest
        # path -- proves no parallel/duplicated ingest logic bypasses the
        # panel-membership hook.
        # reingest_changed_file is a bound Celery task (bind=True); call the
        # underlying function directly via .run() to avoid needing a worker.
        import contextlib
        from app.schemas.settings import GeneralSettings
        general = GeneralSettings(use_imaging_night=False, mosaic_keywords=["Panel", "P"])
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(tasks_mod, "_sync_engine", engine))
            stack.enter_context(patch.object(tasks_mod.settings, "fits_data_path", str(tmp_path / "fits")))
            stack.enter_context(patch.object(tasks_mod.settings, "thumbnails_path", str(tmp_path / "thumbs")))
            stack.enter_context(patch.object(tasks_mod, "fitsio", MagicMock()))
            stack.enter_context(patch.object(tasks_mod, "extract_metadata", MagicMock(return_value=meta)))
            stack.enter_context(patch.object(tasks_mod, "extract_xisf_metadata", MagicMock(return_value=meta)))

            def _fake_gen_thumb(path, thumb_path, max_width=None):
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                thumb_path.write_bytes(b"thumbnail-bytes")
                return thumb_path

            stack.enter_context(patch.object(tasks_mod, "generate_thumbnail", _fake_gen_thumb))
            stack.enter_context(patch.object(tasks_mod, "resolve_target", MagicMock(return_value=seeded["target_matched"])))
            stack.enter_context(patch.object(tasks_mod, "_get_cached_general_settings", MagicMock(return_value=general)))
            stack.enter_context(patch.object(tasks_mod, "_redis", MagicMock()))
            stack.enter_context(patch.object(tasks_mod, "increment_completed_sync", MagicMock()))
            stack.enter_context(patch.object(tasks_mod, "increment_csv_enriched_sync", MagicMock()))
            stack.enter_context(patch.object(tasks_mod, "increment_failed_sync", MagicMock()))

            tasks_mod.reingest_changed_file.run(meta["file_path"], include_calibration=True)

        Session2 = sessionmaker(bind=engine)
        s = Session2()
        try:
            row = s.execute(
                select(*[c for c in tasks_mod.Image.__table__.c]).where(
                    tasks_mod.Image.file_path == meta["file_path"]
                )
            ).mappings().first()
            second = dict(row) if row else None
        finally:
            s.close()

        assert second is not None
        assert second["panel_label"] == first["panel_label"]
        assert second["panel_id"] == first["panel_id"]
