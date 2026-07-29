"""Ingest behaviour for PHD2 guide logs: idempotency, empty files, orphans."""
import os
import uuid
from datetime import date, timedelta

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


class _RecordingRedis:
    """Captures hset calls so scan-state writes can be asserted without Redis."""

    def __init__(self):
        self.writes = []

    def hset(self, key, *args, mapping=None, **kwargs):
        self.writes.append((key, mapping if mapping is not None else args))


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

    assert redis.writes == [(SCAN_KEY, {
        "phd2_found": 0,
        "phd2_ingested": 0,
        "phd2_failed": 0,
        "phd2_state": "pending",
    })]


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

    assert redis.writes[-1] == (SCAN_KEY, ("phd2_state", ""))


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


def test_publishing_the_counters_clears_the_in_flight_flag_in_the_same_write():
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
    })]


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


def _forced_pass(monkeypatch, general, sanity=None):
    """Run a settings-triggered pass and return the activity events it emitted."""
    from app.worker import tasks_phd2

    events = []
    monkeypatch.setattr(tasks_phd2, "_read_settings", lambda: general)
    monkeypatch.setattr(tasks_phd2, "set_phd2_counts_sync", lambda *a, **kw: None)
    monkeypatch.setattr(
        tasks_phd2, "_emit_activity_sync",
        lambda *a, **kw: events.append((kw.get("event_type"), kw.get("message"))),
    )
    if sanity is not None:
        monkeypatch.setattr(
            tasks_phd2, "_session_date_sanity_check", lambda db, dates: sanity
        )
    tasks_phd2.scan_phd2_logs(force=True)
    return events


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
