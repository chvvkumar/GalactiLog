"""Phase 4 of recompute_session_dates: PHD2 rows follow the imaging-night rule.

phd2_sessions is session_date-keyed like session_notes and custom_column_values.
Without this phase, toggling imaging-night or moving observer_longitude leaves
guiding sessions filed under the old night while every image moves, and the
session-detail join silently returns nothing.

The re-key resolves a longitude PER EQUIPMENT PROFILE rather than taking one
value for the whole catalogue, which is what images have always done from their
own FITS headers. A rig taken to a star party twelve degrees west of home keeps
the user's timezone but not the user's night boundary, and twelve degrees is
forty-eight minutes of it.

Several timestamps here sit deliberately within an hour of a site's solar noon.
That is where two longitudes disagree about which night a moment belongs to, so
it is the only place the per-profile behaviour is observable at all.
"""
import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzphd2rekeytest"

# The user's home site and a star party twelve degrees west of it. Same country,
# same IANA zone, forty-eight minutes of longitude apart.
HOME_LON = -97.74
PARTY_LON = -109.74

HOME_PROFILE = "AM5n_OAG_ASI174M"
PARTY_PROFILE = "StarParty_Redcat"

# 18:45 UTC is 00:14 past the home site's noon boundary and 33 minutes short of
# the star party's, so the two sites file this instant under different nights.
BOUNDARY_UTC = datetime(2026, 7, 15, 18, 45, 0, tzinfo=timezone.utc)

# 12:30 UTC is half an hour past Greenwich's noon boundary and six hours short
# of the home site's.
GREENWICH_BOUNDARY_UTC = datetime(2026, 7, 15, 12, 30, 0, tzinfo=timezone.utc)

# A plain night-time capture, well clear of every boundary in this file.
NIGHT_UTC = datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc)


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


def _resolver(per_profile, fallback=None):
    """A stand-in for longitude_resolver, so a test states its own answers."""
    def resolve(profile):
        return per_profile.get(profile or "", fallback)
    return resolve


def _seed(db, rows, stored_date=date(1999, 1, 1)):
    """Insert one session and one calibration per (profile, started_at_utc).

    `stored_date` is deliberately absurd so that every assertion below is about
    a date the re-key wrote, never one that happened to be there already.
    """
    from app.models.phd2 import Phd2Calibration, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    ids = []
    with db() as s:
        s.add(Phd2Log(id=log_id, file_path=f"/{TEST_MARK}/g.txt", parse_status="ok"))
        # The phd2 models declare no relationship(), so the unit of work has no
        # dependency edge to order these inserts by. Flush the parent first or
        # the children hit the foreign key before the log row exists.
        s.flush()
        for index, (profile, started_utc) in enumerate(rows):
            session_id = uuid.uuid4()
            cal_id = uuid.uuid4()
            local = started_utc.replace(tzinfo=None)
            s.add(Phd2Session(
                id=session_id, log_id=log_id, run_index=0, section_index=index,
                started_at_local=local,
                started_at_utc=started_utc,
                duration_s=120.0,
                session_date=stored_date,
                equipment_profile=profile,
            ))
            s.add(Phd2Calibration(
                id=cal_id, log_id=log_id,
                started_at_local=local,
                started_at_utc=started_utc,
                session_date=stored_date,
                equipment_profile=profile,
            ))
            ids.append((session_id, cal_id))
        s.commit()
    return ids


def _dates(db, ids):
    from app.models.phd2 import Phd2Calibration, Phd2Session

    with db() as s:
        return [
            (s.get(Phd2Session, sid).session_date,
             s.get(Phd2Calibration, cid).session_date)
            for sid, cid in ids
        ]


def test_two_profiles_with_different_longitudes_land_on_different_nights(db):
    """The star-party case: one instant, two rigs, two nights."""
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [(HOME_PROFILE, BOUNDARY_UTC), (PARTY_PROFILE, BOUNDARY_UTC)])
    resolve = _resolver({HOME_PROFILE: HOME_LON, PARTY_PROFILE: PARTY_LON})
    with db() as s:
        changed = _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert changed == 4
    home, party = _dates(db, ids)
    assert home == (date(2026, 7, 15), date(2026, 7, 15))
    assert party == (date(2026, 7, 14), date(2026, 7, 14))


def test_calibrations_resolve_their_own_profile_longitude(db):
    """A calibration carries equipment_profile too, so it must resolve per row."""
    from app.models.phd2 import Phd2Calibration
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    _seed(db, [(HOME_PROFILE, BOUNDARY_UTC), (PARTY_PROFILE, BOUNDARY_UTC)])
    resolve = _resolver({HOME_PROFILE: HOME_LON, PARTY_PROFILE: PARTY_LON})
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    with db() as s:
        by_profile = {
            row.equipment_profile: row.session_date
            for row in s.execute(select(Phd2Calibration)).scalars().all()
            if row.equipment_profile in (HOME_PROFILE, PARTY_PROFILE)
        }
    assert by_profile[HOME_PROFILE] == date(2026, 7, 15)
    assert by_profile[PARTY_PROFILE] == date(2026, 7, 14)


def test_the_resolver_is_asked_for_each_row_own_profile(db):
    """The helper resolves through the callable it is given, per row.

    Pinning this keeps the map normalization at the caller, where it happens
    once per pass, instead of drifting back inside the row loop.
    """
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    seen = []

    def resolve(profile):
        seen.append(profile)
        return HOME_LON

    _seed(db, [(HOME_PROFILE, NIGHT_UTC), (PARTY_PROFILE, NIGHT_UTC)])
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert seen.count(HOME_PROFILE) == 2
    assert seen.count(PARTY_PROFILE) == 2


def test_a_profile_absent_from_the_map_inherits_the_global_longitude(db):
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [("NeverConfigured", BOUNDARY_UTC)])
    resolve = _resolver({HOME_PROFILE: PARTY_LON}, fallback=HOME_LON)
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 15), date(2026, 7, 15))]


def test_a_row_with_no_equipment_profile_inherits_the_global_longitude(db):
    """Sections whose header names no profile still get the global value."""
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [(None, BOUNDARY_UTC)])
    resolve = _resolver({}, fallback=PARTY_LON)
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 14), date(2026, 7, 14))]


def test_longitude_zero_is_a_site_not_an_unset_marker(db):
    """A rig on the prime meridian keeps its own boundary.

    A falsy test on the resolved longitude would send this row to the home
    site's night instead, which is the defect this pins.
    """
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [("Greenwich", GREENWICH_BOUNDARY_UTC)])
    resolve = _resolver({"Greenwich": 0.0}, fallback=HOME_LON)
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 15), date(2026, 7, 15))]


def test_no_longitude_anywhere_falls_back_to_utc_midnight(db):
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [(HOME_PROFILE, BOUNDARY_UTC)])
    with db() as s:
        _rekey_phd2_sessions(
            s, use_night=True, resolve_longitude=_resolver({}, fallback=None)
        )
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 15), date(2026, 7, 15))]


def test_rekey_falls_back_to_utc_midnight_when_imaging_night_is_off(db):
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    ids = _seed(db, [(PARTY_PROFILE, BOUNDARY_UTC)])
    resolve = _resolver({PARTY_PROFILE: PARTY_LON})
    with db() as s:
        _rekey_phd2_sessions(s, use_night=False, resolve_longitude=resolve)
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 15), date(2026, 7, 15))]


def test_rekey_is_idempotent(db):
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    _seed(db, [(HOME_PROFILE, BOUNDARY_UTC), (PARTY_PROFILE, BOUNDARY_UTC)])
    resolve = _resolver({HOME_PROFILE: HOME_LON, PARTY_PROFILE: PARTY_LON})
    with db() as s:
        assert _rekey_phd2_sessions(
            s, use_night=True, resolve_longitude=resolve
        ) == 4
        s.commit()
    with db() as s:
        assert _rekey_phd2_sessions(
            s, use_night=True, resolve_longitude=resolve
        ) == 0


def test_a_junk_global_longitude_produces_utc_midnight_not_junk_arithmetic(db):
    """An out-of-range stored global longitude reads as unset, end to end.

    phd2_profiles coerces the global value through the same range check as the
    per-profile ones, so an install that stored 999 stops doing arithmetic with
    it. The nights such an install has on disk therefore MOVE on the next pass,
    from a nonsense boundary to UTC midnight. That is the intended correction,
    and this test is what says so out loud.
    """
    from app.services.phd2_profiles import longitude_resolver
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    resolve = longitude_resolver({}, 999.0)
    assert resolve(HOME_PROFILE) is None

    ids = _seed(db, [(HOME_PROFILE, BOUNDARY_UTC)])
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, resolve_longitude=resolve)
        s.commit()

    assert _dates(db, ids) == [(date(2026, 7, 15), date(2026, 7, 15))]


def test_the_real_resolver_drives_the_rekey_from_a_stored_profile_map(db):
    """The production wiring: a stored map, no test double in the path."""
    from app.services.phd2_profiles import longitude_resolver
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    stored = {
        HOME_PROFILE: {"telescope": "Askar 120", "timezone": "America/Chicago",
                       "latitude": 30.27, "longitude": HOME_LON},
        PARTY_PROFILE: {"telescope": "Redcat 51", "timezone": "America/Chicago",
                        "latitude": 31.9, "longitude": PARTY_LON},
        # Legacy string entry: no site of its own, inherits the global value.
        "OldRig": "Askar 120",
    }
    ids = _seed(db, [
        (HOME_PROFILE, BOUNDARY_UTC),
        (PARTY_PROFILE, BOUNDARY_UTC),
        ("OldRig", BOUNDARY_UTC),
    ])
    with db() as s:
        _rekey_phd2_sessions(
            s, use_night=True,
            resolve_longitude=longitude_resolver(stored, HOME_LON),
        )
        s.commit()

    assert _dates(db, ids) == [
        (date(2026, 7, 15), date(2026, 7, 15)),
        (date(2026, 7, 14), date(2026, 7, 14)),
        (date(2026, 7, 15), date(2026, 7, 15)),
    ]


def test_recompute_task_runs_a_phd2_phase():
    """The task body must call the re-key helper, or PHD2 rows desync silently."""
    import inspect

    from app.worker import tasks_sessions

    source = inspect.getsource(tasks_sessions.recompute_session_dates)
    assert "_rekey_phd2_sessions" in source


def test_recompute_task_builds_the_profile_resolver_once():
    """The map is normalized once per run, not once per stored row."""
    import inspect

    from app.worker import tasks_sessions

    source = inspect.getsource(tasks_sessions.recompute_session_dates)
    assert source.count("longitude_resolver(") == 1
    assert "resolve_longitude=" in source
