"""Background-task activity events carry a readable reason plus raw error details."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.upstream import human_error


class FakeUpstreamError(Exception):
    """Mimics catalog_cache.NonTransientError, matched structurally by name."""


FakeUpstreamError.__name__ = "NonTransientError"
READABLE = "SIMBAD is unavailable: simbad.cds.unistra.fr returned HTTP 404 (Not Found)"


def _upstream_exc():
    try:
        try:
            raise ConnectionError("socket closed")
        except ConnectionError as cause:
            raise FakeUpstreamError(READABLE) from cause
    except FakeUpstreamError as exc:
        return exc


def _assert_details(details):
    assert details["exception_type"] == "NonTransientError"
    assert details["exception"] == READABLE
    assert "ConnectionError: socket closed" in details["error_chain"]
    json.dumps(details)


def test_human_error_reads_upstream_message():
    assert human_error(_upstream_exc()) == READABLE


def test_task_event_message_and_details(monkeypatch):
    import app.worker.celery_app as cmod

    captured = {}

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        captured.update(message=message, details=kw["details"])

    monkeypatch.setattr("app.services.activity.emit_sync", fake_emit_sync)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("app.config.get_sync_redis", lambda: MagicMock())
    monkeypatch.setattr(cmod, "_task_event_engine", None, raising=False)

    cmod._emit_task_event("task_failure", "error", "app.worker.tasks.x", "id1", _upstream_exc())

    assert captured["message"] == f"Background task 'app.worker.tasks.x' failed: {READABLE}"
    assert captured["details"]["task"] == "app.worker.tasks.x"
    _assert_details(captured["details"])


def test_reference_catalog_failure_message_and_details():
    import app.worker.tasks_migrations as tm

    emit = MagicMock()
    with patch.object(tm, "_redis", MagicMock()), \
            patch.object(tm, "Session", MagicMock()), \
            patch.object(tm, "_activity_session", MagicMock()), \
            patch.object(tm, "_emit_activity_sync", emit), \
            patch("app.services.data_migrations.reference_catalogs_are_empty", return_value=True), \
            patch("app.services.data_migrations.load_reference_catalogs", side_effect=_upstream_exc()):
        result = tm.load_reference_catalogs_if_empty.run()

    assert result["status"] == "error"
    kw = emit.call_args.kwargs
    assert kw["event_type"] == "reference_catalog_load_failed"
    assert kw["message"] == f"Reference catalog load failed: {READABLE}"
    _assert_details(kw["details"])


def test_data_upgrade_failure_message_and_details():
    import app.worker.tasks_migrations as tm

    def boom(session):
        raise _upstream_exc()

    emit = MagicMock()
    with patch.object(tm, "_redis", MagicMock()), \
            patch.object(tm, "Session", MagicMock()), \
            patch.object(tm, "_activity_session", MagicMock()), \
            patch.object(tm, "_emit_activity_sync", emit), \
            patch.object(tm, "_pickup_data_migration_job"), \
            patch.object(tm, "_update_data_migration_job"), \
            patch("app.services.data_migrations.get_pending_migrations",
                  return_value=[(14, "fake step", boom)]):
        result = tm.run_data_migrations.run(from_version=13)

    assert result["status"] == "error"
    kw = emit.call_args.kwargs
    assert kw["event_type"] == "data_upgrade_failed"
    assert kw["message"] == f"Data upgrade failed at v14 (fake step): {READABLE}. Press Quick Fix to retry."
    assert kw["details"]["version"] == 14
    _assert_details(kw["details"])


@pytest.mark.asyncio
async def test_mosaic_composite_failure_message_and_details():
    from app.services import mosaic_composite as mc

    captured = {}

    async def fake_emit(db, *, category, severity, event_type, message, **kw):
        captured.update(message=message, details=kw["details"])

    async def failing_select(*a, **kw):
        raise _upstream_exc()

    with patch.object(mc, "_emit_activity", fake_emit),             patch.object(mc, "select_best_frame", failing_select):
        with pytest.raises(FakeUpstreamError):
            await mc.build_mosaic_composite("mosaic-x", [MagicMock()], MagicMock())

    assert captured["message"] == f"Mosaic composite generation failed: {READABLE}"
    assert captured["details"]["mosaic_id"] == "mosaic-x"
    _assert_details(captured["details"])


def test_failure_reasons_group_by_cause_without_name():
    import json
    from app.services import catalog_cache as cc
    from app.worker import tasks_target_rebuild as tr

    def exc(key):
        err = cc.NonTransientError(
            f"SIMBAD lookup for '{key}' failed: {READABLE}", source="simbad", key=key,
            original=ConnectionError("socket closed"),
        )
        err.__cause__ = err.original
        return err

    reasons = {}
    tr._record_failure(reasons, "IC 1396", exc("IC 1396"))
    tr._record_failure(reasons, "M 31", exc("M 31"))
    tr._record_failure(reasons, "NGC 7000", ValueError("odd"))

    suffix, items = tr._failure_summary(reasons)

    assert suffix == f". Most common reason: {READABLE}"
    assert items[0]["reason"] == READABLE
    assert items[0]["count"] == 2
    assert items[0]["example_name"] == "IC 1396"
    assert items[0]["exception_type"] == "NonTransientError"
    assert "ConnectionError: socket closed" in items[0]["error_chain"]
    assert items[1]["count"] == 1 and items[1]["reason"].startswith("ValueError")
    json.dumps(items)
    assert tr._failure_summary({}) == ("", [])


def test_outage_is_run_context_not_a_per_name_reason(monkeypatch):
    import json
    from app.worker import tasks_target_rebuild as tr

    monkeypatch.setattr(tr.cc, "outage", lambda src: READABLE if src == "simbad" else None)
    outages = {}
    tr._observe_outages(outages)
    # A later reason must not overwrite the first one seen.
    monkeypatch.setattr(tr.cc, "outage", lambda src: "other" if src == "simbad" else None)
    tr._observe_outages(outages)
    assert outages == {"simbad": READABLE}

    suffix, items = tr._failure_summary({}, outages)

    # Names that failed without an exception get no reason of their own.
    assert items == []
    assert "Most common reason" not in suffix
    assert suffix == (
        f". SIMBAD was unavailable during this run ({READABLE}), so some of these "
        f"names could not be checked and may resolve on a later run."
    )
    json.dumps(outages)


def test_unresolvable_name_gets_no_outage_reason_when_catalogs_are_up(monkeypatch):
    from app.worker import tasks_target_rebuild as tr

    monkeypatch.setattr(tr.cc, "outage", lambda src: None)
    outages = {}
    tr._observe_outages(outages)

    assert outages == {}
    assert tr._failure_summary({}, outages) == ("", [])


def _run_dedup(monkeypatch, simbad_side_effect, outage):
    from app.services import catalog_cache as cc
    from app.worker import tasks_target_dedup as td

    db = MagicMock()
    session_cm = MagicMock()
    session_cm.__enter__.return_value = db
    unresolved = MagicMock()
    unresolved.all.return_value = [("IC 1396", 3), ("M 31", 2)]
    existing = MagicMock()
    existing.all.return_value = []
    stop = RuntimeError("stop after pass 1")
    db.execute.side_effect = [unresolved, existing, stop]

    emit = MagicMock()
    monkeypatch.setattr(td, "Session", lambda *a, **k: session_cm)
    monkeypatch.setattr(td, "_redis", MagicMock())
    monkeypatch.setattr(td, "_activity_session", MagicMock())
    monkeypatch.setattr(td, "_emit_activity_sync", emit)
    monkeypatch.setattr(cc, "outage", lambda src: outage, raising=False)
    monkeypatch.setattr("app.services.simbad.resolve_target_name_cached", simbad_side_effect)
    with pytest.raises(RuntimeError, match="stop after pass 1"):
        td.detect_duplicate_targets.run()
    return db, emit


def test_dedup_skips_names_on_upstream_error(monkeypatch):
    from app.services import catalog_cache as cc

    def raising(name, db):
        try:
            raise ConnectionError("socket closed")
        except ConnectionError as cause:
            raise cc.NonTransientError(READABLE, source="simbad", key=name) from cause

    db, emit = _run_dedup(monkeypatch, raising, None)

    db.add.assert_not_called()
    assert emit.call_count == 1
    kw = emit.call_args.kwargs
    assert kw["severity"] == "warning"
    assert kw["message"] == (
        f"Duplicate detection skipped 2 object names because SIMBAD is unavailable: "
        f"{READABLE}. They will be checked on the next run."
    )
    assert kw["details"]["skipped"] == 2
    assert kw["details"]["example_names"] == ["IC 1396", "M 31"]
    _assert_details(kw["details"])


def test_dedup_skips_names_during_outage_without_orphan_candidates(monkeypatch):
    db, emit = _run_dedup(monkeypatch, lambda name, db: None, READABLE)

    db.add.assert_not_called()
    kw = emit.call_args.kwargs
    assert READABLE in kw["message"]
    assert kw["details"]["skipped"] == 2
    assert "exception_type" not in kw["details"]
    json.dumps(kw["details"])
