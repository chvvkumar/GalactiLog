"""The correlation task: registration, dispatch seams, and best-effort queuing.

The task itself is thin - correlate_dates does the work - so these tests pin
the things a thin wrapper still gets wrong: date values that cannot cross a
JSON broker, a dispatch failure that takes an otherwise complete scan down
with it, and an activity feed that gains a row on every idle scan.
"""
from datetime import date

import pytest


def test_the_task_is_registered_under_the_facade_name():
    from app.worker.tasks_phd2 import correlate_phd2_images

    assert correlate_phd2_images.name == "app.worker.tasks.correlate_phd2_images"


def test_dates_cross_the_broker_as_strings(monkeypatch):
    """Celery kwargs are JSON-serialised; a datetime.date does not survive."""
    from app.worker import tasks_phd2

    captured = {}

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Task)
    tasks_phd2._dispatch_correlation({date(2026, 7, 14), date(2026, 7, 13)}, 7)

    # Widened by a day either way, so two adjacent guide nights become the
    # four-night run 07-12 .. 07-15. See the widening test below.
    assert captured["kwargs"]["dates"] == [
        "2026-07-12", "2026-07-13", "2026-07-14", "2026-07-15",
    ]
    assert captured["kwargs"]["parent_activity_id"] == 7


def test_the_dispatch_widens_each_night_by_a_day_either_way(monkeypatch):
    """Every re-derive dispatch hands over Phd2Session.session_date values and
    correlate_dates consumes them as Image.session_date. Those are two
    different date spaces: with observer_longitude unset, which is the
    default, guide sessions group by UTC midnight while images group by local
    solar noon, so a session dated D covers images on D-1. The fill path
    widens for exactly this reason (phd2_correlation._dates_needing_fill); the
    re-derive path has to widen too or the frames it means to clear are on a
    night it never visits."""
    from app.worker import tasks_phd2

    captured = {}

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Task)
    tasks_phd2._dispatch_correlation({date(2026, 7, 14)})

    assert captured["kwargs"]["dates"] == [
        "2026-07-13", "2026-07-14", "2026-07-15",
    ]


def test_incremental_dispatch_passes_no_dates(monkeypatch):
    from app.worker import tasks_phd2

    captured = {}

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Task)
    tasks_phd2._dispatch_correlation(None)
    assert captured["kwargs"]["dates"] is None


def test_a_dispatch_failure_does_not_escape(monkeypatch):
    """Correlation is auxiliary. A broker problem at this one call must not
    fail the guide-log pass that has already committed its work."""
    from app.worker import tasks_phd2

    class _Broken:
        @staticmethod
        def apply_async(**kwargs):
            raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Broken)
    tasks_phd2._dispatch_correlation([date(2026, 7, 14)])  # must not raise


def test_unparsable_dates_are_dropped_not_fatal(monkeypatch):
    """A date string from an older queued message must not kill the pass."""
    from app.services.phd2_correlation import CorrelationResult
    from app.worker import tasks_phd2

    seen = {}

    def _fake_correlate(db, dates, **kwargs):
        seen["dates"] = dates
        return CorrelationResult()

    monkeypatch.setattr(
        "app.services.phd2_correlation.correlate_dates", _fake_correlate
    )
    monkeypatch.setattr(tasks_phd2, "_invalidate_stats_cache", lambda: None)
    monkeypatch.setattr(tasks_phd2, "_emit_correlation_activity", lambda *a, **k: None)
    tasks_phd2.correlate_phd2_images(dates=["2026-07-14", "not-a-date"])
    assert seen["dates"] == [date(2026, 7, 14)]


def test_the_facade_reexports_the_task():
    import ast
    import pathlib

    facade = pathlib.Path(__file__).resolve().parents[1] / "app" / "worker" / "tasks.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "app.worker.tasks_phd2"
        for alias in node.names
    }
    assert "correlate_phd2_images" in imported


def test_the_guide_log_pass_chains_correlation_for_the_nights_it_touched():
    """A re-ingested log invalidates the values derived from its old contents,
    so the nights it touched have to be re-derived, not just topped up."""
    import inspect

    from app.worker import tasks_phd2

    source = inspect.getsource(tasks_phd2._run_phd2_pass)
    assert "_dispatch_correlation" in source
    assert "touched_dates" in source


def test_a_profile_remap_re_derives_every_affected_night():
    """Re-keying sessions changes which rig a frame's guiding came from, and
    incremental mode would never revisit a frame that already has a value."""
    import inspect

    from app.worker import tasks_phd2

    source = inspect.getsource(tasks_phd2._run_phd2_pass)
    assert "affected_dates" in source


def test_the_image_scan_seams_chain_the_incremental_pass():
    import inspect

    from app.services import scan_state
    from app.worker import tasks_scan

    assert "correlate_phd2_images" in inspect.getsource(scan_state.check_complete_sync)
    assert "correlate_phd2_images" in inspect.getsource(tasks_scan.run_scan)


# --- live guide-log progress ------------------------------------------------

def test_the_pass_publishes_its_candidate_total_before_it_starts_work():
    """The scan screen counts "N of M" while the pass runs. Publishing M only
    in the final write means the pass reports 0 of 0 for its whole lifetime,
    which is what it did."""
    import inspect

    from app.worker import tasks_phd2

    source = inspect.getsource(tasks_phd2._run_phd2_pass)
    publish_at = source.index("set_phd2_found_sync")
    loop_at = source.index("for path in candidates:")
    final_at = source.index("set_phd2_counts_sync")
    assert publish_at < loop_at < final_at


def test_per_file_progress_is_reported_from_inside_the_ingest_loop():
    import inspect

    from app.worker import tasks_phd2

    source = inspect.getsource(tasks_phd2._run_phd2_pass)
    loop_at = source.index("for path in candidates:")
    increment_at = source.index("increment_phd2_progress_sync")
    final_at = source.index("set_phd2_counts_sync")
    assert loop_at < increment_at < final_at


def test_a_settings_pass_publishes_no_scan_progress(monkeypatch):
    """A settings-triggered pass is not a scan. Writing scan progress from one
    made the panel report a scan that never ran, which is the same reason the
    final counter write is gated on `scanned`."""
    from app.worker import tasks_phd2

    written = []
    monkeypatch.setattr(
        tasks_phd2, "set_phd2_found_sync",
        lambda r, found: written.append(("found", found)),
    )
    monkeypatch.setattr(
        tasks_phd2, "increment_phd2_progress_sync",
        lambda r, **kw: written.append(("progress", kw)),
    )
    monkeypatch.setattr(tasks_phd2, "_stored_log_paths", lambda: [])
    monkeypatch.setattr(
        tasks_phd2, "_read_settings",
        lambda: tasks_phd2.GeneralSettings(phd2_scan_enabled=True),
    )
    monkeypatch.setattr(tasks_phd2, "_invalidate_stats_cache", lambda: None)
    tasks_phd2._run_phd2_pass(force=True)
    assert written == []
