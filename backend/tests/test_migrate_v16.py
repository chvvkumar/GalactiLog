"""Data migration v16: guiding provenance, profile re-key, and the history fill.

Ground truth here is NOT raw_headers, which is what v12/v14/v15 re-derived
from. A frame's guiding RMS was never in its FITS header: it arrived from a
N.I.N.A. sidecar CSV that is not retained, or it did not arrive at all. The
ground truth for this migration is the phd2_sessions/phd2_frames tables,
which hold the full sample stream the correlation reads, plus the structural
fact that until revision 0023 there was exactly one writer of the guiding
columns. Every value already stored is therefore CSV-sourced by construction,
and every value still missing is one the guide logs may be able to supply.
"""
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzmigratev16test"


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
            s.execute(
                text("DELETE FROM images WHERE file_path LIKE :p"),
                {"p": f"%{TEST_MARK}%"},
            )
            s.commit()

    _clean()
    yield Session
    _clean()
    engine.dispose()


def test_existing_values_are_stamped_csv(db):
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    image_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=image_id, file_path=f"/{TEST_MARK}/a.fits", file_name="a.fits",
            image_type="LIGHT", guiding_rms_arcsec=0.42,
        ))
        s.commit()
    with db() as s:
        summary = _migrate_v16_guiding_rms_provenance(s)
        s.commit()
    assert "1" in summary
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "csv"


def test_a_row_with_no_guiding_value_is_left_null(db):
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    image_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=image_id, file_path=f"/{TEST_MARK}/b.fits", file_name="b.fits",
            image_type="LIGHT",
        ))
        s.commit()
    with db() as s:
        _migrate_v16_guiding_rms_provenance(s)
        s.commit()
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source is None


def test_an_existing_stamp_is_not_overwritten(db):
    """Replay must be a no-op: only rows still NULL in the column are read."""
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    image_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=image_id, file_path=f"/{TEST_MARK}/c.fits", file_name="c.fits",
            image_type="LIGHT", guiding_rms_arcsec=0.42,
            guiding_rms_source="phd2",
        ))
        s.commit()
    with db() as s:
        _migrate_v16_guiding_rms_provenance(s)
        s.commit()
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"


def test_the_profile_map_is_rekeyed_through_the_current_aliases(db):
    """A profile mapped before the rig was grouped stores the raw name, and
    nothing ever rewrote it. Query-time expansion hides that on reads; the
    correlation writes need the stored value to be the canonical one."""
    from app.models.phd2 import Phd2Session
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    with db() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
        original_general = dict(row.general or {})
        original_equipment = dict(row.equipment or {})
        row.equipment = {
            "telescopes": {
                "SVBony 80ED": {"aliases": ["SVBony SV503 80mm"]},
            }
        }
        row.general = {
            **original_general,
            "phd2_profile_map": {"P_OAG": "SVBony SV503 80mm"},
        }
        from app.models.phd2 import Phd2Log

        s.add(Phd2Log(id=log_id, file_path=f"/{TEST_MARK}/g.txt", parse_status="ok"))
        s.flush()
        s.add(Phd2Session(
            id=session_id, log_id=log_id, run_index=0, section_index=0,
            started_at_local=datetime(2026, 7, 14, 22, 0, 0),
            started_at_utc=datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc),
            duration_s=1.0, session_date=date(2026, 7, 14),
            equipment_profile="P_OAG", telescope="SVBony SV503 80mm",
            events=[],
        ))
        s.commit()

    try:
        with db() as s:
            _migrate_v16_guiding_rms_provenance(s)
            s.commit()
        with db() as s:
            row = s.get(UserSettings, SETTINGS_ROW_ID)
            entry = row.general["phd2_profile_map"]["P_OAG"]
            # Rewritten through phd2_profiles, so the map comes back in the
            # canonical per-profile shape rather than the legacy bare name it
            # went in as. v17 would have converted it anyway.
            assert entry["telescope"] == "SVBony 80ED"
            assert s.get(Phd2Session, session_id).telescope == "SVBony 80ED"
    finally:
        with db() as s:
            row = s.get(UserSettings, SETTINGS_ROW_ID)
            row.general = original_general
            row.equipment = original_equipment
            s.commit()


def test_the_rekey_keeps_a_profiles_own_timezone_and_site(db):
    """A map already in the per-profile shape must come out of the re-key with
    its zone and coordinates intact. Rebuilding the map from bare telescope
    names, which is what this step used to do, would flatten a remote rig back
    to the global zone and site and shift every night it ever guided."""
    from app.models.phd2 import Phd2Log, Phd2Session
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    with db() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
        original_general = dict(row.general or {})
        original_equipment = dict(row.equipment or {})
        row.equipment = {
            "telescopes": {"SVBony 80ED": {"aliases": ["SVBony SV503 80mm"]}}
        }
        row.general = {
            **original_general,
            "phd2_profile_map": {
                "P_OAG": {
                    "telescope": "SVBony SV503 80mm",
                    "timezone": "America/Chicago",
                    "latitude": 30.27,
                    "longitude": -97.74,
                },
                "P_GREENWICH": {
                    "telescope": None,
                    "timezone": "Europe/London",
                    "latitude": 0.0,
                    "longitude": 0.0,
                },
            },
        }
        s.add(Phd2Log(id=log_id, file_path=f"/{TEST_MARK}/i.txt", parse_status="ok"))
        s.flush()
        s.add(Phd2Session(
            id=session_id, log_id=log_id, run_index=0, section_index=0,
            started_at_local=datetime(2026, 7, 14, 22, 0, 0),
            started_at_utc=datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc),
            duration_s=1.0, session_date=date(2026, 7, 14),
            equipment_profile="P_OAG", telescope="SVBony SV503 80mm",
            events=[],
        ))
        s.commit()

    try:
        with db() as s:
            _migrate_v16_guiding_rms_provenance(s)
            s.commit()
        with db() as s:
            row = s.get(UserSettings, SETTINGS_ROW_ID)
            stored = row.general["phd2_profile_map"]
            assert stored["P_OAG"] == {
                "telescope": "SVBony 80ED",
                "timezone": "America/Chicago",
                "latitude": 30.27,
                "longitude": -97.74,
            }
            # An unmapped profile is not renamed, and a longitude of 0.0 is a
            # rig on the prime meridian, not an unset value.
            assert stored["P_GREENWICH"] == {
                "telescope": None,
                "timezone": "Europe/London",
                "latitude": 0.0,
                "longitude": 0.0,
            }
            assert s.get(Phd2Session, session_id).telescope == "SVBony 80ED"
    finally:
        with db() as s:
            row = s.get(UserSettings, SETTINGS_ROW_ID)
            row.general = original_general
            row.equipment = original_equipment
            s.commit()


def _write_observer_timezone(Session, value):
    """Set user_settings.general.observer_timezone. Returns the previous dict.

    Step (c) of the migration is a correlation pass, and correlation declines
    to write per-image guiding values while this setting is empty: PHD2 writes
    bare local wall clock, so an unset zone reads it as the server's and shifts
    every guiding session by the observer's UTC offset.
    """
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
            s.flush()
        original = dict(row.general or {})
        row.general = {**original, "observer_timezone": value}
        s.commit()
    return original


def _restore_general(Session, general):
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is not None:
            row.general = dict(general)
            s.commit()


def _seed_a_guided_night(db, image_id):
    from app.models import Image
    from app.models.phd2 import Phd2Frame, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    start = datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc)
    with db() as s:
        s.add(Phd2Log(id=log_id, file_path=f"/{TEST_MARK}/h.txt", parse_status="ok"))
        s.flush()
        s.add(Phd2Session(
            id=session_id, log_id=log_id, run_index=0, section_index=0,
            started_at_local=datetime(2026, 7, 14, 22, 0, 0),
            started_at_utc=start, ended_at_utc=start + timedelta(seconds=120),
            duration_s=120.0, session_date=date(2026, 7, 14),
            equipment_profile="140APO_AM5N_ASI174MM", telescope="140APO",
            pixel_scale_arcsec=1.0, frame_count=120, events=[],
        ))
        s.flush()
        s.add_all([
            Phd2Frame(
                session_id=session_id, frame_index=i, time_offset=float(i),
                ra_raw=0.4 if i % 2 == 0 else -0.4,
                dec_raw=0.3 if i % 2 == 0 else -0.3, dropped=False,
            )
            for i in range(120)
        ])
        s.add(Image(
            id=image_id, file_path=f"/{TEST_MARK}/d.fits", file_name="d.fits",
            capture_date=start, session_date=date(2026, 7, 14),
            image_type="LIGHT", exposure_time=60.0, telescope="140APO",
        ))
        s.commit()


def test_the_migration_fills_history_from_the_guide_logs(db):
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    image_id = uuid.uuid4()
    _seed_a_guided_night(db, image_id)
    original = _write_observer_timezone(db, "America/Chicago")
    try:
        with db() as s:
            summary = _migrate_v16_guiding_rms_provenance(s)
            s.commit()
        assert "guiding" in summary.lower()
        with db() as s:
            image = s.get(Image, image_id)
            assert image.guiding_rms_source == "phd2"
            assert image.guiding_rms_arcsec == pytest.approx(0.5, abs=1e-3)
    finally:
        _restore_general(db, original)


def test_the_migration_does_not_fill_from_an_unvalidated_clock(db):
    """The migration reaches correlation through the same choke point the
    Celery dispatches do, so the guard covers it too. An install that upgrades
    before setting a timezone gets NULLs, which mean "not known" and are true,
    rather than an RMS measured hours away from the exposure it is stamped on.
    The CSV stamping in step (b) is unaffected: it is a statement about which
    code wrote the value, not about any clock."""
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    image_id = uuid.uuid4()
    _seed_a_guided_night(db, image_id)
    csv_id = uuid.uuid4()
    with db() as s:
        s.add(Image(
            id=csv_id, file_path=f"/{TEST_MARK}/f.fits", file_name="f.fits",
            image_type="LIGHT", guiding_rms_arcsec=0.42,
        ))
        s.commit()

    original = _write_observer_timezone(db, "")
    try:
        with db() as s:
            _migrate_v16_guiding_rms_provenance(s)
            s.commit()
        with db() as s:
            image = s.get(Image, image_id)
            assert image.guiding_rms_arcsec is None
            assert image.guiding_rms_source is None
            assert s.get(Image, csv_id).guiding_rms_source == "csv"
    finally:
        _restore_general(db, original)


def test_the_migration_is_idempotent(db):
    from app.models import Image
    from app.services.data_migrations import _migrate_v16_guiding_rms_provenance

    with db() as s:
        s.add(Image(
            file_path=f"/{TEST_MARK}/e.fits", file_name="e.fits",
            image_type="LIGHT", guiding_rms_arcsec=0.42,
        ))
        s.commit()
    with db() as s:
        _migrate_v16_guiding_rms_provenance(s)
        s.commit()
    with db() as s:
        second = _migrate_v16_guiding_rms_provenance(s)
        s.commit()
    assert "No changes needed" in second or "0" in second
