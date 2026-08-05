"""Data migration v17: the PHD2 profile map gains a timezone and a site.

The map used to be a profile name against a telescope name, so every rig was
read under the one global observer timezone and the one global observer
location. v17 writes the canonical per-profile entry into the settings row
once. It changes no behaviour by itself - an upgraded entry carries an empty
timezone and null coordinates, which are the inherit markers - so what these
tests pin is the shape, the no-ops, and the two things that are easy to get
wrong: an already-configured entry must survive untouched, and null must stay
null rather than becoming 0, because 0 is a real coordinate.

The forced re-parse the migration queues is pinned here too. It is not part of
the shape work: the guide-log parser changed in the same release and the
stored rows it affects short-circuit as "unchanged" on size and mtime, so only
a forced pass reaches them.
"""
import os
import sys

import pytest
from sqlalchemy import create_engine
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
    """A session factory, with user_settings.general restored afterwards.

    There is exactly one settings row and the rest of the suite reads it, so
    every test here puts back what it found regardless of outcome.
    """
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    Session, engine = _sync_session_factory()
    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
            s.flush()
        original = dict(row.general or {})
        s.commit()
    try:
        yield Session
    finally:
        with Session() as s:
            row = s.get(UserSettings, SETTINGS_ROW_ID)
            if row is not None:
                row.general = original
                s.commit()
        engine.dispose()


def _write_map(Session, value):
    """Store `value` as general.phd2_profile_map, or drop the key for None."""
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        general = dict(row.general or {})
        if value is None:
            general.pop("phd2_profile_map", None)
        else:
            general["phd2_profile_map"] = value
        row.general = general
        s.commit()


def _read_map(Session):
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        return (row.general or {}).get("phd2_profile_map")


def _run(Session, monkeypatch, dispatch=False):
    """Run v17, with the forced re-parse stubbed out by default.

    The dispatch reaches Celery and the broker, which a unit test has no
    business doing; the tests that care about it stub it deliberately.
    """
    from app.services import data_migrations

    monkeypatch.setattr(
        data_migrations, "_dispatch_phd2_reparse", lambda: dispatch
    )
    with Session() as s:
        summary = data_migrations._migrate_v17_phd2_profile_map_shape(s)
        s.commit()
    return summary


def test_a_legacy_map_gains_a_timezone_and_site_slot(db, monkeypatch):
    """The whole point of the migration: the bare telescope name becomes an
    entry with somewhere to put the rig's own zone and coordinates."""
    _write_map(db, {"P_OAG": "SVBony 80ED", "Remote": "Askar 120"})

    summary = _run(db, monkeypatch)

    assert _read_map(db) == {
        "P_OAG": {
            "telescope": "SVBony 80ED", "timezone": "",
            "latitude": None, "longitude": None,
        },
        "Remote": {
            "telescope": "Askar 120", "timezone": "",
            "latitude": None, "longitude": None,
        },
    }
    assert "2 PHD2 profile mapping(s)" in summary


def test_an_upgraded_entry_inherits_rather_than_moving_to_the_equator(db, monkeypatch):
    """The inherit marker for the coordinates is null, never 0. Writing 0 here
    would silently plant every upgraded rig on the equator at Greenwich and
    file its nights under the wrong date."""
    _write_map(db, {"P_OAG": "SVBony 80ED"})

    _run(db, monkeypatch)

    entry = _read_map(db)["P_OAG"]
    assert entry["latitude"] is None
    assert entry["longitude"] is None
    assert entry["timezone"] == ""


def test_a_canonical_map_is_left_alone(db, monkeypatch):
    """Already-configured entries must survive a replay byte for byte,
    including a longitude of 0.0, which is a rig on the prime meridian and not
    an unset value."""
    canonical = {
        "Rig A": {
            "telescope": "Askar 120", "timezone": "America/Chicago",
            "latitude": 30.27, "longitude": -97.74,
        },
        "Greenwich": {
            "telescope": None, "timezone": "Europe/London",
            "latitude": 0.0, "longitude": 0.0,
        },
    }
    _write_map(db, canonical)

    summary = _run(db, monkeypatch)

    assert _read_map(db) == canonical
    assert summary == "No changes needed"


def test_an_empty_map_is_a_no_op(db, monkeypatch):
    _write_map(db, {})

    summary = _run(db, monkeypatch)

    assert _read_map(db) == {}
    assert summary == "No changes needed"


def test_a_map_that_was_never_set_is_a_no_op(db, monkeypatch):
    """A fresh install has no key at all, which must not gain an empty one."""
    _write_map(db, None)

    summary = _run(db, monkeypatch)

    assert _read_map(db) is None
    assert summary == "No changes needed"


def test_the_migration_is_idempotent(db, monkeypatch):
    _write_map(db, {"P_OAG": "SVBony 80ED"})

    _run(db, monkeypatch)
    first = _read_map(db)
    second_summary = _run(db, monkeypatch)

    assert _read_map(db) == first
    assert second_summary == "No changes needed"


def test_the_migration_queues_a_forced_reparse(db, monkeypatch):
    """Not optional and not cosmetic. The guide-log parser changed in this
    release, and the rows that need it most are held as parse_status="empty"
    with unchanged size and mtime, so ingest short-circuits before reaching the
    new parser. Only forcing re-reads them."""
    from app.services import data_migrations

    dispatched = []

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            dispatched.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "app.worker.tasks",
        type("M", (), {"scan_phd2_logs": _Task})(),
    )
    _write_map(db, {})

    with db() as s:
        summary = data_migrations._migrate_v17_phd2_profile_map_shape(s)
        s.commit()

    assert len(dispatched) == 1
    assert dispatched[0]["kwargs"] == {"force": True}
    assert "re-parse" in summary


def test_a_missing_worker_does_not_fail_the_migration(db, monkeypatch):
    """The shape work is already committed by then, and a dev box or a
    single-container install may have no broker to queue against."""
    from app.services import data_migrations

    class _Broken:
        @staticmethod
        def apply_async(**kwargs):
            raise RuntimeError("no broker")

    monkeypatch.setitem(
        sys.modules, "app.worker.tasks",
        type("M", (), {"scan_phd2_logs": _Broken})(),
    )
    _write_map(db, {"P_OAG": "SVBony 80ED"})

    with db() as s:
        summary = data_migrations._migrate_v17_phd2_profile_map_shape(s)
        s.commit()

    assert _read_map(db)["P_OAG"]["telescope"] == "SVBony 80ED"
    assert "re-parse" not in summary
