"""Ingest behaviour for PHD2 guide logs: idempotency, empty files, orphans."""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

from app.schemas.settings import GeneralSettings  # noqa: E402

TEST_MARK = "zzphd2ingesttest"

SAMPLE_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-07-14 20:13:33

Guiding Begins at 2026-07-14 21:42:27
Equipment Profile = AM5n_OAG_ASI174M
Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm
 Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, have dark, dark dur = 500, no defect map, pixel size = 5.9 um
Exposure = 500 ms
RA = 20.22 hr, Dec = 38.5 deg, Hour angle = -4.02 hr, Pier side = West, Rotator pos = N/A, Alt = 43.7 deg, Az = 70.4 deg
Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,YStep,StarMass,SNR,ErrorCode
1,1.228,"Mount",0.330,0.544,0.556,-0.189,0.350,0.000,98,W,0,,,,1713,28.59,1
2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0
Guiding Ends at 2026-07-14 21:42:46

Log Summary: calcnt:0 gcnt:1 gdur:19 gacnt:2
Log closed at 2026-07-14 21:43:00
"""

EMPTY_LOG = """PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at 2026-01-19 17:21:18
INFO: Guiding parameter change, MultiStar = true

Log Summary: calcnt:0 gcnt:0 gdur:0 gacnt:0
Log closed at 2026-01-19 17:21:51
"""


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

    def _clean():
        with Session() as s:
            s.execute(
                text("DELETE FROM phd2_logs WHERE file_path LIKE :p"),
                {"p": f"%{TEST_MARK}%"},
            )
            s.commit()

    _clean()
    yield Session
    _clean()
    engine.dispose()


@pytest.fixture
def log_file(tmp_path):
    d = tmp_path / TEST_MARK
    d.mkdir()
    return d / "PHD2_GuideLog_2026-07-14_201333.txt"


def _settings(**kw):
    base = dict(
        observer_timezone="America/New_York",
        phd2_scan_enabled=True,
        phd2_profile_map={"AM5n_OAG_ASI174M": "140APO"},
        use_imaging_night=True,
        observer_longitude=-80.0,
    )
    base.update(kw)
    return GeneralSettings(**base)


def test_ingest_creates_log_session_and_frames(db, log_file):
    from app.models.phd2 import Phd2Frame, Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "ok"

    with db() as s:
        log = s.execute(
            select(Phd2Log).where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert log.parse_status == "ok"
        assert log.session_count == 1
        assert log.phd2_version == "2.6.14"
        session = s.execute(
            select(Phd2Session).where(Phd2Session.log_id == log.id)
        ).scalar_one()
        assert session.equipment_profile == "AM5n_OAG_ASI174M"
        assert session.telescope == "140APO"
        assert session.frame_count == 2
        assert session.pixel_scale_arcsec == 1.54
        frames = s.execute(
            select(Phd2Frame).where(Phd2Frame.session_id == session.id)
        ).scalars().all()
        assert len(frames) == 2
        assert frames[0].ra_direction == "W"


def test_reingest_is_skipped_when_size_and_mtime_are_unchanged(db, log_file):
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "ok"
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "unchanged"


def test_changed_file_is_reparsed_without_duplicating_rows(db, log_file):
    from app.models.phd2 import Phd2Frame, Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        ingest_phd2_log(s, str(log_file), _settings())

    grown = SAMPLE_LOG.replace(
        '2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0',
        '2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0\n'
        '3,3.149,"Mount",-0.139,-0.706,-0.710,-0.035,-0.448,0.000,125,E,0,,,,1888,29.97,1',
    )
    log_file.write_text(grown, encoding="utf-8")
    os.utime(log_file, (log_file.stat().st_atime, log_file.stat().st_mtime + 100))

    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "ok"
    with db() as s:
        assert s.execute(
            select(func.count()).select_from(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one() == 1
        session = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert session.frame_count == 3
        assert s.execute(
            select(func.count()).select_from(Phd2Frame)
            .where(Phd2Frame.session_id == session.id)
        ).scalar_one() == 3


def test_data_free_log_gets_a_zero_session_row_and_is_not_retried(db, log_file):
    from app.models.phd2 import Phd2Log
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(EMPTY_LOG, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "empty"
    with db() as s:
        log = s.execute(
            select(Phd2Log).where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert log.parse_status == "empty"
        assert log.session_count == 0
        assert log.run_count == 1
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "unchanged"


def test_unmapped_profile_leaves_telescope_null(db, log_file):
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        ingest_phd2_log(s, str(log_file), _settings(phd2_profile_map={}))
    with db() as s:
        session = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert session.telescope is None


def test_apply_profile_map_rewrites_existing_sessions(db, log_file):
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import apply_profile_map, ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        ingest_phd2_log(s, str(log_file), _settings(phd2_profile_map={}))
    with db() as s:
        changed = apply_profile_map(s, {"AM5n_OAG_ASI174M": "RedCat 51"})
        s.commit()
        assert changed >= 1
    with db() as s:
        session = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert session.telescope == "RedCat 51"


def test_unreadable_file_is_failed_without_recording_a_row(db, log_file):
    """A file that cannot even be stat'd writes nothing, so the next pass
    retries it rather than remembering it as permanently broken."""
    from app.models.phd2 import Phd2Log
    from app.worker.tasks_phd2 import ingest_phd2_log

    missing = str(log_file) + ".gone"
    with db() as s:
        assert ingest_phd2_log(s, missing, _settings()) == "failed"
    with db() as s:
        assert s.execute(
            select(Phd2Log).where(Phd2Log.file_path == missing)
        ).scalar_one_or_none() is None


def _stored_start(session_factory, path):
    from app.models.phd2 import Phd2Log, Phd2Session

    with session_factory() as s:
        return s.execute(
            select(Phd2Session).join(Phd2Log).where(Phd2Log.file_path == str(path))
        ).scalar_one().started_at_utc


def test_forced_ingest_reparses_an_unchanged_file_under_the_new_timezone(db, log_file):
    """The whole point of the force flag: PHD2 never rewrites a closed log, so
    without it a corrected observer timezone could never reach stored rows."""
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "ok"
    before = _stored_start(db, log_file)

    corrected = _settings(observer_timezone="UTC")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), corrected) == "unchanged"
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), corrected, force=True) == "ok"

    after = _stored_start(db, log_file)
    # 21:42 local on 2026-07-14 is 01:42Z under America/New_York (UTC-4 in
    # July) and 21:42Z under UTC.
    assert (before - after).total_seconds() == 4 * 3600


def test_forced_scan_reparses_stored_logs_while_scanning_is_disabled(db, log_file, monkeypatch):
    """A timezone correction is a fix to data already in the catalog, so it
    must not be gated on the discovery toggle, and it needs no walk: the
    candidate list is every log path already stored."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert tasks_phd2.ingest_phd2_log(s, str(log_file), _settings()) == "ok"
    before = _stored_start(db, log_file)

    corrected = _settings(observer_timezone="UTC", phd2_scan_enabled=False)
    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: corrected)
    monkeypatch.setattr(tasks_phd2, "set_phd2_counts_sync", lambda *a, **kw: None)
    monkeypatch.setattr(tasks_phd2, "_emit_activity_sync", lambda *a, **kw: None)

    result = tasks_phd2.scan_phd2_logs(force=True)
    assert result["status"] == "complete"
    assert result["ingested"] >= 1

    after = _stored_start(db, log_file)
    assert (before - after).total_seconds() == 4 * 3600


def test_remap_applies_while_scanning_is_disabled(db, log_file, monkeypatch):
    """Re-keying touches no filesystem, so the scan toggle must not silence a
    profile-map edit."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings(phd2_profile_map={}))

    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: _settings(
        phd2_scan_enabled=False,
        phd2_profile_map={"AM5n_OAG_ASI174M": "RedCat 51"},
    ))
    result = tasks_phd2.scan_phd2_logs(remap_only=True)
    assert result["status"] == "remapped"

    with db() as s:
        session = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert session.telescope == "RedCat 51"


def _isolate_log_table(db):
    """Empty phd2_logs so the missing-fraction guard measures only this test.

    The guard is deliberately global: it compares every stored log against the
    disk. Rows left behind by a crashed earlier run would therefore move both
    the numerator and the denominator. Every module that seeds this table
    clears its own rows before use, so emptying it here strands nothing.
    """
    with db() as s:
        s.execute(text("DELETE FROM phd2_logs"))
        s.commit()


def _ingest_files(db, directory, count):
    from app.worker.tasks_phd2 import ingest_phd2_log

    paths = []
    for index in range(count):
        path = directory / f"PHD2_GuideLog_2026-07-1{index}_201333.txt"
        path.write_text(SAMPLE_LOG, encoding="utf-8")
        with db() as s:
            assert ingest_phd2_log(s, str(path), _settings()) == "ok"
        paths.append(path)
    return paths


def _row_exists(db, path):
    from app.models.phd2 import Phd2Log

    with db() as s:
        return s.execute(
            select(Phd2Log).where(Phd2Log.file_path == str(path))
        ).scalar_one_or_none() is not None


def test_cleanup_orphans_drops_rows_whose_file_is_gone(db, log_file):
    """The only destructive operation in the module: existence on disk is the
    sole test, so a log still present survives a pass and a deleted one does
    not."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    kept_a, kept_b, gone = _ingest_files(db, log_file.parent, 3)

    with db() as s:
        assert _cleanup_orphans(s) == 0
    assert _row_exists(db, gone)

    gone.unlink()
    with db() as s:
        assert _cleanup_orphans(s) == 1
    assert not _row_exists(db, gone)
    assert _row_exists(db, kept_a)
    assert _row_exists(db, kept_b)


def test_cleanup_orphans_is_skipped_when_the_library_vanishes(db, log_file):
    """An unmounted share fails every existence test at once. The image
    scanner refuses to purge past the same 50%-missing line, and this is the
    module's only destructive operation, so it refuses too."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    paths = _ingest_files(db, log_file.parent, 3)
    for path in paths:
        path.unlink()

    notices = []
    with db() as s:
        assert _cleanup_orphans(s, notices) == 0
    assert [t for t, _ in notices] == ["phd2_orphan_warning"]
    assert "unmounted share" in notices[0][1]
    for path in paths:
        assert _row_exists(db, path)


def test_a_forced_admin_cleanup_deletes_past_the_guard(db, log_file):
    """The guard catches an accident; it must not overrule an admin who has
    said they deleted the files on purpose. Without the bypass a genuinely
    emptied log directory could never be cleared from the catalog."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    paths = _ingest_files(db, log_file.parent, 3)
    for path in paths:
        path.unlink()

    notices = []
    with db() as s:
        assert _cleanup_orphans(s, notices, force=True) == 3
    for path in paths:
        assert not _row_exists(db, path)
    assert [t for t, _ in notices] == ["phd2_orphan_force_warning"]


def _capture_dispatch(monkeypatch, fail=False):
    """Stand in for the correlation task and return the list of recorded calls.

    Same seam as test_phd2_correlation_task.py uses: the task object is looked
    up on the module at call time, so replacing it there records the dispatch
    without a broker.
    """
    from app.worker import tasks_phd2

    calls = []

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            calls.append(kwargs)
            if fail:
                raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Task)
    return calls


def _ingest_one(db, path, text_body):
    from app.worker.tasks_phd2 import ingest_phd2_log

    path.write_text(text_body, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(path), _settings()) == "ok"
    return path


def _orphan_on_its_own_night(db, directory):
    """Ingest a log whose only session lands on a night no other log covers."""
    path = directory / "PHD2_GuideLog_2026-07-20_201333.txt"
    return _ingest_one(db, path, SAMPLE_LOG.replace("2026-07-14", "2026-07-20"))


def test_cleanup_orphans_re_derives_the_nights_the_deleted_logs_covered(
    db, log_file, monkeypatch
):
    """Deleting a log cascades its sessions and frames away, but the images
    those sessions supplied keep the guiding values correlation derived from
    them. No other seam ever revisits those nights - the end-of-pass dispatch
    covers nights this pass ingested, and a deleted log is not ingested - so
    the delete has to ask for them itself, and for those nights only."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    _ingest_files(db, log_file.parent, 3)
    orphan = _orphan_on_its_own_night(db, log_file.parent)

    calls = _capture_dispatch(monkeypatch)
    orphan.unlink()
    with db() as s:
        assert _cleanup_orphans(s) == 1

    assert len(calls) == 1
    # The deleted log's own night, widened by a day either way because the
    # dispatch names it in guide-log date space and the re-derive reads it as
    # an imaging night (see _dispatch_correlation). Still bounded to that
    # neighbourhood: 2026-07-14, which the three surviving logs cover, is not
    # in the set.
    assert calls[0]["kwargs"]["dates"] == [
        "2026-07-19", "2026-07-20", "2026-07-21",
    ]


def test_the_orphan_re_derive_is_nested_under_the_scan_activity(
    db, log_file, monkeypatch
):
    """The dispatch belongs to the scan that triggered it, so the parent
    activity id the pass holds has to reach it."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    _ingest_files(db, log_file.parent, 3)
    orphan = _orphan_on_its_own_night(db, log_file.parent)

    calls = _capture_dispatch(monkeypatch)
    orphan.unlink()
    with db() as s:
        assert _cleanup_orphans(s, parent_activity_id=4242) == 1

    assert calls[0]["kwargs"]["parent_activity_id"] == 4242


def test_the_orphan_re_derive_is_dispatched_after_the_delete_is_durable(
    db, log_file, monkeypatch
):
    """A worker that started re-deriving while the rows were still there would
    refill the nights from sessions that are about to vanish."""
    from app.worker import tasks_phd2

    _isolate_log_table(db)
    _ingest_files(db, log_file.parent, 3)
    orphan = _orphan_on_its_own_night(db, log_file.parent)

    seen = []

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            seen.append(_row_exists(db, orphan))

    monkeypatch.setattr(tasks_phd2, "correlate_phd2_images", _Task)
    orphan.unlink()
    with db() as s:
        assert tasks_phd2._cleanup_orphans(s) == 1

    assert seen == [False]


def test_the_missing_share_guard_re_derives_nothing(db, log_file, monkeypatch):
    """The guard deletes nothing, so nothing on any night went stale."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    paths = _ingest_files(db, log_file.parent, 3)
    for path in paths:
        path.unlink()

    calls = _capture_dispatch(monkeypatch)
    with db() as s:
        assert _cleanup_orphans(s, []) == 0
    assert calls == []


def test_a_cleanup_that_finds_nothing_missing_re_derives_nothing(
    db, log_file, monkeypatch
):
    """An idle scan must not queue a correlation pass per scan."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    _ingest_files(db, log_file.parent, 3)

    calls = _capture_dispatch(monkeypatch)
    with db() as s:
        assert _cleanup_orphans(s) == 0
    assert calls == []


def test_a_failed_re_derive_dispatch_does_not_break_the_cleanup(
    db, log_file, monkeypatch
):
    """The deletion is already committed by the time the dispatch is tried. A
    broker problem must not turn a completed cleanup into a crashed pass."""
    from app.worker.tasks_phd2 import _cleanup_orphans

    _isolate_log_table(db)
    _ingest_files(db, log_file.parent, 3)
    orphan = _orphan_on_its_own_night(db, log_file.parent)

    calls = _capture_dispatch(monkeypatch, fail=True)
    orphan.unlink()
    with db() as s:
        assert _cleanup_orphans(s) == 1

    assert len(calls) == 1
    assert not _row_exists(db, orphan)


class _RecordingRedis:
    """Captures hset/hincrby calls so scan-state writes can be asserted without Redis."""

    def __init__(self):
        self.writes = []
        self.increments = []

    def hset(self, key, *args, mapping=None, **kwargs):
        self.writes.append((key, mapping if mapping is not None else args))

    def hincrby(self, key, field, amount):
        self.increments.append((key, field, amount))


def test_a_scan_forwards_the_admin_cleanup_flag_to_the_guide_log_pass(monkeypatch):
    """The flag is one admin decision about one library. Applying it to images
    only left the guide-log side with no route past its own guard."""
    from app.worker import tasks_scan

    dispatched = {}

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            dispatched.update(kwargs)

    monkeypatch.setattr(tasks_scan, "_redis", _RecordingRedis())
    monkeypatch.setattr(tasks_scan, "scan_phd2_logs", _Task)
    tasks_scan._dispatch_phd2_scan(["/logs/a.txt"], 7, force_orphan_cleanup=True)
    assert dispatched["kwargs"]["force_orphan_cleanup"] is True
    assert dispatched["kwargs"]["parent_activity_id"] == 7

    dispatched.clear()
    tasks_scan._dispatch_phd2_scan(["/logs/a.txt"])
    assert dispatched["kwargs"]["force_orphan_cleanup"] is False


def test_dispatching_the_guide_log_pass_zeroes_the_previous_runs_counters(monkeypatch):
    """scan:state outlives a finished scan, so the counters from the last run
    stay readable next to a state of "complete" while the new pass is still
    queued. A caller polling for completeness would read them as this run's."""
    from app.services.scan_state import SCAN_KEY
    from app.worker import tasks_scan

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            pass

    redis = _RecordingRedis()
    monkeypatch.setattr(tasks_scan, "_redis", redis)
    monkeypatch.setattr(tasks_scan, "scan_phd2_logs", _Task)
    tasks_scan._dispatch_phd2_scan(["/logs/a.txt"])

    assert len(redis.writes) == 1
    key, mapping = redis.writes[0]
    assert key == SCAN_KEY
    # The progress counters are this pass's own, and start at nothing done.
    # phd2_found is NOT one of them: it is the denominator, asserted against
    # the candidate list in
    # test_marking_the_pass_pending_publishes_the_candidate_count.
    assert mapping["phd2_ingested"] == 0
    assert mapping["phd2_failed"] == 0
    assert mapping["phd2_state"] == "pending"
    # The wall-clock value cannot be asserted exactly; that the reset stamps
    # one at all is covered by test_the_pending_flag_carries_the_time_it_was_set.
    assert isinstance(mapping["phd2_state_at"], float)


def test_marking_the_pass_pending_publishes_the_candidate_count(monkeypatch):
    """The guide-log task is dispatched with a 50 s countdown, so the number it
    publishes when it starts arrives about a minute after the job row goes up.
    The scan already holds the candidate list at dispatch, so the denominator
    is published with the flag and the row reads "0 of 3 logs" from its first
    render instead of carrying no sub-label for the whole countdown."""
    from app.services.scan_state import SCAN_KEY
    from app.worker import tasks_scan

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            pass

    redis = _RecordingRedis()
    monkeypatch.setattr(tasks_scan, "_redis", redis)
    monkeypatch.setattr(tasks_scan, "scan_phd2_logs", _Task)
    tasks_scan._dispatch_phd2_scan(["/logs/a.txt", "/logs/b.txt", "/logs/c.txt"])

    key, mapping = redis.writes[0]
    assert key == SCAN_KEY
    assert mapping["phd2_found"] == 3


def test_a_pass_with_no_guide_logs_publishes_a_true_zero_alongside_the_flag():
    """"Not yet known" and "known to be zero" have to stay tellable apart, and
    the only thing that separates them is whether the count can lag the flag.
    Both go in one hset mapping, so a reader never sees the pass claimed with
    its denominator unpublished: phd2_found == 0 next to a live phd2_state
    means zero logs in scope, never "wait and see"."""
    from app.services.scan_state import SCAN_KEY, reset_phd2_counts_sync

    redis = _RecordingRedis()
    reset_phd2_counts_sync(redis, 0)

    assert len(redis.writes) == 1
    key, mapping = redis.writes[0]
    assert key == SCAN_KEY
    assert mapping["phd2_found"] == 0
    assert mapping["phd2_state"] == "pending"


def test_the_pending_mark_cannot_be_written_without_a_count():
    """The placeholder zero was a default, and a default is what let a caller
    that knew the number publish nothing. Requiring the argument makes the
    omission a TypeError at the call site rather than a silent 0 on screen."""
    import inspect

    from app.services.scan_state import reset_phd2_counts_sync

    found = inspect.signature(reset_phd2_counts_sync).parameters["found"]
    assert found.default is inspect.Parameter.empty


def test_the_no_new_files_path_marks_the_pass_with_its_own_candidate_count():
    """run_scan's early return marks the pass pending before publishing the
    scan as complete, ahead of the _dispatch_phd2_scan call further down. That
    call site holds the same candidate list and must not fall back to a
    placeholder just because it is not the dispatch itself."""
    import inspect

    from app.worker import tasks_scan

    source = inspect.getsource(tasks_scan.run_scan)
    assert "reset_phd2_counts_sync(_redis, len(phd2_paths))" in source


def test_a_guide_log_pass_that_cannot_be_queued_claims_nothing_is_in_flight(monkeypatch):
    """Nothing will run, so the scan screen must not be left waiting on it."""
    from app.services.scan_state import SCAN_KEY
    from app.worker import tasks_scan

    class _Broken:
        @staticmethod
        def apply_async(**kwargs):
            raise RuntimeError("broker unreachable")

    redis = _RecordingRedis()
    monkeypatch.setattr(tasks_scan, "_redis", redis)
    monkeypatch.setattr(tasks_scan, "scan_phd2_logs", _Broken)
    tasks_scan._dispatch_phd2_scan(["/logs/a.txt"])

    # The idle write clears the timestamp alongside the flag, so a reader can
    # never see a stale "pending" age attached to a cleared claim.
    assert redis.writes[-1] == (SCAN_KEY, {"phd2_state": "", "phd2_state_at": ""})


def test_a_scan_pass_flags_the_guide_log_work_in_flight_until_it_stops(monkeypatch):
    """`state == "complete"` describes the image scan only: the guide-log pass
    runs on for another minute or two. The flag is what lets a caller tell the
    two apart, so it has to come down on every exit, crashes included."""
    from app.worker import tasks_phd2

    states = []
    monkeypatch.setattr(
        tasks_phd2, "set_phd2_state_sync", lambda r, state: states.append(state)
    )
    monkeypatch.setattr(
        tasks_phd2, "_run_phd2_pass", lambda **kw: {"status": "complete"}
    )
    tasks_phd2.scan_phd2_logs(paths=["/logs/a.txt"])
    assert states == ["running", ""]

    def _boom(**kwargs):
        raise RuntimeError("pass died")

    states.clear()
    monkeypatch.setattr(tasks_phd2, "_run_phd2_pass", _boom)
    with pytest.raises(RuntimeError):
        tasks_phd2.scan_phd2_logs(paths=["/logs/a.txt"])
    assert states == ["running", ""]

    # A settings save is not a scan and has no scan state to describe.
    states.clear()
    monkeypatch.setattr(
        tasks_phd2, "_run_phd2_pass", lambda **kw: {"status": "complete"}
    )
    tasks_phd2.scan_phd2_logs(force=True)
    assert states == []


def test_the_phd2_counters_are_reset_before_the_scan_is_called_complete():
    """run_scan wrote "complete" and only then reset the guide-log counters,
    so for the length of three apply_async calls a poller could read this
    scan's completion next to the previous scan's guide-log totals."""
    import inspect

    from app.worker import tasks_scan

    source = inspect.getsource(tasks_scan.run_scan)
    reset_at = source.index("reset_phd2_counts_sync(_redis")
    idle_at = source.index("set_idle_sync(_redis)")
    assert reset_at < idle_at, (
        "the guide-log counters must be zeroed before the scan is published "
        "as complete"
    )


def test_the_pending_flag_carries_the_time_it_was_set():
    """Only a RAISING apply_async clears the flag. A task queued and then lost
    (worker down, broker discard) leaves phd2_state at "pending" until the
    whole scan:state key expires, and a UI waiting on it shows "processing"
    forever. The timestamp lets the reader age the claim out."""
    from app.services.scan_state import SCAN_KEY, reset_phd2_counts_sync

    redis = _RecordingRedis()
    reset_phd2_counts_sync(redis, 25)
    key, mapping = redis.writes[0]
    assert key == SCAN_KEY
    assert mapping["phd2_state"] == "pending"
    assert isinstance(mapping["phd2_state_at"], float)
    assert mapping["phd2_state_at"] > 0


def test_moving_to_running_refreshes_the_timestamp():
    from app.services.scan_state import SCAN_KEY, set_phd2_state_sync

    redis = _RecordingRedis()
    set_phd2_state_sync(redis, "running")
    key, mapping = redis.writes[0]
    assert key == SCAN_KEY
    assert mapping["phd2_state"] == "running"
    assert isinstance(mapping["phd2_state_at"], float)


def test_publishing_the_counters_clears_the_flag_and_its_timestamp_together():
    """A reader that sees the pass finished must see this pass's numbers in the
    same snapshot, never the flag cleared a moment before the totals land."""
    from app.services.scan_state import SCAN_KEY, set_phd2_counts_sync

    redis = _RecordingRedis()
    set_phd2_counts_sync(redis, 25, 19, 0)
    assert redis.writes == [(SCAN_KEY, {
        "phd2_found": 25,
        "phd2_ingested": 19,
        "phd2_failed": 0,
        "phd2_state": "",
        "phd2_state_at": "",
    })]


def test_the_timestamp_reaches_the_scan_status_response():
    from app.schemas.scan import ScanStateResponse
    from app.services.scan_state import parse_snapshot

    snap = parse_snapshot({
        "state": "complete", "total": "0", "completed": "0", "failed": "0",
        "phd2_state": "pending", "phd2_state_at": "1753800000.0",
    })
    assert snap.phd2_state_at == 1753800000.0
    assert "phd2_state_at" in snap.to_dict()
    assert "phd2_state_at" in ScanStateResponse.model_fields


def test_a_hash_written_before_this_field_existed_reads_back_none():
    from app.services.scan_state import parse_snapshot

    snap = parse_snapshot({
        "state": "complete", "total": "0", "completed": "0", "failed": "0",
        "phd2_state": "pending",
    })
    assert snap.phd2_state_at is None


def test_the_candidate_total_can_be_published_before_the_pass_finishes():
    """The scan UI counts "N of M" while the pass runs. M is known as soon as
    the candidate list is, and publishing it only at the end means the UI has
    nothing to count against for the whole pass."""
    from app.services.scan_state import SCAN_KEY, set_phd2_found_sync

    redis = _RecordingRedis()
    set_phd2_found_sync(redis, 25)
    assert redis.writes == [(SCAN_KEY, ("phd2_found", 25))]


def test_per_file_progress_increments_rather_than_overwrites():
    """hincrby, not hset: the pass has no running total of its own to write,
    and re-deriving one per file would race the end-of-pass write."""
    from app.services.scan_state import SCAN_KEY, increment_phd2_progress_sync

    redis = _RecordingRedis()
    increment_phd2_progress_sync(redis, ingested=1)
    increment_phd2_progress_sync(redis, failed=1)
    assert redis.increments == [
        (SCAN_KEY, "phd2_ingested", 1),
        (SCAN_KEY, "phd2_failed", 1),
    ]


def test_progress_renews_the_state_timestamp():
    """phd2_state_at is otherwise stamped only at the pending and running
    transitions, so a consumer that ages "running" out on the same window it
    uses for "pending" calls a healthy pass stalled as soon as it runs longer
    than that window. Per-file progress renewing the timestamp means a
    timestamp that stopped moving is evidence the pass stopped moving."""
    from app.services.scan_state import SCAN_KEY, increment_phd2_progress_sync

    redis = _RecordingRedis()
    increment_phd2_progress_sync(redis, ingested=1)
    assert redis.increments == [(SCAN_KEY, "phd2_ingested", 1)]
    assert len(redis.writes) == 1
    key, args = redis.writes[0]
    assert key == SCAN_KEY
    assert args[0] == "phd2_state_at"
    assert isinstance(args[1], float)
    assert args[1] > 0

    redis = _RecordingRedis()
    increment_phd2_progress_sync(redis, failed=1)
    assert redis.writes[0][1][0] == "phd2_state_at"


def test_a_no_op_progress_call_writes_nothing():
    """A file that was unchanged or empty is neither ingested nor failed, and
    must not cost a Redis round trip per file in a scan of hundreds. It also
    must not renew phd2_state_at: a pass that is hung rather than busy would
    then keep looking alive to anything aging the claim out."""
    from app.services.scan_state import increment_phd2_progress_sync

    redis = _RecordingRedis()
    increment_phd2_progress_sync(redis)
    assert redis.increments == []
    assert redis.writes == []


def test_a_remap_pass_never_purges(db, log_file, monkeypatch):
    """Re-keying reads no filesystem, so nothing it sees can be evidence that
    a file is gone."""
    from app.worker import tasks_phd2

    calls = []
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: _settings())
    monkeypatch.setattr(
        tasks_phd2, "_cleanup_orphans", lambda *a, **kw: calls.append(a) or 0
    )
    assert tasks_phd2.scan_phd2_logs(remap_only=True)["status"] == "remapped"
    assert calls == []


def test_a_forced_pass_never_purges_and_reports_itself_honestly(db, log_file, monkeypatch):
    """Saving the observer timezone while the share is unreachable used to
    fail every stat() and then delete every row. A settings save also has no
    scan to report, so it neither writes the scan counters nor claims one
    finished."""
    from app.worker import tasks_phd2

    calls = []
    counters = []
    events = []
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    monkeypatch.setattr(
        tasks_phd2, "_read_settings", lambda: _settings(observer_timezone="UTC")
    )
    monkeypatch.setattr(
        tasks_phd2, "_cleanup_orphans", lambda *a, **kw: calls.append(a) or 0
    )
    monkeypatch.setattr(
        tasks_phd2, "set_phd2_counts_sync", lambda *a, **kw: counters.append(a)
    )
    monkeypatch.setattr(
        tasks_phd2, "_emit_activity_sync",
        lambda *a, **kw: events.append(kw.get("event_type")),
    )

    result = tasks_phd2.scan_phd2_logs(force=True)
    assert result["status"] == "complete"
    assert result["removed"] == 0
    assert calls == []
    assert counters == []
    assert "phd2_scan_complete" not in events
    assert "phd2_settings_reapplied" in events


# ── Imaging-night grouping without a longitude (smoke test, finding 4.1) ──


@pytest.fixture
def image_rows(db):
    """Insert images on given session dates, cleaned up afterwards.

    Dated far in the future so nothing another module seeds can be mistaken
    for one of these rows, and vice versa.
    """
    from app.models import Image

    def _add(*session_dates):
        with db() as s:
            for session_date in session_dates:
                s.add(Image(
                    id=uuid.uuid4(),
                    file_path=f"/data/{TEST_MARK}/{uuid.uuid4()}.fits",
                    file_name="x.fits",
                    image_type="LIGHT",
                    raw_headers={},
                    session_date=session_date,
                ))
            s.commit()

    yield _add
    with db() as s:
        s.execute(
            text("DELETE FROM images WHERE file_path LIKE :p"),
            {"p": f"%{TEST_MARK}%"},
        )
        s.commit()


def _forced_pass_records(monkeypatch, general, sanity=None):
    """Run a settings-triggered pass and return every activity call it made.

    The whole kwargs dict, so a test can assert on `details` as well as on the
    message. `_forced_pass` is the two-field view of the same run.
    """
    from app.worker import tasks_phd2

    records = []
    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: general)
    monkeypatch.setattr(tasks_phd2, "set_phd2_counts_sync", lambda *a, **kw: None)
    monkeypatch.setattr(
        tasks_phd2, "_emit_activity_sync", lambda *a, **kw: records.append(kw)
    )
    if sanity is not None:
        monkeypatch.setattr(
            tasks_phd2, "_session_date_sanity_check", lambda db, dates: sanity
        )
    tasks_phd2.scan_phd2_logs(force=True)
    return records


def _forced_pass(monkeypatch, general, sanity=None):
    """Run a settings-triggered pass and return the activity events it emitted."""
    return [
        (record.get("event_type"), record.get("message"))
        for record in _forced_pass_records(monkeypatch, general, sanity)
    ]


def test_a_pass_without_a_longitude_warns_that_grouping_fell_back(db, log_file, monkeypatch):
    """A guide log carries no coordinates, so the global setting is the only
    longitude there is. Unset, the whole pass silently drops to UTC-midnight
    grouping while images keep the solar-noon boundary - the image scanner and
    the session-date recompute both warn about this, and so must this pass."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    warned = []
    monkeypatch.setattr(
        tasks_phd2, "warn_imaging_night_fallback", lambda log: warned.append(log)
    )
    _forced_pass(monkeypatch, _settings(observer_longitude=None))
    assert len(warned) == 1


def test_a_pass_with_a_longitude_does_not_warn(db, log_file, monkeypatch):
    """Grouping works, so there is nothing to report."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    warned = []
    monkeypatch.setattr(
        tasks_phd2, "warn_imaging_night_fallback", lambda log: warned.append(log)
    )
    _forced_pass(monkeypatch, _settings(observer_longitude=-90.7))
    assert warned == []


def test_grouping_switched_off_never_warns(db, log_file, monkeypatch):
    """Nothing has fallen back: UTC-midnight grouping is what was asked for."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    warned = []
    monkeypatch.setattr(
        tasks_phd2, "warn_imaging_night_fallback", lambda log: warned.append(log)
    )
    _forced_pass(
        monkeypatch, _settings(observer_longitude=None, use_imaging_night=False)
    )
    assert warned == []


def test_a_whole_day_offset_is_recognised_as_the_missing_longitude_signature(db, image_rows):
    """Without a longitude an evening session keeps its UTC date, one day past
    the noon-boundary date its images carry. Images on the night before every
    reported night is that fingerprint."""
    from app.worker.tasks_phd2 import _session_date_sanity_check

    night = date(2099, 3, 14)
    image_rows(night)
    with db() as s:
        suspicious, day_skewed = _session_date_sanity_check(
            s, {night + timedelta(days=1)}
        )
    assert suspicious == [(night + timedelta(days=1)).isoformat()]
    assert day_skewed is True


def test_a_guiding_night_with_no_images_nearby_is_not_the_signature(db, image_rows):
    """A night the library simply has no frames for looks the same as a
    mis-grouped one until the neighbouring day is checked."""
    from app.worker.tasks_phd2 import _session_date_sanity_check

    image_rows(date(2099, 3, 14))
    with db() as s:
        suspicious, day_skewed = _session_date_sanity_check(s, {date(2099, 6, 1)})
    assert suspicious == ["2099-06-01"]
    assert day_skewed is False


def test_the_day_skew_notice_blames_the_longitude_not_the_timezone(db, log_file, monkeypatch):
    """Sending the user to check a timezone that is already correct is what
    made this defect cost a whole investigation."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    events = _forced_pass(
        monkeypatch,
        _settings(observer_longitude=None),
        sanity=(["2026-07-15"], True),
    )
    types = [t for t, _ in events]
    assert "phd2_longitude_missing" in types
    assert "phd2_timezone_mismatch" not in types
    message = next(m for t, m in events if t == "phd2_longitude_missing")
    assert "observer longitude" in message
    assert "timezone" not in message
    # The notice has to name the screen and the field, not just the concept.
    assert "Settings > Library > Observer Location" in message
    assert "set Longitude" in message


def test_a_skew_that_is_not_the_signature_still_points_at_the_timezone(db, log_file, monkeypatch):
    """Guiding nights with no images either side are the timezone symptom the
    original notice was written for, and it stays."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    events = _forced_pass(
        monkeypatch,
        _settings(observer_longitude=None),
        sanity=(["2026-07-15"], False),
    )
    types = [t for t, _ in events]
    assert "phd2_timezone_mismatch" in types
    assert "phd2_longitude_missing" not in types
    message = next(m for t, m in events if t == "phd2_timezone_mismatch")
    # Soak feedback: the old wording named the setting but not what to do with
    # it. The notice must state what happened, why, and the exact action.
    assert "matched no images" in message
    assert "Settings > Library > Observer Location" in message
    assert "set Timezone to the timezone of the PC that runs PHD2" in message


def test_a_configured_longitude_leaves_the_timezone_notice_alone(db, log_file, monkeypatch):
    """The longitude is set, so a day skew cannot be blamed on it."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    events = _forced_pass(
        monkeypatch,
        _settings(observer_longitude=-90.7),
        sanity=(["2026-07-15"], True),
    )
    types = [t for t, _ in events]
    assert "phd2_timezone_mismatch" in types
    assert "phd2_longitude_missing" not in types


# ── One map entry per rig: telescope, timezone and site ──


PROFILE = "AM5n_OAG_ASI174M"


def _entry(**kw):
    """One per-profile map entry in the current object form."""
    base = {"telescope": "140APO", "timezone": "", "latitude": None,
            "longitude": None}
    base.update(kw)
    return base


def test_a_map_entry_object_still_writes_a_telescope_name(db, log_file):
    """The settings schema now hands the worker entry objects rather than bare
    strings, and the telescope column takes a name. Reading the map without the
    projection put a Phd2ProfileMapping into an insert and failed the whole
    file."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings(
            phd2_profile_map={PROFILE: _entry(telescope="RedCat 51")}
        )) == "ok"
    with db() as s:
        session = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert session.telescope == "RedCat 51"


def test_apply_profile_map_takes_entry_objects_and_legacy_strings(db, log_file):
    """Callers hold the map in whichever form they were handed. Both have to
    land the same telescope name on the same row."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import apply_profile_map, ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        ingest_phd2_log(s, str(log_file), _settings(phd2_profile_map={}))

    def _telescope():
        with db() as s:
            return s.execute(
                select(Phd2Session).join(Phd2Log)
                .where(Phd2Log.file_path == str(log_file))
            ).scalar_one().telescope

    with db() as s:
        apply_profile_map(s, {PROFILE: _entry(telescope="RedCat 51")})
        s.commit()
    assert _telescope() == "RedCat 51"

    with db() as s:
        apply_profile_map(s, {PROFILE: "Askar 120"})
        s.commit()
    assert _telescope() == "Askar 120"

    # An entry that kept its zone and site after being unmapped is not mapped
    # to a telescope called "None".
    with db() as s:
        apply_profile_map(
            s, {PROFILE: _entry(telescope=None, timezone="UTC", longitude=12.5)}
        )
        s.commit()
    assert _telescope() is None


def _two_profile_log(second_profile):
    """One file holding two sections written by two different rigs."""
    first, _, tail = SAMPLE_LOG.partition("Log Summary:")
    second = first.partition("Guiding Begins at")[2]
    second = ("Guiding Begins at" + second).replace(PROFILE, second_profile)
    return first + second + "Log Summary:" + tail


def test_each_profile_is_read_in_its_own_timezone(db, log_file):
    """Two rigs in one file is the case a single per-file zone cannot express:
    the same wall-clock string is two different instants."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(_two_profile_log("Remote_RC8"), encoding="utf-8")
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings(
            phd2_profile_map={
                PROFILE: _entry(timezone="America/New_York"),
                "Remote_RC8": _entry(telescope="RC8", timezone="UTC"),
            },
        )) == "ok"

    with db() as s:
        rows = s.execute(
            select(Phd2Session).join(Phd2Log)
            .where(Phd2Log.file_path == str(log_file))
        ).scalars().all()
        starts = {r.equipment_profile: r.started_at_utc for r in rows}
    assert len(starts) == 2
    # 21:42:27 local on 2026-07-14 is 01:42:27Z under America/New_York (UTC-4
    # in July) and 21:42:27Z under UTC.
    assert (starts["Remote_RC8"] - starts[PROFILE]).total_seconds() == -4 * 3600


def test_a_profile_with_its_own_longitude_is_filed_on_its_own_night(db, log_file):
    """The night boundary is local solar noon, so a rig taken far enough west
    or east of home belongs on a different night from the same instant."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker.tasks_phd2 import ingest_phd2_log

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")

    def _ingest(profile_map):
        with db() as s:
            assert ingest_phd2_log(
                s, str(log_file), _settings(phd2_profile_map=profile_map),
                force=True,
            ) == "ok"
        with db() as s:
            return s.execute(
                select(Phd2Session).join(Phd2Log)
                .where(Phd2Log.file_path == str(log_file))
            ).scalar_one().session_date

    # observer_longitude is -80.0 in _settings, so the home site files this
    # 01:42Z session under the night of the 14th.
    assert _ingest({}) == date(2026, 7, 14)
    assert _ingest({PROFILE: _entry(longitude=170.0)}) == date(2026, 7, 15)


def test_an_unreadable_log_is_recorded_as_unreadable_with_its_reason(db, log_file):
    """"I could not understand this file" and "this file has nothing in it"
    used to be the same stored status. The reason has to reach parse_error, and
    the pass has to keep counting the file as a failure."""
    from app.models.phd2 import Phd2Log
    from app.worker.tasks_phd2 import ingest_phd2_log

    # Guide-log content with no readable run in it: the parser recognises the
    # markers and raises Phd2UnreadableLog rather than returning zero runs.
    log_file.write_text(
        "Guiding Begins at 2026-07-14 21:42:27\n"
        "Equipment Profile = AM5n_OAG_ASI174M\n",
        encoding="utf-8",
    )
    with db() as s:
        assert ingest_phd2_log(s, str(log_file), _settings()) == "failed"
    with db() as s:
        row = s.execute(
            select(Phd2Log).where(Phd2Log.file_path == str(log_file))
        ).scalar_one()
        assert row.parse_status == "unreadable"
        assert "no PHD2 run could be read" in row.parse_error


# ── Sidereal cross-check ──


FRAME_BLOCK = (
    "Frame,Time,mount,dx,dy,RARawDistance,DECRawDistance,RAGuideDistance,"
    "DECGuideDistance,RADuration,RADirection,DECDuration,DECDirection,XStep,"
    "YStep,StarMass,SNR,ErrorCode\n"
    '1,1.228,"Mount",0.330,0.544,0.556,-0.189,0.350,0.000,98,W,0,,,,1713,28.59,1\n'
    '2,2.093,"Mount",0.524,0.132,0.151,-0.477,0.000,0.000,0,,0,,,,1702,28.36,0\n'
)

POINTING_DEC_DEG = 38.5
POINTING_HOUR_ANGLES = (-2.0, -1.0, 0.0, 1.0)


def _pointing_section(
    profile, local_start, zone, reference_deg, latitude_deg, error_hours,
    hour_angle_hr, with_ra=True, alt_error_deg=0.0,
):
    """One guiding section whose pointing implies a chosen offset error.

    RA is solved backwards from the answer wanted: local sidereal time is
    RA + hour angle, so writing RA = GMST(instant) + implied_longitude - HA
    makes the section imply exactly `error_hours` against `reference_deg`. The
    altitude is the one the pointing triangle predicts for `latitude_deg`, so
    the coherence gate passes unless `alt_error_deg` deliberately breaks it.
    """
    from app.services.phd2_sidereal import gmst_hours, predicted_altitude_deg

    instant = local_start.replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
    implied_longitude_hours = reference_deg / 15.0 + error_hours
    ra_hr = (gmst_hours(instant) + implied_longitude_hours - hour_angle_hr) % 24.0
    alt_deg = predicted_altitude_deg(
        POINTING_DEC_DEG, hour_angle_hr, latitude_deg
    ) + alt_error_deg
    ra_field = f"RA = {ra_hr:.2f} hr, " if with_ra else ""
    ended = local_start + timedelta(seconds=19)
    return (
        f"Guiding Begins at {local_start:%Y-%m-%d %H:%M:%S}\n"
        f"Equipment Profile = {profile}\n"
        "Pixel scale = 1.54 arc-sec/px, Binning = 1, Focal length = 784 mm\n"
        " Camera = ZWO ASI174MM Mini, gain = 90, full size = 1936 x 1216, "
        "have dark, dark dur = 500, no defect map, pixel size = 5.9 um\n"
        "Exposure = 500 ms\n"
        f"{ra_field}Dec = {POINTING_DEC_DEG} deg, "
        f"Hour angle = {hour_angle_hr:.2f} hr, Pier side = West, "
        f"Rotator pos = N/A, Alt = {alt_deg:.1f} deg, Az = 70.4 deg\n"
        + FRAME_BLOCK
        + f"Guiding Ends at {ended:%Y-%m-%d %H:%M:%S}\n\n"
    )


def _pointing_log(
    zone, reference_deg, latitude_deg, error_hours, sections=3,
    profile=PROFILE, with_ra=True, alt_error_deg=0.0,
):
    """A whole guide log whose every section implies the same offset error."""
    body = ""
    for index in range(sections):
        body += _pointing_section(
            profile,
            datetime(2026, 7, 14 + index, 21, 42, 27),
            zone, reference_deg, latitude_deg, error_hours,
            POINTING_HOUR_ANGLES[index % len(POINTING_HOUR_ANGLES)],
            with_ra=with_ra, alt_error_deg=alt_error_deg,
        )
    return (
        "PHD2 version 2.6.14 [Windows], Log version 2.5. Log enabled at "
        "2026-07-14 20:13:33\n\n"
        + body
        + f"Log Summary: calcnt:0 gcnt:{sections} gdur:{19 * sections} "
        f"gacnt:{2 * sections}\n"
        "Log closed at 2026-07-17 21:43:00\n"
    )


ZONE = "America/New_York"
SITE_LON = -80.0
SITE_LAT = 30.0
# America/New_York is UTC-4 in July, so its standard meridian is -60 degrees.
ZONE_MERIDIAN_DEG = -60.0


def _sidereal_settings(entry=None, **kw):
    profile_map = {} if entry is None else {PROFILE: entry}
    base = dict(
        observer_timezone=ZONE,
        observer_latitude=SITE_LAT,
        observer_longitude=SITE_LON,
        phd2_profile_map=profile_map,
    )
    base.update(kw)
    return _settings(**base)


def _sidereal_pass(db, log_file, monkeypatch, body, general):
    """Ingest one synthetic log, then run a forced pass over it alone."""
    _isolate_log_table(db)
    log_file.write_text(body, encoding="utf-8")
    with db() as s:
        assert tasks_phd2_module().ingest_phd2_log(
            s, str(log_file), general
        ) == "ok"
    return _forced_pass_records(monkeypatch, general)


def tasks_phd2_module():
    from app.worker import tasks_phd2

    return tasks_phd2


def _sidereal_records(records):
    return [
        r for r in records
        if r.get("event_type") == "phd2_timezone_sidereal_mismatch"
    ]


def test_a_six_hour_pointing_error_raises_exactly_one_warning(
    db, log_file, monkeypatch
):
    """The rig is on UTC-10 and labelled UTC-4, so its own pointing puts local
    sidereal time six hours from where the configured zone says it should be.
    One row for the whole pass, naming an offset the user can select."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0),
        general,
    )

    found = _sidereal_records(records)
    assert len(found) == 1
    row = found[0]
    assert row["severity"] == "warning"
    assert row["category"] == "scan"
    message = row["message"]
    assert PROFILE in message
    assert "UTC-10:00" in message
    assert "UTC-04:00" in message
    assert "GalactiLog changed nothing" in message
    # The site is known, so the finding is stated rather than hedged.
    assert "probably wrong" not in message
    assert "Either the profile timezone is wrong" not in message
    assert found[0]["details"]["profiles"][0]["site_known"] is True
    profiles = row["details"]["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["profile"] == PROFILE
    assert profiles[0]["sections"] == 3
    assert abs(profiles[0]["median_error_hours"] - 6.0) < 0.05
    assert row["details"]["observer_longitude"] == SITE_LON


def test_a_rig_with_neither_a_site_nor_a_zone_is_left_to_the_other_warning(
    db, log_file, monkeypatch
):
    """No longitude and no timezone at either level is a single
    misconfiguration, and the correlation pass already names the profile for
    it. One cause, one warning."""
    general = _sidereal_settings(
        _entry(), observer_longitude=None, observer_timezone="",
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0),
        general,
    )
    assert _sidereal_records(records) == []


def test_a_travelling_rigs_own_site_is_checked_with_no_global_longitude(
    db, log_file, monkeypatch
):
    """The case the per-rig site exists for: the user has not filled in
    Observer Location, but has told GalactiLog exactly where the remote rig
    stands. That rig is checkable, and stating its finding as fact is correct
    because the site is one the user entered for it."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON),
        observer_longitude=None,
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0),
        general,
    )

    found = _sidereal_records(records)
    assert len(found) == 1
    message = found[0]["message"]
    assert "UTC-10:00" in message
    assert "Either the profile timezone is wrong" not in message
    entry = found[0]["details"]["profiles"][0]
    assert entry["site_known"] is True
    assert entry["compared_longitude_deg"] == SITE_LON
    # The global value is genuinely unset, and the notice says so rather than
    # implying a site nobody entered.
    assert found[0]["details"]["observer_longitude"] is None


def test_an_inherited_longitude_never_states_the_finding_as_fact(
    db, log_file, monkeypatch
):
    """A rig with no site of its own is compared against the home longitude,
    which is a premise rather than a fact: the rig may simply not be there.
    Same tolerance, but the wording has to offer all three explanations."""
    general = _sidereal_settings(_entry(timezone=ZONE, latitude=SITE_LAT))
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0),
        general,
    )

    found = _sidereal_records(records)
    assert len(found) == 1
    message = found[0]["message"]
    assert (
        "Either the profile timezone is wrong, or this rig is not at the "
        "configured observer longitude, or the mount clock is wrong."
    ) in message
    # Not stated as fact, and not the hedged standard-meridian tier either.
    assert "which puts this rig on" not in message
    assert "probably wrong" not in message
    entry = found[0]["details"]["profiles"][0]
    assert entry["tier"] == "site"
    assert entry["site_known"] is False
    assert entry["compared_longitude_deg"] == SITE_LON


def test_two_pointing_sections_are_not_enough_to_accuse_anyone(
    db, log_file, monkeypatch
):
    """A spread measured over two samples measures nothing, so one stale
    pointing line could otherwise carry a warning on its own."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0, sections=2),
        general,
    )
    assert _sidereal_records(records) == []


def test_a_log_with_no_ra_says_nothing_and_still_ingests(db, log_file, monkeypatch):
    """The ASIAIR degrade path: those files write Dec, hour angle, Alt and Az
    but no RA, so the offset cannot be solved at all. They must still be
    catalogued."""
    from app.models.phd2 import Phd2Log

    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0, with_ra=False),
        general,
    )
    assert _sidereal_records(records) == []
    with db() as s:
        assert s.execute(
            select(Phd2Log).where(Phd2Log.file_path == str(log_file))
        ).scalar_one().parse_status == "ok"


def test_pointing_without_an_ra_contributes_no_sample(db, log_file):
    """The collection itself, rather than the verdict it feeds: a header
    missing either half of the sidereal input appends nothing."""
    from app.worker.tasks_phd2 import ingest_phd2_log

    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    log_file.write_text(
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0, with_ra=False),
        encoding="utf-8",
    )
    samples = []
    with db() as s:
        assert ingest_phd2_log(
            s, str(log_file), general, pointing=samples
        ) == "ok"
    assert samples == []

    log_file.write_text(
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0), encoding="utf-8"
    )
    samples = []
    with db() as s:
        assert ingest_phd2_log(
            s, str(log_file), general, force=True, pointing=samples
        ) == "ok"
    assert len(samples) == 3
    assert {s.profile for s in samples} == {PROFILE}
    assert all(s.ra_hr is not None and s.hour_angle_hr is not None for s in samples)


def test_incoherent_pointing_suppresses_the_verdict(db, log_file, monkeypatch):
    """The mount's own coordinates are checkable with no clock and no
    longitude. When the altitude it reports cannot be reached from the
    configured latitude at that declination and hour angle, the pointing is not
    evidence about a timezone - it is evidence about the mount."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0, alt_error_deg=25.0),
        general,
    )
    assert _sidereal_records(records) == []


def test_pointing_that_cannot_be_checked_is_not_treated_as_checked(
    db, log_file, monkeypatch
):
    """With no latitude configured at either level the coherence gate can
    return neither yes nor no. "Cannot check" is not "coherent": the gate is
    tested against True, so an unverifiable pointing block accuses nobody."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, longitude=SITE_LON), observer_latitude=None
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0),
        general,
    )
    assert _sidereal_records(records) == []


def test_a_rig_with_no_site_of_its_own_is_only_probably_wrong(
    db, log_file, monkeypatch
):
    """With no longitude resolvable at either level the comparison falls back
    to the timezone's standard meridian, whose real width can be three hours.
    The tolerance widens, the wording hedges, and the actionable output is a
    longitude to enter rather than an offset to select."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT), observer_longitude=None
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, ZONE_MERIDIAN_DEG, SITE_LAT, 5.0),
        general,
    )

    found = _sidereal_records(records)
    assert len(found) == 1
    message = found[0]["message"]
    assert "probably wrong" in message
    assert "standard meridian" in message
    assert "Settings > Library > PHD2" in message
    # No offset is quoted from a comparison against a whole zone.
    assert "UTC-" not in message and "UTC+" not in message
    entry = found[0]["details"]["profiles"][0]
    assert entry["tier"] == "meridian"
    assert entry["confident"] is False
    assert entry["implied_utc_offset_hours"] is None
    assert entry["implied_longitude_deg"] is not None


def test_a_rig_inside_its_own_zones_width_says_nothing(db, log_file, monkeypatch):
    """Two hours from the standard meridian is ordinary zone geography, not a
    misconfiguration: Spain, western Argentina and Xinjiang all live there."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT), observer_longitude=None
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, ZONE_MERIDIAN_DEG, SITE_LAT, 2.0),
        general,
    )
    assert _sidereal_records(records) == []


def test_a_correctly_configured_rig_is_never_accused(db, log_file, monkeypatch):
    """The check has to be silent on a correct setup, or it is noise."""
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    records = _sidereal_pass(
        db, log_file, monkeypatch,
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 0.0),
        general,
    )
    assert _sidereal_records(records) == []


def test_a_remap_pass_draws_no_sidereal_verdict(db, log_file, monkeypatch):
    """A remap parses nothing, so it has no pointing to reason from."""
    from app.worker import tasks_phd2

    _isolate_log_table(db)
    general = _sidereal_settings(
        _entry(timezone=ZONE, latitude=SITE_LAT, longitude=SITE_LON)
    )
    log_file.write_text(
        _pointing_log(ZONE, SITE_LON, SITE_LAT, 6.0), encoding="utf-8"
    )
    with db() as s:
        assert tasks_phd2.ingest_phd2_log(s, str(log_file), general) == "ok"

    records = []
    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: general)
    monkeypatch.setattr(
        tasks_phd2, "_emit_activity_sync", lambda *a, **kw: records.append(kw)
    )
    assert tasks_phd2.scan_phd2_logs(remap_only=True)["status"] == "remapped"
    assert _sidereal_records(records) == []


# ── Per-profile longitude, stale rows and the notices that name them ──


def test_the_longitude_notice_names_the_profiles_and_the_profile_remedy(
    db, log_file, monkeypatch
):
    """The fallback is now a per-profile fact: one rig can be grouped correctly
    while another is not, so the notice has to say which, and has to offer the
    per-rig field as well as the global one."""
    from app.worker import tasks_phd2

    _isolate_log_table(db)
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    general = _settings(observer_longitude=None)
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), general)

    records = _forced_pass_records(
        monkeypatch, general, sanity=(["2026-07-15"], True)
    )
    notice = next(
        r for r in records if r.get("event_type") == "phd2_longitude_missing"
    )
    assert PROFILE in notice["message"]
    assert "Settings > Library > Observer Location" in notice["message"]
    assert "set Longitude" in notice["message"]
    assert "Settings > Library > PHD2" in notice["message"]
    # The old notice hard-coded a null here even when a longitude was set.
    assert notice["details"]["observer_longitude"] is None
    assert notice["details"]["profiles"] == [PROFILE]


def test_a_rig_with_its_own_longitude_is_not_named_by_the_fallback_notice(
    db, log_file, monkeypatch
):
    """A profile carrying its own site is grouped correctly whatever the global
    setting says, so it must not be listed as falling back."""
    from app.worker import tasks_phd2

    _isolate_log_table(db)
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    general = _settings(
        observer_longitude=None,
        phd2_profile_map={PROFILE: _entry(longitude=-97.7)},
    )
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), general)

    warned = []
    monkeypatch.setattr(
        tasks_phd2, "warn_imaging_night_fallback", lambda log: warned.append(log)
    )
    records = _forced_pass_records(
        monkeypatch, general, sanity=(["2026-07-15"], True)
    )
    assert warned == []
    assert [
        r for r in records if r.get("event_type") == "phd2_longitude_missing"
    ] == []


def test_the_timezone_notice_offers_the_per_profile_zone_as_well(
    db, log_file, monkeypatch
):
    """A rig on a PC in another zone cannot be fixed from Observer Location, so
    the notice that sends a user there has to name the other field too."""
    from app.worker import tasks_phd2

    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        tasks_phd2.ingest_phd2_log(s, str(log_file), _settings())

    events = _forced_pass(
        monkeypatch, _settings(), sanity=(["2026-07-15"], False)
    )
    message = next(m for t, m in events if t == "phd2_timezone_mismatch")
    assert "set Timezone to the timezone of the PC that runs PHD2" in message
    assert "set a timezone on the profile in Settings > Library > PHD2" in message


def test_a_forced_pass_rekeys_a_row_whose_file_has_gone(db, log_file, monkeypatch):
    """The re-parse cannot reach a log whose file has been deleted or whose
    share is offline: it fails at the stat() before any row is rewritten, and a
    settings-triggered pass never purges. Without a re-key that row keeps the
    night the old site gave it forever. session_date is derived from
    started_at_utc, which no longitude affects, so no file is needed."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.worker import tasks_phd2

    _isolate_log_table(db)
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    with db() as s:
        assert tasks_phd2.ingest_phd2_log(s, str(log_file), _settings()) == "ok"

    def _stored_date():
        with db() as s:
            return s.execute(
                select(Phd2Session).join(Phd2Log)
                .where(Phd2Log.file_path == str(log_file))
            ).scalar_one().session_date

    assert _stored_date() == date(2026, 7, 14)
    log_file.unlink()

    records = _forced_pass_records(
        monkeypatch, _settings(phd2_profile_map={PROFILE: _entry(longitude=170.0)})
    )
    assert records  # the pass still reported itself
    assert _stored_date() == date(2026, 7, 15)


def test_the_pass_names_profiles_that_carry_no_map_entry(db, log_file, monkeypatch):
    """A profile renamed in PHD2 silently inherits the home site and looks
    entirely normal in the catalog. The pass's own report is where that becomes
    visible, rather than in a warning of its own: the correlation pass already
    warns about unattributed profiles."""
    _isolate_log_table(db)
    log_file.write_text(SAMPLE_LOG, encoding="utf-8")
    general = _settings(phd2_profile_map={"SomeOtherRig": _entry()})
    with db() as s:
        assert tasks_phd2_module().ingest_phd2_log(
            s, str(log_file), general
        ) == "ok"

    records = _forced_pass_records(monkeypatch, general)
    report = next(
        r for r in records if r.get("event_type") == "phd2_settings_reapplied"
    )
    assert report["details"]["unmapped_profiles"] == [PROFILE]
