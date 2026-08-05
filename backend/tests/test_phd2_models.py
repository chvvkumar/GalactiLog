"""Schema round-trip for the four PHD2 tables created by alembic 0022.

Uses a real sync engine against the test DB (same pattern as
test_image_panel_membership.py): the cascade deletes, the BIGSERIAL frame id,
and the JSONB columns are Postgres behaviour, not something a mocked session
would prove.
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

TEST_MARK = "zzphd2modeltest"


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
    with Session() as s:
        s.execute(text("DELETE FROM phd2_logs WHERE file_path LIKE :p"), {"p": f"/{TEST_MARK}%"})
        s.commit()
    yield Session
    with Session() as s:
        s.execute(text("DELETE FROM phd2_logs WHERE file_path LIKE :p"), {"p": f"/{TEST_MARK}%"})
        s.commit()
    engine.dispose()


def test_models_are_exported_from_app_models():
    import app.models as models

    assert models.Phd2Log is not None
    assert models.Phd2Session is not None
    assert models.Phd2Frame is not None
    assert models.Phd2Calibration is not None


def test_full_round_trip_and_cascade_delete(db):
    from app.models.phd2 import Phd2Calibration, Phd2Frame, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    with db() as s:
        s.add(Phd2Log(
            id=log_id,
            file_path=f"/{TEST_MARK}/PHD2_GuideLog_2026-07-14_201333.txt",
            file_size=123456,
            file_mtime=1752537213.0,
            parse_status="ok",
            phd2_version="2.6.14",
            log_version="2.5",
            run_count=1,
            session_count=1,
            calibration_count=1,
        ))
        # The models carry no ORM relationship(), so the unit of work has no
        # parent-before-child ordering to infer: flush each level explicitly.
        s.flush()
        s.add(Phd2Session(
            id=session_id,
            log_id=log_id,
            run_index=0,
            section_index=0,
            started_at_local=datetime(2026, 7, 14, 21, 42, 27),
            started_at_utc=datetime(2026, 7, 15, 1, 42, 27, tzinfo=timezone.utc),
            ended_at_utc=datetime(2026, 7, 15, 1, 42, 46, tzinfo=timezone.utc),
            duration_s=19.0,
            session_date=date(2026, 7, 14),
            equipment_profile="AM5n_OAG_ASI174M",
            telescope="140APO",
            pixel_scale_arcsec=1.54,
            frame_count=5,
            drop_count=1,
            max_drop_run=1,
            unguided_seconds=2.0,
            rms_total_arcsec=0.61,
            pulse_count_ra_west=2,
            pulse_count_ra_east=1,
            pulse_count_dec_north=0,
            pulse_count_dec_south=1,
            pulse_total_ms_ra=331,
            pulse_total_ms_dec=267,
            dither_count=1,
            settle_count=1,
            settle_failed_count=0,
            star_lost_reasons={"Star lost - mass changed": 1},
            events=[{"type": "dither", "t": 7.381, "detail": "3.4, -1.2"}],
            truncated=False,
        ))
        s.flush()
        s.add(Phd2Frame(
            session_id=session_id,
            frame_index=1,
            time_offset=1.228,
            dx=0.330, dy=0.544, ra_raw=0.556, dec_raw=-0.189,
            ra_guide=0.350, dec_guide=0.0,
            ra_duration_ms=98, ra_direction="W",
            dec_duration_ms=0, dec_direction="",
            star_mass=1713.0, snr=28.59, error_code=1, dropped=False,
        ))
        s.add(Phd2Calibration(
            log_id=log_id,
            started_at_local=datetime(2026, 7, 14, 21, 41, 21),
            started_at_utc=datetime(2026, 7, 15, 1, 41, 21, tzinfo=timezone.utc),
            session_date=date(2026, 7, 14),
            equipment_profile="AM5n_OAG_ASI174M",
            west_angle_deg=87.9, west_rate_px_s=3.579, west_parity="N/A",
            north_angle_deg=-170.3, north_rate_px_s=4.437, north_parity="N/A",
            completed=True,
            steps=[{"direction": "West", "step": 0, "dx": 0.0, "dy": 0.0,
                    "x": 86.217, "y": 202.308, "dist": 0.0}],
        ))
        s.commit()

    with db() as s:
        sess = s.get(Phd2Session, session_id)
        assert sess.star_lost_reasons == {"Star lost - mass changed": 1}
        assert sess.events[0]["type"] == "dither"
        frame = s.execute(
            select(Phd2Frame).where(Phd2Frame.session_id == session_id)
        ).scalar_one()
        # BIGSERIAL: the id is assigned by the database, not the caller.
        assert isinstance(frame.id, int)
        assert frame.ra_direction == "W"
        assert frame.dropped is False

    with db() as s:
        s.delete(s.get(Phd2Log, log_id))
        s.commit()

    with db() as s:
        assert s.execute(
            select(Phd2Session).where(Phd2Session.id == session_id)
        ).scalar_one_or_none() is None
        assert s.execute(
            select(Phd2Frame).where(Phd2Frame.session_id == session_id)
        ).scalar_one_or_none() is None
        assert s.execute(
            select(Phd2Calibration).where(Phd2Calibration.log_id == log_id)
        ).scalar_one_or_none() is None


def test_expected_indexes_exist(db):
    with db() as s:
        rows = s.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename IN ('phd2_logs','phd2_sessions','phd2_frames','phd2_calibrations')"
        )).scalars().all()
    names = set(rows)
    assert "ix_phd2_sessions_session_date" in names
    assert "ix_phd2_sessions_telescope_session_date" in names
    assert "ix_phd2_sessions_started_at_utc" in names
    assert "ix_phd2_sessions_log_id" in names
    assert "ix_phd2_frames_session_frame" in names
    assert "ix_phd2_frames_session_time" in names
    assert "ix_phd2_calibrations_log_id" in names
    assert "ix_phd2_calibrations_session_date" in names
