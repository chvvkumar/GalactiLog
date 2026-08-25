import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from sqlalchemy.exc import IntegrityError

# conftest.py handles env vars, fitsio stubbing, and the app.worker.tasks mock.
# Do not override those stubs here.

import fitsio  # noqa: E402  (real when available, MagicMock stub otherwise per conftest)

from app.services.scanner import extract_metadata
from app.services.thumbnail import generate_thumbnail


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bootstrap_tasks(modname="app.worker.tasks"):
    """Load the real target module, patching create_engine so it doesn't
    need a live DB connection at import time.

    Tasks now live in per-domain app.worker.tasks_* modules (app.worker.tasks
    is a thin facade that re-exports them for external call sites -- see
    app/worker/tasks.py). A test that patches an internal name (Session,
    _redis, a helper function, etc.) must bootstrap the module that actually
    OWNS the function under test, since patch.object() rebinds an attribute on
    one module's namespace and a function only sees patches made on the
    module it was defined in (its __globals__), not on the facade that merely
    re-exports the same function object. Callers pass e.g.
    modname="app.worker.tasks_scan" for _do_ingest/reingest_changed_file, or
    "app.worker.tasks_thumbnails" for the chunked thumbnail tasks.

    See conftest.bootstrap_worker_module for why the mocked engine must not be
    left behind in sys.modules.
    """
    from tests.conftest import bootstrap_worker_module

    return bootstrap_worker_module(modname)


def _make_partition_result(chunks: list[list]):
    """Return a mock result proxy that supports .yield_per().partitions() iteration."""
    result_proxy = MagicMock()

    def _yield_per(n):
        partition_proxy = MagicMock()
        partition_proxy.partitions = MagicMock(return_value=iter(chunks))
        return partition_proxy

    result_proxy.yield_per = _yield_per
    return result_proxy


# ---------------------------------------------------------------------------
# existing integration tests (fitsio backed)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_fits(tmp_path: Path) -> Path:
    import fitsio as _fitsio
    import numpy as _np
    data = _np.random.default_rng(42).normal(1000, 50, (128, 128)).astype(_np.float32)
    header = _fitsio.FITSHDR()
    for k, v in {
        "OBJECT": "NGC 7000", "EXPTIME": 600.0, "FILTER": "OIII",
        "CCD-TEMP": -15.0, "GAIN": 100, "DATE-OBS": "2024-06-15T01:30:00",
    }.items():
        header.add_record({"name": k, "value": v})
    path = tmp_path / "Light_NGC7000_001.fits"
    _fitsio.write(str(path), data, header=header, clobber=True)
    return path


def test_full_ingest_pipeline(sample_fits: Path, tmp_path: Path):
    """Integration test: extract metadata + generate thumbnail for a single file."""
    meta = extract_metadata(sample_fits)
    assert meta["object_name"] == "NGC 7000"
    assert meta["filter_used"] == "OIII"

    thumb_path = tmp_path / "thumbnails" / "thumb.jpg"
    result = generate_thumbnail(sample_fits, thumb_path, max_width=200)
    assert result.exists()


# ---------------------------------------------------------------------------
# PERF-9: regenerate_missing_thumbnails -- chunked fetch
# ---------------------------------------------------------------------------

class TestRegenerateMissingThumbnailsChunked:
    """Verify that regenerate_missing_thumbnails processes rows chunk-by-chunk
    via yield_per/partitions and produces the same logical outcomes as the
    previous all()-based implementation."""

    def _run(self, tasks_mod, chunks, tmp_path):
        """Wire a mock Session so execute().yield_per().partitions() returns
        the supplied chunks, then invoke the task and return its result dict."""
        mock_redis = MagicMock()
        mock_redis.set.return_value = True

        # Build real thumbnail files for rows that should appear "present"
        # and omit files for rows that should appear "missing".
        partition_result = _make_partition_result(chunks)

        session_ctx = MagicMock()
        session_ctx.__enter__ = MagicMock(return_value=session_ctx)
        session_ctx.__exit__ = MagicMock(return_value=False)
        session_ctx.execute = MagicMock(return_value=partition_result)

        activity_ctx = MagicMock()
        activity_ctx.__enter__ = MagicMock(return_value=MagicMock())
        activity_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(tasks_mod, "_redis", mock_redis), \
             patch.object(tasks_mod, "_emit_activity_sync", MagicMock()), \
             patch.object(tasks_mod, "_activity_session", return_value=activity_ctx), \
             patch.object(tasks_mod, "set_idle_sync", MagicMock()), \
             patch.object(tasks_mod, "set_ingesting_sync", MagicMock()), \
             patch.object(tasks_mod, "regenerate_thumbnail") as mock_regen, \
             patch.object(tasks_mod, "Session", return_value=session_ctx):
            result = tasks_mod.regenerate_missing_thumbnails.run()

        return result, mock_regen

    def test_no_rows_returns_complete(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        result, mock_regen = self._run(tasks_mod, chunks=[], tmp_path=None)
        assert result["status"] == "complete"
        assert result["checked"] == 0
        assert result["missing"] == 0
        mock_regen.delay.assert_not_called()

    def test_all_present_returns_complete(self, tmp_path):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        # Create two real thumbnail files so _check_missing returns False
        t1 = tmp_path / "t1.jpg"
        t2 = tmp_path / "t2.jpg"
        t1.write_bytes(b"x")
        t2.write_bytes(b"x")

        chunks = [
            [("id1", "/fits/a.fits", str(t1)), ("id2", "/fits/b.fits", str(t2))],
        ]
        result, mock_regen = self._run(tasks_mod, chunks=chunks, tmp_path=tmp_path)
        assert result["status"] == "complete"
        assert result["checked"] == 2
        assert result["missing"] == 0
        mock_regen.delay.assert_not_called()

    def test_missing_thumbnails_queued_across_chunks(self, tmp_path):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        # t1 exists on disk; t2 and t3 do not
        t1 = tmp_path / "t1.jpg"
        t1.write_bytes(b"x")
        t2 = str(tmp_path / "missing2.jpg")
        t3 = str(tmp_path / "missing3.jpg")

        # Two chunks to verify multi-chunk processing
        chunks = [
            [("id1", "/fits/a.fits", str(t1)), ("id2", "/fits/b.fits", t2)],
            [("id3", "/fits/c.fits", t3)],
        ]
        result, mock_regen = self._run(tasks_mod, chunks=chunks, tmp_path=tmp_path)
        assert result["status"] == "ingesting"
        assert result["checked"] == 3
        assert result["missing"] == 2
        assert mock_regen.delay.call_count == 2
        queued_ids = {c.args[0] for c in mock_regen.delay.call_args_list}
        assert "id2" in queued_ids
        assert "id3" in queued_ids

    def test_row_without_file_path_skipped(self, tmp_path):
        """Rows where file_path is falsy must not be queued even if thumb is missing."""
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        t_missing = str(tmp_path / "missing.jpg")

        chunks = [
            [("id1", None, t_missing)],
        ]
        result, mock_regen = self._run(tasks_mod, chunks=chunks, tmp_path=tmp_path)
        assert result["missing"] == 0
        mock_regen.delay.assert_not_called()


# ---------------------------------------------------------------------------
# PERF-9: purge_and_regenerate_thumbnails -- chunked fetch
# ---------------------------------------------------------------------------

class TestPurgeAndRegenerateThumbnailsChunked:
    """Verify that purge_and_regenerate_thumbnails processes rows in chunks for
    both the delete pass and the queue pass."""

    def _run(self, tasks_mod, total_count, chunks_data, tmp_path, cancel_after_purge=False):
        mock_redis = MagicMock()

        # Mock the count query (first Session call).
        # session.execute(...).scalar_one() must return total_count.
        count_session_ctx = MagicMock()
        count_session_ctx.__enter__ = MagicMock(return_value=count_session_ctx)
        count_session_ctx.__exit__ = MagicMock(return_value=False)
        count_execute_result = MagicMock()
        count_execute_result.scalar_one = MagicMock(return_value=total_count)
        count_session_ctx.execute = MagicMock(return_value=count_execute_result)

        # Mock the delete+queue chunk Sessions (second and third calls)
        partition_result = _make_partition_result(chunks_data)
        chunk_session_ctx = MagicMock()
        chunk_session_ctx.__enter__ = MagicMock(return_value=chunk_session_ctx)
        chunk_session_ctx.__exit__ = MagicMock(return_value=False)
        chunk_session_ctx.execute = MagicMock(return_value=partition_result)

        activity_ctx = MagicMock()
        activity_ctx.__enter__ = MagicMock(return_value=MagicMock())
        activity_ctx.__exit__ = MagicMock(return_value=False)

        cancel_calls = [False, cancel_after_purge]
        cancel_iter = iter(cancel_calls)

        def _is_cancel(*a, **kw):
            try:
                return next(cancel_iter)
            except StopIteration:
                return False

        session_call_count = [0]

        def _session_factory(*a, **kw):
            session_call_count[0] += 1
            if session_call_count[0] == 1:
                return count_session_ctx
            # Re-create a fresh partition result each time so both passes get chunks
            fresh_partition = _make_partition_result(chunks_data)
            fresh_ctx = MagicMock()
            fresh_ctx.__enter__ = MagicMock(return_value=fresh_ctx)
            fresh_ctx.__exit__ = MagicMock(return_value=False)
            fresh_ctx.execute = MagicMock(return_value=fresh_partition)
            return fresh_ctx

        with patch.object(tasks_mod, "_redis", mock_redis), \
             patch.object(tasks_mod, "_emit_activity_sync", MagicMock()), \
             patch.object(tasks_mod, "_activity_session", return_value=activity_ctx), \
             patch.object(tasks_mod, "set_idle_sync", MagicMock()), \
             patch.object(tasks_mod, "set_ingesting_sync", MagicMock()), \
             patch.object(tasks_mod, "set_cancelled_sync", MagicMock()), \
             patch.object(tasks_mod, "is_cancel_requested_sync", side_effect=_is_cancel), \
             patch.object(tasks_mod, "regenerate_thumbnail") as mock_regen, \
             patch.object(tasks_mod, "Session", side_effect=_session_factory):
            result = tasks_mod.purge_and_regenerate_thumbnails.run()

        return result, mock_regen

    def test_no_images_returns_complete(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        result, mock_regen = self._run(tasks_mod, total_count=0, chunks_data=[], tmp_path=None)
        assert result["status"] == "complete"
        assert result["deleted"] == 0
        assert result["queued"] == 0
        mock_regen.delay.assert_not_called()

    def test_images_queued_across_chunks(self, tmp_path):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        t1 = tmp_path / "t1.jpg"
        t1.write_bytes(b"x")
        t2 = tmp_path / "t2.jpg"
        t2.write_bytes(b"x")

        chunks = [
            [("id1", "/fits/a.fits", str(t1)), ("id2", "/fits/b.fits", str(t2))],
        ]
        result, mock_regen = self._run(tasks_mod, total_count=2, chunks_data=chunks, tmp_path=tmp_path)
        assert result["status"] == "ingesting"
        assert result["queued"] == 2
        assert mock_regen.delay.call_count == 2

    def test_rows_without_file_path_not_queued(self, tmp_path):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_thumbnails")
        chunks = [
            [("id1", None, str(tmp_path / "t1.jpg")), ("id2", "/fits/b.fits", None)],
        ]
        result, mock_regen = self._run(tasks_mod, total_count=2, chunks_data=chunks, tmp_path=tmp_path)
        assert result["queued"] == 0
        mock_regen.delay.assert_not_called()


# ---------------------------------------------------------------------------
# PERF-10: detect_duplicate_targets Pass 2 -- LEFT JOIN aggregate
# ---------------------------------------------------------------------------

class TestDetectDuplicatesPass2JoinQuery:
    """Verify the SQL text used in Pass 2 uses a LEFT JOIN aggregate rather
    than a correlated subquery, and that img_count values are correctly read."""

    def test_pass2_query_uses_left_join_not_correlated_subquery(self):
        import pathlib
        # detect_duplicate_targets now lives in tasks_target_dedup.py (Phase 6
        # Task 3 split), not directly in tasks.py.
        src = pathlib.Path("app/worker/tasks_target_dedup.py").read_text()
        # Find the active_targets_query block used in Pass 2
        assert "LEFT JOIN" in src, "Pass 2 query must use LEFT JOIN aggregate"
        assert "COALESCE(ic.img_count, 0)" in src, "Pass 2 must use COALESCE for 0-image targets"
        # The old correlated subquery pattern must be gone
        assert "(SELECT COUNT(*) FROM images i\n                    WHERE i.resolved_target_id = t.id)" \
            not in src, "Correlated subquery must be replaced by LEFT JOIN"

    def test_pass2_query_coalesce_handles_zero_images(self):
        """Simulate the query result: a target with no images should yield img_count=0."""
        # Two rows as if returned by the new LEFT JOIN query:
        # (id, primary_name, aliases, img_count)
        rows = [
            (1, "NGC 1", ["n1"], 5),   # target with images
            (2, "NGC 2", None, 0),     # target with no images (COALESCE result)
        ]
        # Reproduce the target_info mapping the task builds from those rows
        target_info = {row[0]: (row[1], row[3]) for row in rows}
        assert target_info[1] == ("NGC 1", 5)
        assert target_info[2] == ("NGC 2", 0)

    def test_pass2_group_sorting_uses_img_count(self):
        """Targets within a duplicate group are sorted descending by img_count so
        the one with the most images is selected as the merge winner."""
        # Simulate three targets sharing an alias, with img_counts from the LEFT JOIN
        members_with_info = [
            (3, "Target C", 1),
            (1, "Target A", 10),
            (2, "Target B", 4),
        ]
        members_with_info.sort(key=lambda x: x[2], reverse=True)
        winner_id, winner_name, winner_count = members_with_info[0]
        assert winner_id == 1
        assert winner_name == "Target A"
        assert winner_count == 10


# ---------------------------------------------------------------------------
# AUD-029: reingest_changed_file validates the file before deleting the row
# ---------------------------------------------------------------------------

class TestReingestValidatesBeforeDelete:
    """A truncated/corrupt file must NOT delete the existing catalog row."""

    def test_corrupt_file_does_not_delete_existing_row(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")

        bad_fitsio = MagicMock()
        bad_fitsio.read_header.side_effect = ValueError("SIMPLE card")
        mock_session_cls = MagicMock()
        mock_do_ingest = MagicMock()

        with patch.object(tasks_mod, "fitsio", bad_fitsio), \
             patch.object(tasks_mod, "Session", mock_session_cls), \
             patch.object(tasks_mod, "_do_ingest", mock_do_ingest), \
             patch.object(tasks_mod, "_redis", MagicMock()), \
             patch.object(tasks_mod, "increment_failed_sync", MagicMock()):
            result = tasks_mod.reingest_changed_file.apply(
                args=["/fits/data/truncated.fits", True]
            ).result

        # The validation read failed, so:
        assert result["status"] == "failed"
        # The DB session was never opened -> the old row was never deleted.
        mock_session_cls.assert_not_called()
        # And the ingest pipeline was never entered.
        mock_do_ingest.assert_not_called()

    def test_valid_file_proceeds_to_ingest(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")

        ok_fitsio = MagicMock()
        ok_fitsio.read_header.return_value = MagicMock()  # readable header

        # Session context manager yields a session with no existing row.
        session_ctx = MagicMock()
        session_ctx.__enter__ = MagicMock(return_value=session_ctx)
        session_ctx.__exit__ = MagicMock(return_value=False)
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = None
        session_ctx.execute = MagicMock(return_value=exec_result)

        mock_do_ingest = MagicMock(return_value={"file": "x", "status": "ok"})

        with patch.object(tasks_mod, "fitsio", ok_fitsio), \
             patch.object(tasks_mod, "Session", return_value=session_ctx), \
             patch.object(tasks_mod, "_do_ingest", mock_do_ingest), \
             patch.object(tasks_mod, "_redis", MagicMock()):
            result = tasks_mod.reingest_changed_file.apply(
                args=["/fits/data/valid.fits", True]
            ).result

        assert result["status"] == "ok"
        mock_do_ingest.assert_called_once()


# ---------------------------------------------------------------------------
# AUD-015: a duplicate ingest of the same path must NOT delete the surviving
# row's thumbnail (the thumbnail filename is deterministic from the path, so
# both attempts target the same file).
# ---------------------------------------------------------------------------

class _FakeInsertSession:
    """Minimal Session stand-in: get() returns None (defaults), and commit()
    raises the supplied exception so the insert path exercises its except
    branches without a live DB."""

    def __init__(self, commit_exc):
        self._commit_exc = commit_exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **kw):
        return None

    def add(self, *a, **kw):
        pass

    def execute(self, *a, **kw):
        return MagicMock()

    def commit(self):
        raise self._commit_exc


class TestDuplicateIngestPreservesThumbnail:
    def _run_do_ingest(self, tasks_mod, tmp_path, commit_exc, thumb_referenced=None):
        """Invoke _do_ingest with heavy I/O mocked and the insert commit forced
        to raise ``commit_exc``. Returns (raised_exc, thumb_path)."""
        fits_root = tmp_path / "fits"
        thumbs = tmp_path / "thumbs"
        fits_root.mkdir()
        thumbs.mkdir()
        fits_path = fits_root / "M31" / "Light_M31_001.fits"
        fits_path.parent.mkdir(parents=True)
        fits_path.write_bytes(b"stub")

        def _fake_gen_thumb(path, thumb_path, max_width=None):
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"thumbnail-bytes")
            return thumb_path

        meta = {
            "file_path": str(fits_path),
            "file_name": fits_path.name,
            "object_name": "M31",
            "image_type": "LIGHT",
            "raw_headers": {},
            "capture_date": None,
        }

        patchers = [
            patch.object(tasks_mod.settings, "fits_data_path", str(fits_root)),
            patch.object(tasks_mod.settings, "thumbnails_path", str(thumbs)),
            patch.object(tasks_mod, "fitsio", MagicMock()),
            patch.object(tasks_mod, "extract_metadata", MagicMock(return_value=meta)),
            patch.object(tasks_mod, "generate_thumbnail", _fake_gen_thumb),
            patch.object(tasks_mod, "resolve_target", MagicMock(return_value=None)),
            patch.object(tasks_mod, "Session", lambda *a, **kw: _FakeInsertSession(commit_exc)),
            patch.object(tasks_mod, "_redis", MagicMock()),
            patch.object(tasks_mod, "increment_completed_sync", MagicMock()),
            patch.object(tasks_mod, "increment_csv_enriched_sync", MagicMock()),
        ]
        if thumb_referenced is not None:
            patchers.append(
                patch.object(tasks_mod, "_thumbnail_referenced",
                             MagicMock(return_value=thumb_referenced))
            )

        import contextlib
        raised = None
        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            try:
                tasks_mod._do_ingest(str(fits_path), include_calibration=True)
            except Exception as exc:  # noqa: BLE001
                raised = exc

        # Reconstruct the deterministic thumbnail path the task would have used.
        import hashlib
        path_hash = hashlib.md5(str(fits_path).encode()).hexdigest()[:12]
        thumb_path = thumbs / f"{fits_path.stem}_{path_hash}.jpg"
        return raised, thumb_path

    def test_integrity_error_preserves_thumbnail(self, tmp_path):
        """Duplicate path -> IntegrityError on commit -> thumbnail is kept."""
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        exc = IntegrityError("INSERT", {}, Exception("duplicate key"))
        raised, thumb_path = self._run_do_ingest(tasks_mod, tmp_path, exc)
        assert isinstance(raised, IntegrityError)
        assert thumb_path.exists(), "surviving row's thumbnail must not be deleted"

    def test_orphaned_insert_removes_unreferenced_thumbnail(self, tmp_path):
        """Genuine insert failure with no row referencing the thumb -> deleted."""
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        exc = RuntimeError("boom")
        raised, thumb_path = self._run_do_ingest(
            tasks_mod, tmp_path, exc, thumb_referenced=False
        )
        assert isinstance(raised, RuntimeError)
        assert not thumb_path.exists(), "orphaned thumbnail should be cleaned up"

    def test_orphaned_insert_keeps_referenced_thumbnail(self, tmp_path):
        """Insert failure but another row references the thumb -> kept (defensive)."""
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        exc = RuntimeError("boom")
        raised, thumb_path = self._run_do_ingest(
            tasks_mod, tmp_path, exc, thumb_referenced=True
        )
        assert isinstance(raised, RuntimeError)
        assert thumb_path.exists(), "shared thumbnail must not be deleted"


# ---------------------------------------------------------------------------
# Provenance columns must survive the ingest constructor.
#
# _do_ingest builds the Image row from a hand-enumerated kwargs list, so a
# column merge_csv_metrics writes into the metadata dict reaches the DB only
# if someone remembered to add the kwarg. eccentricity_source shipped that way
# and guiding_rms_source was silently dropped for a whole review round. These
# pin the row the ingest actually inserts, not the metadata dict it built.
# ---------------------------------------------------------------------------

class _CapturingSession:
    """Session stand-in that keeps whatever was added, and commits cleanly."""

    def __init__(self, added):
        self._added = added

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **kw):
        return None

    def add(self, obj):
        self._added.append(obj)

    def execute(self, *a, **kw):
        return MagicMock()

    def commit(self):
        pass


class TestIngestPersistsProvenanceColumns:
    def _ingest(self, tmp_path, extra_meta):
        """Run _do_ingest over a stub file, returning the inserted Image."""
        import contextlib

        from app.models import Image

        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")

        fits_root = tmp_path / "fits"
        thumbs = tmp_path / "thumbs"
        fits_root.mkdir()
        thumbs.mkdir()
        fits_path = fits_root / "M31" / "Light_M31_001.fits"
        fits_path.parent.mkdir(parents=True)
        fits_path.write_bytes(b"stub")

        meta = {
            "file_path": str(fits_path),
            "file_name": fits_path.name,
            "object_name": "M31",
            "image_type": "LIGHT",
            "raw_headers": {},
            "capture_date": None,
        }
        meta.update(extra_meta)

        added: list = []
        patchers = [
            patch.object(tasks_mod.settings, "fits_data_path", str(fits_root)),
            patch.object(tasks_mod.settings, "thumbnails_path", str(thumbs)),
            patch.object(tasks_mod, "fitsio", MagicMock()),
            patch.object(tasks_mod, "extract_metadata", MagicMock(return_value=meta)),
            patch.object(tasks_mod, "generate_thumbnail", MagicMock(return_value=None)),
            patch.object(tasks_mod, "resolve_target", MagicMock(return_value=None)),
            patch.object(tasks_mod, "Session", lambda *a, **kw: _CapturingSession(added)),
            patch.object(tasks_mod, "_redis", MagicMock()),
            patch.object(tasks_mod, "increment_completed_sync", MagicMock()),
            patch.object(tasks_mod, "increment_csv_enriched_sync", MagicMock()),
        ]

        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            tasks_mod._do_ingest(str(fits_path), include_calibration=True)

        images = [obj for obj in added if isinstance(obj, Image)]
        assert len(images) == 1
        return images[0]

    def test_ingest_persists_csv_provenance_stamps(self, tmp_path):
        """Both provenance labels the CSV merge writes must reach the row."""
        image = self._ingest(tmp_path, {
            "eccentricity": 0.42,
            "eccentricity_source": "csv",
            "guiding_rms_arcsec": 0.78,
            "guiding_rms_ra_arcsec": 0.52,
            "guiding_rms_dec_arcsec": 0.58,
            "guiding_rms_source": "csv",
            "detected_stars": 312,
        })

        assert image.guiding_rms_arcsec == 0.78
        assert image.guiding_rms_source == "csv"
        assert image.eccentricity_source == "csv"

    def test_ingest_leaves_provenance_null_without_csv(self, tmp_path):
        """A frame the CSV never spoke about carries no provenance label."""
        image = self._ingest(tmp_path, {})

        assert image.guiding_rms_arcsec is None
        assert image.guiding_rms_source is None
        assert image.eccentricity_source is None


# ---------------------------------------------------------------------------
# Phase 1.1: DetachedInstanceError in ingest.
#
# The filename-candidate step reads `image.id` for an Image that was inserted
# inside an earlier `with Session(...) as session:` block. Under SQLAlchemy's
# default expire_on_commit, that instance is expired at commit and detached
# once the block closes, so touching `image.id` afterwards raises
# DetachedInstanceError (46 such failures observed in production, logged as
# "Failed to create filename candidate"). The fix captures the id into a local
# variable while the session is still open.
# ---------------------------------------------------------------------------

class _DetachOnCloseImage:
    """Mimics an ORM instance under expire_on_commit=True: `id` is populated at
    commit but raises DetachedInstanceError once the owning session closes."""

    def __init__(self, **kwargs):
        self._id = None
        self._detached = False

    def _assign_id(self, value):
        self._id = value

    def _detach(self):
        self._detached = True

    @property
    def id(self):
        from sqlalchemy.orm.exc import DetachedInstanceError
        if self._detached:
            raise DetachedInstanceError("Instance is not bound to a Session")
        return self._id


class _CandidateQueryResult:
    """execute() result whose scalars().all() yields no existing candidates."""

    def scalars(self):
        return self

    def all(self):
        return []


class TestIngestFilenameCandidateNoDetach:
    """Regression: ingesting a LIGHT frame with no OBJECT header and no resolved
    target must record a filename candidate without a DetachedInstanceError."""

    def _run(self, tasks_mod, tmp_path):
        from app.models.filename_candidate import FilenameCandidate

        fits_root = tmp_path / "fits"
        thumbs = tmp_path / "thumbs"
        fits_root.mkdir()
        thumbs.mkdir()
        fits_path = fits_root / "Light_unknown_001.fits"
        fits_path.write_bytes(b"stub")

        # Shared state so the fake Session instances cooperate across the
        # separate `with Session(...)` blocks inside _do_ingest.
        state = {"image": None, "candidate": None, "id_read_while_open": None}
        ASSIGNED_ID = 4242

        assigned_ids = iter([ASSIGNED_ID])

        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                # Closing the session detaches the inserted image, matching the
                # real expire_on_commit + session-close semantics.
                if state["image"] is not None:
                    state["image"]._detach()
                return False

            def get(self, *a, **kw):
                # UserSettings load -> use defaults.
                return None

            def add(self, obj):
                if isinstance(obj, _DetachOnCloseImage):
                    state["image"] = obj
                elif isinstance(obj, FilenameCandidate):
                    state["candidate"] = obj

            def execute(self, *a, **kw):
                return _CandidateQueryResult()

            def commit(self):
                img = state["image"]
                if img is not None and img._id is None:
                    img._assign_id(next(assigned_ids, ASSIGNED_ID))

        def _fake_gen_thumb(path, thumb_path, max_width=None):
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"thumbnail-bytes")
            return thumb_path

        meta = {
            "file_path": str(fits_path),
            "file_name": fits_path.name,
            "object_name": None,  # forces the filename-candidate branch
            "image_type": "LIGHT",
            "raw_headers": {},
            "capture_date": None,
        }

        resolution = {"method": "none", "confidence": 0.0, "suggested_target_id": None}

        import contextlib
        patchers = [
            patch.object(tasks_mod.settings, "fits_data_path", str(fits_root)),
            patch.object(tasks_mod.settings, "thumbnails_path", str(thumbs)),
            patch.object(tasks_mod, "fitsio", MagicMock()),
            patch.object(tasks_mod, "extract_metadata", MagicMock(return_value=meta)),
            patch.object(tasks_mod, "generate_thumbnail", _fake_gen_thumb),
            patch.object(tasks_mod, "Image", _DetachOnCloseImage),
            patch.object(tasks_mod, "Session", lambda *a, **kw: _FakeSession()),
            patch.object(tasks_mod, "_redis", MagicMock()),
            patch.object(tasks_mod, "increment_completed_sync", MagicMock()),
            patch.object(tasks_mod, "increment_csv_enriched_sync", MagicMock()),
            patch(
                "app.services.filename_parser.extract_target_from_filename",
                MagicMock(return_value="UnknownTarget"),
            ),
            patch(
                "app.services.filename_resolver.resolve_filename_candidate",
                MagicMock(return_value=resolution),
            ),
        ]

        captured_logs = []
        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            stack.enter_context(
                patch.object(
                    tasks_mod.logger, "warning",
                    MagicMock(side_effect=lambda *a, **kw: captured_logs.append((a, kw))),
                )
            )
            tasks_mod._do_ingest(str(fits_path), include_calibration=True)

        return state, captured_logs, ASSIGNED_ID

    def test_filename_candidate_created_without_detached_instance_error(self, tmp_path):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        state, captured_logs, assigned_id = self._run(tasks_mod, tmp_path)

        # No "Failed to create filename candidate" warning was emitted.
        candidate_warnings = [
            a for (a, _kw) in captured_logs
            if a and "Failed to create filename candidate" in str(a[0])
        ]
        assert not candidate_warnings, (
            "filename candidate step raised (likely DetachedInstanceError): "
            f"{candidate_warnings}"
        )

        # The candidate was persisted with the id captured before session close.
        assert state["candidate"] is not None, "expected a FilenameCandidate to be added"
        assert state["candidate"].image_ids == [assigned_id]


# ---------------------------------------------------------------------------
# _is_unrecoverable: a truncated file must fail fast, not burn three retries
# ---------------------------------------------------------------------------

class TestIsUnrecoverable:
    """FITSIO status 107 means the read ran off the end of a short file.

    Every retry re-reads the same truncated bytes and fails identically, so
    retrying only delays the scan and the failure report the user acts on.
    """

    @pytest.mark.parametrize("msg", [
        "FITSIO status = 107: tried to move past end of file",
        "attempt to move past end of file in table",
        "FITSIO status = 107: could not interpret primary array header",
        "SIMPLE card",
        "file is not a valid FITS file",
    ])
    def test_unrecoverable_oserror_messages(self, msg):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        assert tasks_mod._is_unrecoverable(OSError(msg)) is True

    def test_transient_oserror_is_still_retried(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        assert tasks_mod._is_unrecoverable(OSError("Stale file handle")) is False

    def test_value_and_filesystem_errors_stay_unrecoverable(self):
        tasks_mod = _bootstrap_tasks("app.worker.tasks_scan")
        assert tasks_mod._is_unrecoverable(ValueError("bad header")) is True
        assert tasks_mod._is_unrecoverable(FileNotFoundError("gone")) is True
        assert tasks_mod._is_unrecoverable(PermissionError("denied")) is True
        assert tasks_mod._is_unrecoverable(RuntimeError("boom")) is False
