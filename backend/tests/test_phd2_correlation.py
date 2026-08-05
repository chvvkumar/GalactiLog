"""Per-image guiding RMS computed from the PHD2 frame stream.

A session RMS answers "how did guiding go last night". These tests pin the
per-image answer: "was THIS sub guided well", which is what the Analysis
correlations and the WBPP quality filter consume. The two figures must be
the same measurement at two grains - population standard deviation of the
raw RA/Dec distances in arcsec, DROP frames and dither/settle windows
excluded - or a frame table and the session panel above it disagree.
"""
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "GALACTILOG_DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test_catalog",
)

TEST_MARK = "zzphd2correlationtest"

EPOCH = datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc)

# Correlation refuses to write per-image values while observer_timezone is
# unset, because PHD2 writes bare local wall clock and an unset zone silently
# reads it as the server's. Every end-to-end test below therefore runs with a
# configured zone, and the guard tests blank it themselves.
OBSERVER_TZ = "America/Chicago"
TIMEZONE_UNSET_EVENT = "phd2_correlation_timezone_unset"


def _write_observer_timezone(Session, value):
    """Set user_settings.general.observer_timezone. Returns the previous dict."""
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
            s.flush()
        original = dict(row.general or {})
        # Whole-value assignment: SQLAlchemy tracks JSONB by identity, so a
        # mutation of the stored dict would never be flushed.
        row.general = {**original, "observer_timezone": value}
        s.commit()
    return original


def _write_profile_map(Session, mapping):
    """Set user_settings.general.phd2_profile_map to the given raw value."""
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is None:
            row = UserSettings(id=SETTINGS_ROW_ID)
            s.add(row)
            s.flush()
        row.general = {**dict(row.general or {}), "phd2_profile_map": mapping}
        s.commit()


def _restore_general(Session, general):
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings

    with Session() as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        if row is not None:
            row.general = dict(general)
            s.commit()


def _guard_warnings(Session):
    """Every activity row the timezone guard has emitted."""
    with Session() as s:
        return s.execute(
            text(
                "SELECT severity, category, message FROM activity_events "
                "WHERE event_type = :e ORDER BY id"
            ),
            {"e": TIMEZONE_UNSET_EVENT},
        ).all()


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
            s.execute(
                text("DELETE FROM activity_events WHERE event_type = :e"),
                {"e": TIMEZONE_UNSET_EVENT},
            )
            s.commit()

    _clean()
    original_general = _write_observer_timezone(Session, OBSERVER_TZ)
    try:
        yield Session
    finally:
        _restore_general(Session, original_general)
        _clean()
        engine.dispose()


# --- pure-function fixtures -------------------------------------------------

@dataclass
class FakeSession:
    """Stands in for a Phd2Session row in the pure-function tests."""

    id: uuid.UUID
    telescope: str | None = None
    equipment_profile: str | None = None
    pixel_scale_arcsec: float | None = 1.0
    started_at_utc: datetime = EPOCH
    events: list | None = None


def _frames(count, *, step=1.0, ra=0.5, dec=-0.5, dropped=False, start=0.0):
    """(time_offset, ra_raw, dec_raw, dropped) tuples, the query's row shape."""
    return [
        (start + i * step, ra, dec, dropped)
        for i in range(count)
    ]


# --- window rule parity -----------------------------------------------------

def test_stored_events_produce_the_same_windows_as_parsed_events():
    """The per-image RMS must exclude the frames the session RMS excludes.
    Two code paths computing that rule independently is how they drift."""
    from app.services.phd2_metrics import (
        dither_settle_windows, dither_settle_windows_from_stored,
    )
    from app.services import phd2_parser

    section = phd2_parser.Phd2GuidingSection(
        started_at_local=datetime(2026, 7, 14, 21, 0, 0),
        header=phd2_parser.Phd2Header(),
    )
    section.events = [
        phd2_parser.Phd2Event(type="dither", time_offset=10.0, detail=""),
        phd2_parser.Phd2Event(type="settle_done", time_offset=16.0, detail=""),
        phd2_parser.Phd2Event(type="settle_start", time_offset=30.0, detail=""),
    ]
    # The parser dataclass declares no defaults, so every field is spelled
    # out; only frame_index and time_offset carry meaning for this rule.
    section.frames = [phd2_parser.Phd2Frame(
        frame_index=1, time_offset=40.0, dropped=False,
        dx=0.0, dy=0.0, ra_raw=0.0, dec_raw=0.0, ra_guide=0.0, dec_guide=0.0,
        ra_duration_ms=0, ra_direction="", dec_duration_ms=0, dec_direction="",
        star_mass=None, snr=None, error_code=0, drop_reason="",
    )]

    stored = [
        {"type": e.type, "t": e.time_offset, "detail": e.detail}
        for e in section.events
    ]
    assert dither_settle_windows(section) == dither_settle_windows_from_stored(
        stored, 40.0
    )
    assert dither_settle_windows_from_stored(stored, 40.0) == [(10.0, 16.0), (30.0, 40.0)]


def test_samples_exclude_dropped_frames_and_dither_windows():
    from app.services.phd2_correlation import guide_samples

    session = FakeSession(
        id=uuid.uuid4(),
        pixel_scale_arcsec=2.0,
        events=[
            {"type": "dither", "t": 2.0, "detail": ""},
            {"type": "settle_done", "t": 4.0, "detail": ""},
        ],
    )
    frames = [
        (1.0, 0.5, -0.25, False),   # kept
        (3.0, 9.0, 9.0, False),     # inside the dither window
        (5.0, 0.5, -0.25, True),    # DROP
        (6.0, 0.5, -0.25, False),   # kept
    ]
    samples = guide_samples(session, frames)
    assert [round(s[0] - EPOCH.timestamp(), 3) for s in samples] == [1.0, 6.0]
    # pixels * pixel scale
    assert samples[0][1] == pytest.approx(1.0)
    assert samples[0][2] == pytest.approx(-0.5)


def test_samples_are_empty_without_a_pixel_scale():
    """Frames are stored in pixels; with no scale there is nothing to convert
    them with and an arcsec figure would be a fabrication."""
    from app.services.phd2_correlation import guide_samples

    session = FakeSession(id=uuid.uuid4(), pixel_scale_arcsec=None)
    assert guide_samples(session, _frames(50)) == []


# --- the window RMS and its gate --------------------------------------------

def test_window_rms_is_the_population_stdev_in_arcsec():
    from app.services.phd2_correlation import window_rms

    base = EPOCH.timestamp()
    # Alternating +1/-1 arcsec in RA, constant 0 in Dec: pstdev is exactly 1.
    samples = [
        (base + i, 1.0 if i % 2 == 0 else -1.0, 0.0) for i in range(20)
    ]
    result = window_rms(samples, base, base + 19)
    assert result is not None
    ra, dec, total = result
    assert ra == pytest.approx(1.0)
    assert dec == pytest.approx(0.0)
    assert total == pytest.approx(1.0)


def test_a_thin_window_is_left_alone_rather_than_guessed_at():
    """Fewer than MIN_CORRELATION_FRAMES samples is not an RMS, it is noise.
    Leaving NULL is honest; a short sub with sparse guiding is normal and
    warrants no warning."""
    from app.services.phd2_correlation import MIN_CORRELATION_FRAMES, window_rms

    base = EPOCH.timestamp()
    samples = [(base + i, 1.0, 0.0) for i in range(MIN_CORRELATION_FRAMES - 1)]
    assert window_rms(samples, base, base + 60) is None


def test_a_window_guiding_covered_only_briefly_is_left_alone():
    """20 samples in the first 10 seconds of a 300 s sub describe 3% of that
    sub. Reporting them as the sub's guiding RMS would be a lie by omission."""
    from app.services.phd2_correlation import window_rms

    base = EPOCH.timestamp()
    samples = [(base + i * 0.5, 1.0, 0.0) for i in range(20)]
    assert window_rms(samples, base, base + 300) is None


def test_coverage_is_measured_against_the_exposure_interval():
    from app.services.phd2_correlation import (
        MIN_CORRELATION_COVERAGE, window_rms,
    )

    assert MIN_CORRELATION_COVERAGE == 0.5
    base = EPOCH.timestamp()
    # 60 samples spanning 59 s of a 100 s exposure: 59% covered, passes.
    samples = [(base + i, 1.0 if i % 2 else -1.0, 0.0) for i in range(60)]
    assert window_rms(samples, base, base + 100) is not None


# --- attribution ------------------------------------------------------------

def test_a_mapped_profile_attributes_through_the_alias_map_in_both_directions():
    """A profile mapped before the rig was grouped stores the raw name and the
    map is never rewritten, so folding one side is not enough."""
    from app.services.phd2_correlation import attribute_sessions_to_rigs

    session = FakeSession(
        id=uuid.uuid4(), telescope="SVBony SV503 80mm", equipment_profile="P1"
    )
    alias_map = {"SVBony SV503 80mm": "SVBony 80ED"}
    attributed, unattributed = attribute_sessions_to_rigs(
        [session], {"SVBony 80ED"}, alias_map
    )
    assert list(attributed) == ["SVBony 80ED"]
    assert attributed["SVBony 80ED"] == [session]
    assert unattributed == []


def test_a_sole_unmapped_profile_attributes_on_a_single_rig_night():
    from app.services.phd2_correlation import attribute_sessions_to_rigs

    session = FakeSession(id=uuid.uuid4(), telescope=None, equipment_profile="P1")
    attributed, unattributed = attribute_sessions_to_rigs(
        [session], {"140APO"}, {}
    )
    assert attributed == {"140APO": [session]}
    assert unattributed == []


def test_a_sole_unmapped_profile_attributes_nothing_on_a_multi_rig_night():
    """Guessing would put the guided rig's numbers on the other rig's frames
    too. Spec decision 4: skip attribution and name the profile."""
    from app.services.phd2_correlation import attribute_sessions_to_rigs

    session = FakeSession(id=uuid.uuid4(), telescope=None, equipment_profile="P1")
    attributed, unattributed = attribute_sessions_to_rigs(
        [session], {"140APO", "SVBony 80ED"}, {}
    )
    assert attributed == {}
    assert unattributed == ["P1"]


def test_two_spellings_of_one_rig_are_one_rig_for_the_veto():
    """The veto counts rigs, and two spellings of a rig are still one rig.

    A rig routinely appears under several names across a night's headers,
    which is the whole reason the alias map exists. Counting the raw strings
    would read one physical rig as two, veto its own sole unmapped profile,
    and leave the night empty with a warning naming a profile that was never
    ambiguous - a fabricated conflict producing a real data loss.
    """
    from app.services.phd2_correlation import attribute_sessions_to_rigs

    session = FakeSession(
        id=uuid.uuid4(), telescope=None, equipment_profile="SOLO_PROFILE"
    )
    alias_map = {"SVBony SV503 80mm": "SVBony 80ED"}
    attributed, unattributed = attribute_sessions_to_rigs(
        [session], {"SVBony SV503 80mm", "SVBony 80ED"}, alias_map
    )
    assert unattributed == []
    # Both spellings attribute, so an image stored under either one fills.
    assert sorted(attributed) == ["SVBony 80ED", "SVBony SV503 80mm"]
    assert all(rows == [session] for rows in attributed.values())

    # The contrast: two names that do NOT alias together are two rigs, and
    # the same sole unmapped profile is vetoed and named.
    attributed, unattributed = attribute_sessions_to_rigs(
        [session], {"140APO", "SVBony 80ED"}, alias_map
    )
    assert attributed == {}
    assert unattributed == ["SOLO_PROFILE"]


def test_two_unmapped_profiles_attribute_nothing_even_on_one_rig():
    from app.services.phd2_correlation import attribute_sessions_to_rigs

    sessions = [
        FakeSession(id=uuid.uuid4(), telescope=None, equipment_profile="P1"),
        FakeSession(id=uuid.uuid4(), telescope=None, equipment_profile="P2"),
    ]
    attributed, unattributed = attribute_sessions_to_rigs(sessions, {"140APO"}, {})
    assert attributed == {}
    assert unattributed == ["P1", "P2"]


# --- end to end over the database -------------------------------------------

def _seed_night(db, *, telescope="140APO", profile="140APO_AM5N_ASI174MM",
                mapped=True, exposure=60.0, frame_count=120,
                image_rms=None, image_source=None, second_rig=False,
                second_rig_rms=None, second_rig_source=None,
                second_rig_telescope="SVBony 80ED",
                night=date(2026, 7, 14), tag="a"):
    """One image and one guiding session covering it, on 2026-07-14.

    `night` and `tag` exist for the tests that need two independent nights in
    one pass; every other caller takes the defaults and gets exactly the
    fixture this file has always seeded. `second_rig` only ever applies to the
    default night, so its file path stays the fixed one `_second_rig_image`
    looks up.
    """
    from app.models import Image
    from app.models.phd2 import Phd2Frame, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    session_id = uuid.uuid4()
    image_id = uuid.uuid4()
    start = datetime(
        night.year, night.month, night.day, 2, 0, 0, tzinfo=timezone.utc
    ) + timedelta(days=1)

    with db() as s:
        s.add(Phd2Log(
            id=log_id, file_path=f"/{TEST_MARK}/g-{tag}.txt", parse_status="ok"
        ))
        s.flush()
        s.add(Phd2Session(
            id=session_id, log_id=log_id, run_index=0, section_index=0,
            started_at_local=start.replace(tzinfo=None) - timedelta(hours=4),
            started_at_utc=start,
            ended_at_utc=start + timedelta(seconds=frame_count),
            duration_s=float(frame_count),
            session_date=night,
            equipment_profile=profile,
            telescope=telescope if mapped else None,
            pixel_scale_arcsec=1.0,
            frame_count=frame_count,
            events=[],
        ))
        s.flush()
        s.add_all([
            Phd2Frame(
                session_id=session_id, frame_index=i, time_offset=float(i),
                ra_raw=0.4 if i % 2 == 0 else -0.4,
                dec_raw=0.3 if i % 2 == 0 else -0.3,
                dropped=False,
            )
            for i in range(frame_count)
        ])
        s.add(Image(
            id=image_id,
            file_path=f"/{TEST_MARK}/{tag}.fits", file_name=f"{tag}.fits",
            capture_date=start, session_date=night,
            image_type="LIGHT", exposure_time=exposure,
            telescope=telescope,
            guiding_rms_arcsec=image_rms,
            guiding_rms_source=image_source,
        ))
        if second_rig:
            s.add(Image(
                id=uuid.uuid4(),
                file_path=f"/{TEST_MARK}/b.fits", file_name="b.fits",
                capture_date=start, session_date=night,
                image_type="LIGHT", exposure_time=exposure,
                telescope=second_rig_telescope,
                guiding_rms_arcsec=second_rig_rms,
                guiding_rms_source=second_rig_source,
            ))
        s.commit()
    return image_id


def test_correlation_fills_a_covered_exposure(db):
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.filled == 1
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_source == "phd2"
        assert image.guiding_rms_ra_arcsec == pytest.approx(0.4, abs=1e-3)
        assert image.guiding_rms_dec_arcsec == pytest.approx(0.3, abs=1e-3)
        assert image.guiding_rms_arcsec == pytest.approx(0.5, abs=1e-3)


def test_a_csv_value_is_never_overwritten(db):
    """Spec decision 5: the CSV is the frame's own instrument record and wins."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, image_rms=0.99, image_source="csv")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.filled == 0
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec == pytest.approx(0.99)
        assert image.guiding_rms_source == "csv"


def test_re_deriving_a_night_clears_its_stale_phd2_values_first(db):
    """A re-ingested log or an edited profile map can invalidate a value that
    was right when it was written. Without the clear, a frame that no longer
    qualifies keeps yesterday's number forever."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, image_rms=0.11, image_source="phd2", exposure=1.0)
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.cleared == 1
    with db() as s:
        image = s.get(Image, image_id)
        # A 1 s exposure holds too few samples to re-qualify, so the stale
        # value is gone rather than silently retained.
        assert image.guiding_rms_arcsec is None
        assert image.guiding_rms_source is None


def test_incremental_mode_never_clears(db):
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, image_rms=0.11, image_source="phd2", exposure=1.0)
    with db() as s:
        result = correlate_dates(s, None)
        s.commit()
    assert result.cleared == 0
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_arcsec == pytest.approx(0.11)


def test_correlation_is_idempotent(db):
    from app.services.phd2_correlation import correlate_dates

    _seed_night(db)
    with db() as s:
        correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    with db() as s:
        second = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert second.filled == 1
    assert second.cleared == 1


def test_an_unmapped_profile_on_a_multi_rig_night_is_reported_not_guessed(db):
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, mapped=False, second_rig=True)
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.filled == 0
    assert result.unattributed_profiles == ["140APO_AM5N_ASI174MM"]
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_arcsec is None


def _second_rig_image(session):
    from app.models import Image

    return session.execute(
        select(Image).where(Image.file_path == f"/{TEST_MARK}/b.fits")
    ).scalar_one()


def test_a_rig_whose_frames_are_csv_covered_still_makes_the_night_multi_rig(db):
    """The veto counts the night's rigs, not the rigs still needing a fill.

    One rig runs N.I.N.A. with the Session Metadata CSV, so every one of its
    subs already holds a "csv" value and none of them appear in the fill
    query. If that made the night look single-rig, the sole unmapped profile
    - which in fact belongs to the CSV-covered rig - would be attributed by
    the fallback, and the guided rig's RMS would be written onto the other
    rig's frames with a plausible arcsec figure, an empty
    unattributed_profiles, and no counter moved. Silent and wrong is worse
    than empty.
    """
    from app.services.phd2_correlation import correlate_dates

    _seed_night(db, mapped=False, second_rig=True,
                image_rms=0.42, image_source="csv")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.filled == 0
    assert result.unattributed_profiles == ["140APO_AM5N_ASI174MM"]
    with db() as s:
        other = _second_rig_image(s)
        assert other.guiding_rms_arcsec is None
        assert other.guiding_rms_source is None


def test_a_mapped_profile_on_a_csv_covered_night_fills_only_its_own_rig(db):
    """The widened rig set must not cost the mapped path anything.

    Same two-rig, one-rig-CSV-covered shape as above, but the profile is
    mapped. The veto does not apply to a mapped session, so its own rig fills
    normally, the CSV-covered rig keeps its own instrument record, and no
    profile is reported.
    """
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, second_rig=True,
                           second_rig_rms=0.42, second_rig_source="csv")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    assert result.filled == 1
    assert result.unattributed_profiles == []
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"
        other = _second_rig_image(s)
        assert other.guiding_rms_arcsec == pytest.approx(0.42)
        assert other.guiding_rms_source == "csv"


def test_one_rig_under_two_names_still_gets_its_sole_profile_fallback(db):
    """End to end for the veto's cardinality: alias spellings are one rig.

    Both of the night's frames were shot on the same scope, stored under the
    canonical name and under an alias of it, with a single unmapped guiding
    profile. That is a single-rig night, so the fallback should attribute and
    both frames should fill. Counting the stored strings instead would judge
    it multi-rig, veto, and report a conflict that does not exist.
    """
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(
        db, telescope="SVBony 80ED", mapped=False,
        profile="SOLO_PROFILE", second_rig=True,
        second_rig_telescope="SVBony SV503 80mm",
    )
    alias_map = {"SVBony SV503 80mm": "SVBony 80ED"}
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)], alias_map=alias_map)
        s.commit()
    assert result.filled == 2
    assert result.unattributed_profiles == []
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"
        other = _second_rig_image(s)
        assert other.guiding_rms_source == "phd2"
        assert other.guiding_rms_arcsec == pytest.approx(0.5, abs=1e-3)


def test_two_genuinely_different_rigs_still_veto_end_to_end(db):
    """The companion to the test above: the veto still fires when it should.

    Same seed shape and the same alias map, but the second frame's rig is not
    an alias of the first. Two rigs, one unmapped profile, so nothing fills
    and the profile is named.
    """
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(
        db, telescope="SVBony 80ED", mapped=False,
        profile="SOLO_PROFILE", second_rig=True,
        second_rig_telescope="140APO",
    )
    alias_map = {"SVBony SV503 80mm": "SVBony 80ED"}
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)], alias_map=alias_map)
        s.commit()
    assert result.filled == 0
    assert result.unattributed_profiles == ["SOLO_PROFILE"]
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_arcsec is None
        assert _second_rig_image(s).guiding_rms_arcsec is None


def test_incremental_mode_only_visits_nights_that_can_change(db):
    """A library with ten years of images and one month of guide logs must not
    pay for the other nine years and eleven months on every scan."""
    from app.services.phd2_correlation import correlate_dates

    _seed_night(db)
    with db() as s:
        result = correlate_dates(s, None)
        s.commit()
    assert result.dates == 1


def test_affected_dates_covers_both_sides_of_a_remap(db):
    from app.services.phd2_correlation import affected_dates, correlate_dates

    _seed_night(db)
    with db() as s:
        correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    with db() as s:
        assert date(2026, 7, 14) in affected_dates(s)


# --- the two date spaces ----------------------------------------------------

def _seed_day_skewed_orphan(db):
    """A guide session dated D over an image dated D-1, from a log that is
    already gone from disk.

    This is the out-of-the-box arrangement, not a contrived one: with
    observer_longitude unset (the default) guide sessions group by UTC
    midnight while images keep solar-noon grouping, so an evening session west
    of Greenwich lands one day after the frames it covers. The image already
    carries a phd2-sourced value because the fill path widens and found it.
    """
    from app.models import Image
    from app.models.phd2 import Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    image_id = uuid.uuid4()
    start = datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc)

    with db() as s:
        s.add(Phd2Log(
            id=log_id,
            file_path=f"/{TEST_MARK}/deleted-from-disk.txt",
            parse_status="ok",
        ))
        s.flush()
        s.add(Phd2Session(
            id=uuid.uuid4(), log_id=log_id, run_index=0, section_index=0,
            started_at_local=datetime(2026, 7, 14, 22, 0, 0),
            started_at_utc=start,
            ended_at_utc=start + timedelta(seconds=120),
            duration_s=120.0,
            session_date=date(2026, 7, 14),
            equipment_profile="140APO_AM5N_ASI174MM",
            telescope="140APO",
            pixel_scale_arcsec=1.0,
            frame_count=120,
            events=[],
        ))
        s.add(Image(
            id=image_id,
            file_path=f"/{TEST_MARK}/skewed.fits", file_name="skewed.fits",
            capture_date=start, session_date=date(2026, 7, 13),
            image_type="LIGHT", exposure_time=60.0, telescope="140APO",
            guiding_rms_arcsec=0.5, guiding_rms_ra_arcsec=0.4,
            guiding_rms_dec_arcsec=0.3, guiding_rms_source="phd2",
        ))
        s.commit()
    return image_id


def test_deleting_a_log_clears_the_night_its_frames_actually_sit_on(db):
    """Orphan cleanup re-derives the nights a deleted log covered, but it can
    only name them in guide-log date space. Unless the dispatch widens, the
    frames the log actually fed keep a phd2-sourced value derived from
    sessions that have been cascade-deleted, with no later seam that can ever
    clear it."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates
    from app.worker import tasks_phd2

    image_id = _seed_day_skewed_orphan(db)

    captured = {}

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            captured.update(kwargs["kwargs"])

    original = tasks_phd2.correlate_phd2_images
    tasks_phd2.correlate_phd2_images = _Task
    try:
        with db() as s:
            tasks_phd2._cleanup_orphans(s, force=True)
    finally:
        tasks_phd2.correlate_phd2_images = original

    # The worker parses the ISO strings back before handing them on, so the
    # re-derive sees exactly this set.
    dates = [date.fromisoformat(d) for d in captured["dates"]]
    assert date(2026, 7, 13) in dates
    assert date(2026, 7, 14) in dates

    with db() as s:
        correlate_dates(s, dates)
        s.commit()
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_source is None
        assert image.guiding_rms_arcsec is None
        assert image.guiding_rms_ra_arcsec is None
        assert image.guiding_rms_dec_arcsec is None


# --- the unvalidated-clock guard --------------------------------------------
#
# PHD2 writes bare local wall clock with no zone, and ingest converts it to UTC
# with observer_timezone. When that setting is empty the conversion falls back
# to the server's zone, which in the container is UTC, so on a America/Chicago
# corpus every guiding session is stored six hours early. Most exposures then
# overlap nothing and correctly stay NULL; the minority that still overlap are
# filled with an RMS measured six hours later in the night, stamped "phd2" like
# any other value, with nothing in the data marking them suspect. A NULL means
# "not known", which is true. A filled value from a shifted window is a false
# statement about the user's data, so the guard declines to write one.

def test_an_unset_observer_timezone_fills_nothing(db):
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.timezone_unset is True
    assert result.filled == 0
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec is None
        assert image.guiding_rms_ra_arcsec is None
        assert image.guiding_rms_dec_arcsec is None
        assert image.guiding_rms_source is None


def test_an_unset_observer_timezone_fills_nothing_in_incremental_mode(db):
    """The scan seams and the v16 migration both use incremental mode, so the
    guard has to hold on a pass that was given no dates at all."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "")
    with db() as s:
        result = correlate_dates(s, None)
        s.commit()

    assert result.timezone_unset is True
    assert result.filled == 0
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_arcsec is None


def test_the_unset_timezone_is_reported_once_per_pass(db):
    """Silence would trade one invisible failure for another. One row per
    pass, not one per night: this pass is handed three nights."""
    from app.services.phd2_correlation import correlate_dates

    _seed_night(db)
    _write_observer_timezone(db, "")
    with db() as s:
        correlate_dates(
            s, [date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15)]
        )
        s.commit()

    rows = _guard_warnings(db)
    assert len(rows) == 1
    severity, category, message = rows[0]
    assert severity == "warning"
    assert category == "scan"
    # Names the profile whose guiding was left out, and both places a timezone
    # can be set for it.
    assert "140APO_AM5N_ASI174MM" in message
    assert "Settings > Equipment > PHD2 Profiles" in message
    assert "Observer Location" in message


def test_a_configured_timezone_fills_normally(db):
    """The guard must not be a way of disabling the feature. Same fixture as
    the tests above, one setting different."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "America/Chicago")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.timezone_unset is False
    assert result.filled == 1
    assert _guard_warnings(db) == []
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"


def test_a_zone_equal_to_the_servers_own_zone_still_fills(db):
    """"Unset" is a distinct case from "explicitly configured", even when the
    two resolve to the same offset. The test containers and the app container
    both run UTC, which is exactly what the empty value falls back to, so a
    guard keyed on the resolved zone rather than on the setting would refuse
    this pass and silently disable the feature for every UTC observer."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "UTC")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.timezone_unset is False
    assert result.filled == 1
    assert _guard_warnings(db) == []
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"


def test_the_guard_declines_to_write_and_never_clears(db):
    """Decline, not clear. Whether a stored value is wrong depends on the zone
    that was configured when it was derived, and nothing records that; an empty
    setting now says nothing about the value written last week under a correct
    one. Clearing would therefore destroy correct data on a settings screen
    where the field is momentarily blank, and the repair path already exists:
    saving a zone forces a re-parse, which re-derives these nights and rewrites
    every phd2-sourced value on them. The companion test
    test_re_deriving_a_night_clears_its_stale_phd2_values_first pins the
    opposite outcome for the same fixture with the zone set."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(
        db, image_rms=0.11, image_source="phd2", exposure=1.0
    )
    _write_observer_timezone(db, "")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.cleared == 0
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec == pytest.approx(0.11)
        assert image.guiding_rms_source == "phd2"


def test_a_csv_value_survives_the_guard_on_both_paths(db):
    """Spec decision 5 does not weaken when the guard trips: the CSV is the
    frame's own instrument record, and neither the re-derive path nor the
    incremental path may touch it."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db, image_rms=0.99, image_source="csv")
    _write_observer_timezone(db, "")
    with db() as s:
        correlate_dates(s, [date(2026, 7, 14)])
        s.commit()
    with db() as s:
        correlate_dates(s, None)
        s.commit()

    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec == pytest.approx(0.99)
        assert image.guiding_rms_source == "csv"


def test_a_day_skewed_night_with_no_configured_zone_is_not_cleared(db):
    """The night the images sit on is excluded, not just the session's own.

    With the observer longitude unset, a guiding session's session_date lands a
    day after the frames it covers, which is the out-of-the-box arrangement
    rather than a contrived one. The guard has to recognise the image night as
    unconfigured from a session filed on the next day, or the clear runs on the
    night that actually holds the data and the refill, which correctly declines
    to use an unzoned session, leaves it empty.
    """
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_day_skewed_orphan(db)
    _write_observer_timezone(db, "")
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 13), date(2026, 7, 14)])
        s.commit()

    assert result.cleared == 0
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec == pytest.approx(0.5)
        assert image.guiding_rms_source == "phd2"


def test_a_pass_with_nothing_to_correlate_says_nothing(db):
    """Incremental correlation is dispatched from the image-scan seams, so it
    runs after every scan. An install with no guide logs can never fill
    anything, and warning there would put a row in the activity feed on every
    scan interval, which is how a feed stops being read."""
    from app.services.phd2_correlation import correlate_dates

    _write_observer_timezone(db, "")
    with db() as s:
        result = correlate_dates(s, None)
        s.commit()

    assert result.dates == 0
    assert result.timezone_unset is False
    assert _guard_warnings(db) == []


# --- per-profile timezones --------------------------------------------------
#
# One global zone cannot describe a remote rig, so each equipment profile
# carries its own and falls back to the global one. The guard follows: it stops
# being a pass-wide refusal and becomes a per-profile exclusion, so a
# configured rig keeps filling on a night that also holds an unconfigured one.
# What must not change is the reason the refusal exists at all - a blank
# setting may never DESTROY a value that was correct when it was written - so a
# night on which every overlapping profile resolves to no zone is kept out of
# the clear as well as out of the fill.

def _seed_two_profile_night(db, *, profile_a="PROFILE_A", rig_a="140APO",
                            profile_b="PROFILE_B", rig_b="SVBony 80ED",
                            frame_count=120, exposure=60.0):
    """Two rigs on one night, each with its own mapped guiding session."""
    from app.models import Image
    from app.models.phd2 import Phd2Frame, Phd2Log, Phd2Session

    log_id = uuid.uuid4()
    start = datetime(2026, 7, 15, 2, 0, 0, tzinfo=timezone.utc)
    ids = []

    with db() as s:
        s.add(Phd2Log(
            id=log_id, file_path=f"/{TEST_MARK}/two.txt", parse_status="ok"
        ))
        s.flush()
        for index, (profile, rig) in enumerate(
            ((profile_a, rig_a), (profile_b, rig_b))
        ):
            session_id = uuid.uuid4()
            s.add(Phd2Session(
                id=session_id, log_id=log_id, run_index=0, section_index=index,
                started_at_local=datetime(2026, 7, 14, 22, 0, 0),
                started_at_utc=start,
                ended_at_utc=start + timedelta(seconds=frame_count),
                duration_s=float(frame_count),
                session_date=date(2026, 7, 14),
                equipment_profile=profile,
                telescope=rig,
                pixel_scale_arcsec=1.0,
                frame_count=frame_count,
                events=[],
            ))
            s.flush()
            s.add_all([
                Phd2Frame(
                    session_id=session_id, frame_index=i, time_offset=float(i),
                    ra_raw=0.4 if i % 2 == 0 else -0.4,
                    dec_raw=0.3 if i % 2 == 0 else -0.3,
                    dropped=False,
                )
                for i in range(frame_count)
            ])
            image_id = uuid.uuid4()
            ids.append(image_id)
            s.add(Image(
                id=image_id,
                file_path=f"/{TEST_MARK}/two-{index}.fits",
                file_name=f"two-{index}.fits",
                capture_date=start, session_date=date(2026, 7, 14),
                image_type="LIGHT", exposure_time=exposure, telescope=rig,
            ))
        s.commit()
    return ids


def test_a_configured_profile_fills_while_an_unconfigured_one_is_named(db):
    """The whole point of the per-profile guard: a rig whose zone the user has
    given is no longer starved by a rig whose zone they have not."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_a, image_b = _seed_two_profile_night(db)
    _write_observer_timezone(db, "")
    _write_profile_map(db, {
        "PROFILE_A": {"telescope": "140APO", "timezone": "America/Chicago"},
    })
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.filled == 1
    assert result.timezone_unset_profiles == ["PROFILE_B"]
    assert result.timezone_unset is True
    with db() as s:
        assert s.get(Image, image_a).guiding_rms_source == "phd2"
        other = s.get(Image, image_b)
        assert other.guiding_rms_arcsec is None
        assert other.guiding_rms_source is None


def test_the_warning_names_only_the_profiles_that_have_no_zone(db):
    from app.services.phd2_correlation import correlate_dates

    _seed_two_profile_night(db)
    _write_observer_timezone(db, "")
    _write_profile_map(db, {
        "PROFILE_A": {"telescope": "140APO", "timezone": "America/Chicago"},
    })
    with db() as s:
        correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    rows = _guard_warnings(db)
    assert len(rows) == 1
    severity, category, message = rows[0]
    assert severity == "warning"
    assert category == "scan"
    assert "PROFILE_B" in message
    assert "PROFILE_A" not in message


def test_a_night_whose_every_profile_lacks_a_zone_keeps_its_stored_values(db):
    """The property the guard exists for, now decided per night.

    A profile map that names other rigs does not make this night's rig
    configured, and clearing here would destroy a value that was correct when
    it was written under a zone nothing records.
    """
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(
        db, image_rms=0.11, image_source="phd2", exposure=1.0
    )
    _write_observer_timezone(db, "")
    _write_profile_map(db, {
        "SOME_OTHER_RIG": {"telescope": "X", "timezone": "America/Chicago"},
    })
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.cleared == 0
    assert result.timezone_unset_profiles == ["140APO_AM5N_ASI174MM"]
    with db() as s:
        image = s.get(Image, image_id)
        assert image.guiding_rms_arcsec == pytest.approx(0.11)
        assert image.guiding_rms_source == "phd2"


def test_one_unconfigured_night_does_not_stop_a_configured_one(db):
    """Per night, not per pass. The configured night re-derives normally while
    the unconfigured one is held back from both the clear and the fill."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    configured = _seed_night(
        db, night=date(2026, 7, 12), tag="cfg", profile="CONFIGURED",
        image_rms=0.11, image_source="phd2", exposure=1.0,
    )
    unconfigured = _seed_night(
        db, night=date(2026, 7, 14), tag="unc", profile="UNCONFIGURED",
        image_rms=0.22, image_source="phd2", exposure=1.0,
    )
    _write_observer_timezone(db, "")
    _write_profile_map(db, {
        "CONFIGURED": {"telescope": "140APO", "timezone": "America/Chicago"},
    })
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 12), date(2026, 7, 14)])
        s.commit()

    assert result.cleared == 1
    assert result.timezone_unset_profiles == ["UNCONFIGURED"]
    with db() as s:
        # One second of exposure holds too few samples to re-qualify, so the
        # cleared value stays gone; the held-back night keeps its own.
        assert s.get(Image, configured).guiding_rms_arcsec is None
        assert s.get(Image, unconfigured).guiding_rms_arcsec == pytest.approx(0.22)


def test_a_profile_zone_alone_is_enough_to_fill_with_no_global_zone(db):
    """A user with one rig in another timezone configures that rig and nothing
    else. The pass must not still be waiting on the global setting."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "")
    _write_profile_map(db, {
        "140APO_AM5N_ASI174MM": {
            "telescope": "140APO", "timezone": "America/Chicago",
        },
    })
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.filled == 1
    assert result.timezone_unset is False
    assert result.timezone_unset_profiles == []
    assert _guard_warnings(db) == []
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"


def test_a_blank_profile_zone_inherits_the_global_one(db):
    """Per-profile empty means inherit, not unset. Only both being empty is
    unset, which is what keeps the existing single-timezone installs working."""
    from app.models import Image
    from app.services.phd2_correlation import correlate_dates

    image_id = _seed_night(db)
    _write_observer_timezone(db, "America/Chicago")
    _write_profile_map(db, {
        "140APO_AM5N_ASI174MM": {"telescope": "140APO", "timezone": ""},
    })
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.filled == 1
    assert result.timezone_unset is False
    with db() as s:
        assert s.get(Image, image_id).guiding_rms_source == "phd2"


def test_a_legacy_string_entry_carries_no_zone_of_its_own(db):
    """Every install stored the map as {profile: telescope} before per-rig
    zones existed. Such an entry is mapped but unzoned, so with no global zone
    it is named rather than trusted."""
    from app.services.phd2_correlation import correlate_dates

    _seed_night(db)
    _write_observer_timezone(db, "")
    _write_profile_map(db, {"140APO_AM5N_ASI174MM": "140APO"})
    with db() as s:
        result = correlate_dates(s, [date(2026, 7, 14)])
        s.commit()

    assert result.filled == 0
    assert result.timezone_unset_profiles == ["140APO_AM5N_ASI174MM"]


# --- what the resolver reads ------------------------------------------------

def test_the_resolver_prefers_a_profile_zone_and_falls_back_to_the_global(db):
    from app.services.phd2_correlation import load_zone_resolver

    _write_observer_timezone(db, "UTC")
    _write_profile_map(db, {
        "PROFILE_A": {"telescope": "140APO", "timezone": "America/Chicago"},
        "PROFILE_B": {"telescope": "SVBony 80ED", "timezone": ""},
    })
    with db() as s:
        resolve = load_zone_resolver(s)

    assert resolve("PROFILE_A") == ("America/Chicago", "profile")
    assert resolve("PROFILE_B") == ("UTC", "global")
    assert resolve("NEVER_SEEN") == ("UTC", "global")
    # A section whose header names no profile resolves through the global
    # value alone.
    assert resolve(None) == ("UTC", "global")


def test_the_resolver_reads_the_raw_json_and_never_raises_on_it(db):
    """Deliberately not through GeneralSettings: that schema rejects a zone
    name tzdata cannot load, so a value stored before the validator existed
    would raise here instead of answering the question asked. An unloadable
    zone is not a configured zone, and it has its own warning elsewhere."""
    from app.services.phd2_correlation import load_zone_resolver

    _write_observer_timezone(db, "Mars/Olympus_Mons")
    _write_profile_map(db, {"PROFILE_A": {"timezone": "Not/AZone"}, "X": 7})
    with db() as s:
        resolve = load_zone_resolver(s)

    assert resolve("PROFILE_A") == ("", "unset")
    assert resolve("X") == ("", "unset")
    assert resolve(None) == ("", "unset")
