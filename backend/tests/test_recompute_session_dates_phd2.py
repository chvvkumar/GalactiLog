"""Phase 4 of recompute_session_dates: PHD2 rows follow the imaging-night rule.

phd2_sessions is session_date-keyed like session_notes and custom_column_values.
Without this phase, toggling imaging-night or moving observer_longitude leaves
guiding sessions filed under the old night while every image moves, and the
session-detail join silently returns nothing.
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


def _seed(db):
    from app.models.phd2 import Phd2Calibration, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    with db() as s:
        s.add(Phd2Log(id=log_id, file_path=f"/{TEST_MARK}/g.txt", parse_status="ok"))
        # The phd2 models declare no relationship(), so the unit of work has no
        # dependency edge to order these inserts by. Flush the parent first or
        # the children hit the foreign key before the log row exists.
        s.flush()
        s.add(Phd2Session(
            id=session_id, log_id=log_id, run_index=0, section_index=0,
            # 01:42 UTC on the 15th is still the night of the 14th at -80 deg.
            started_at_local=datetime(2026, 7, 14, 21, 42, 27),
            started_at_utc=datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc),
            duration_s=120.0,
            session_date=date(2026, 7, 15),   # deliberately wrong going in
            equipment_profile="AM5n_OAG_ASI174M",
        ))
        s.add(Phd2Calibration(
            log_id=log_id,
            started_at_local=datetime(2026, 7, 14, 21, 41, 21),
            started_at_utc=datetime(2026, 7, 15, 1, 41, 21, tzinfo=timezone.utc),
            session_date=date(2026, 7, 15),
            equipment_profile="AM5n_OAG_ASI174M",
        ))
        s.commit()
    return log_id, session_id


def test_rekey_moves_sessions_onto_the_imaging_night(db):
    from app.models.phd2 import Phd2Calibration, Phd2Session
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    _, session_id = _seed(db)
    with db() as s:
        changed = _rekey_phd2_sessions(s, use_night=True, longitude=-80.0)
        s.commit()
    assert changed == 2

    with db() as s:
        assert s.get(Phd2Session, session_id).session_date == date(2026, 7, 14)
        cal = s.execute(
            select(Phd2Calibration).where(Phd2Calibration.session_date.isnot(None))
            .where(Phd2Calibration.equipment_profile == "AM5n_OAG_ASI174M")
        ).scalars().first()
        assert cal.session_date == date(2026, 7, 14)


def test_rekey_falls_back_to_utc_midnight_when_imaging_night_is_off(db):
    from app.models.phd2 import Phd2Session
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    _, session_id = _seed(db)
    with db() as s:
        _rekey_phd2_sessions(s, use_night=False, longitude=-80.0)
        s.commit()
    with db() as s:
        assert s.get(Phd2Session, session_id).session_date == date(2026, 7, 15)


def test_rekey_is_idempotent(db):
    from app.worker.tasks_sessions import _rekey_phd2_sessions

    _seed(db)
    with db() as s:
        _rekey_phd2_sessions(s, use_night=True, longitude=-80.0)
        s.commit()
    with db() as s:
        assert _rekey_phd2_sessions(s, use_night=True, longitude=-80.0) == 0


def test_recompute_task_runs_a_phd2_phase():
    """The task body must call the re-key helper, or PHD2 rows desync silently."""
    import inspect

    from app.worker import tasks_sessions

    source = inspect.getsource(tasks_sessions.recompute_session_dates)
    assert "_rekey_phd2_sessions" in source
