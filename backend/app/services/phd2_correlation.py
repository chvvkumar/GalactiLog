"""Per-image guiding RMS, computed from the stored PHD2 frame stream.

Phase 1 answered "how did guiding go last night". This module answers "was
THIS sub guided well", which is the figure the Analysis correlations and the
WBPP quality filter consume and the one a user compares against PHD2's own
display. The measurement is deliberately identical to the session-level one
(population standard deviation of the raw RA/Dec distances converted to
arcsec, DROP frames and dither/settle windows excluded), because the two
appear side by side in the UI and a methodological difference between them
would read as a bug in whichever number the user trusts less.

Sync only: every caller is a Celery task or a data migration, both of which
hold a sync Session from app.worker.tasks_common._sync_engine.

correlate_dates is also the single gate on the whole feature. Every path that
can write a phd2-sourced value - the three dispatch sites in tasks_phd2
(orphan cleanup, end of pass, post-scan cascade) and step (c) of the v16 data
migration - reaches the columns through it and through nothing else, so the
timezone guard below is stated once rather than repeated at four call sites
that a fifth caller would then have to remember.

Cost shape. One pass touches a bounded set of imaging nights, and per night
issues exactly four queries: the night's unfilled images, the night's full
set of rig names (which the multi-rig veto is decided over and which the
unfilled set cannot answer), the guiding sessions whose time range overlaps
the images (served by the started_at_utc index that revision 0022 created
for this), and those sessions' frames. The three after the first are skipped
when the night has nothing to fill. The per-image work is then a bisect over
an in-memory sorted array. It is
deliberately NOT the full-table ORM walk that apply_profile_map does: that
pattern is affordable over 800 session rows and is not affordable over
390k frame rows times every night in a catalog.
"""
from __future__ import annotations

import bisect
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import Image
from app.models.phd2 import Phd2Frame, Phd2Session
from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
from app.services.activity import emit_sync as _emit_activity_sync
from app.services.normalization import (
    build_equipment_alias_maps, equipment_match_set, normalize_equipment,
)
from app.services.phd2_metrics import (
    _in_windows, _rms, dither_settle_windows_from_stored,
    select_phd2_night_rows,
)
from app.services.phd2_profiles import profile_zone_resolver

logger = logging.getLogger(__name__)

# The two values images.guiding_rms_source can hold (see models/image.py).
GUIDING_RMS_SOURCE_CSV = "csv"
GUIDING_RMS_SOURCE_PHD2 = "phd2"

# Coverage gate. phd2_metrics.MIN_FRAMES = 100 is a session-level gate and
# does NOT apply here: an exposure window is seconds to minutes long, so a
# hundred samples would exclude every sub shorter than about a minute at a
# 0.5 s guide exposure. What matters per image is that the samples are
# numerous enough to have a standard deviation at all, and that they cover
# enough of the exposure to describe it - twenty samples from the first ten
# seconds of a five-minute sub say nothing about the other 290.
MIN_CORRELATION_FRAMES = 10
MIN_CORRELATION_COVERAGE = 0.5

# How far before a night's first exposure to look for a guiding session that
# could still be running when it starts. PHD2 sessions run for hours, and a
# session's own session_date can land a day off the images it covers when the
# observer longitude or timezone is misconfigured (the hazard tasks_phd2's
# _session_date_sanity_check warns about), so the session lookup is a time
# overlap rather than a date equality.
SESSION_LOOKBACK = timedelta(hours=24)

# The guard on the observer clock. PHD2 writes bare local wall-clock times with
# no zone, and ingest converts them to UTC with the zone configured for the
# equipment profile, falling back to observer_timezone; when neither is set the
# conversion falls back to the server's zone, which in the container is UTC. On
# a America/Chicago corpus that stores every guiding session six hours early.
# Most exposures then overlap no guide frames and correctly stay NULL, which is
# harmless. The damage is the minority that still overlap: on the production
# clone 172 images were filled with an RMS measured six hours later in the
# night, stamped "phd2" like any other value, with nothing in the data marking
# them suspect (smoke report s2-data, finding F1). A NULL means "not known",
# which is true; a filled value from a shifted window is a false statement about
# the user's data.
#
# The event type is unchanged from the single-timezone version of this guard:
# activity-feed filters and the guides resolve against the string.
TIMEZONE_UNSET_EVENT = "phd2_correlation_timezone_unset"

# What a guiding section whose header names no equipment profile is called in
# the warning. Such a section resolves through the global setting alone, and
# there is no profile name to print, but leaving it out would produce a warning
# that names nobody.
UNNAMED_PROFILE = "(no equipment profile)"


def timezone_unset_message(profiles: list[str]) -> str:
    """Why these profiles were left out, and the two places that fixes it."""
    names = ", ".join(profiles)
    return (
        f"Guiding from PHD2 profile(s) {names} was not matched to any frame "
        "because no timezone is configured for them. PHD2 writes local "
        "wall-clock times with no timezone, so reading them in the wrong zone "
        "shifts every guiding session by the difference and would attach "
        "guiding measured hours away to whichever exposures happened to "
        "overlap. Open Settings > Library > PHD2 and set the timezone of the "
        "PC that runs PHD2 for each profile, or set Settings > Library > "
        "Observer Location > Timezone to cover every profile that has none of "
        "its own. Other profiles were matched normally. Values already stored "
        "were left as they are."
    )


@dataclass
class CorrelationResult:
    """What one correlation pass did, for the activity event and the logs."""

    dates: int = 0
    images_considered: int = 0
    filled: int = 0
    cleared: int = 0
    below_gate: int = 0
    unattributed_profiles: list[str] = field(default_factory=list)
    timezone_unset_profiles: list[str] = field(default_factory=list)

    @property
    def timezone_unset(self) -> bool:
        """Whether the guard held anything back, for the callers that ask.

        The guard used to be pass-wide and this used to be a stored bool. It
        stays readable as one so the activity emitter and the existing
        assertions keep working; the list is what says WHICH rigs were left
        out, which is the question a user with more than one rig has.
        """
        return bool(self.timezone_unset_profiles)

    def summary(self) -> str:
        return (
            f"{self.filled} frame(s) filled, {self.below_gate} below the "
            f"coverage gate, {self.cleared} stale value(s) cleared, over "
            f"{self.dates} night(s)"
        )


def load_telescope_alias_map_sync(db: Session) -> dict[str, str]:
    """Telescope alias -> canonical map, read through a sync Session.

    normalization.load_alias_maps is async and TTL-cached for the request
    path; a Celery worker has neither an AsyncSession nor any use for a
    30-second cache inside a single pass. Only the read is reimplemented -
    the map itself is still built by normalization.build_equipment_alias_maps,
    so there stays exactly one definition of what an alias is.
    """
    row = db.get(UserSettings, SETTINGS_ROW_ID)
    _, tel_map = build_equipment_alias_maps(
        row.equipment if row is not None and row.equipment else {}
    )
    return tel_map


def load_zone_resolver(db: Session) -> Callable[[str | None], tuple[str, str]]:
    """The per-profile zone lookup this pass decides the guard with.

    Returns phd2_profiles.profile_zone_resolver bound to the stored map and the
    stored global value, so one profile name resolves to (zone, source) with
    source one of "profile", "global" or "unset". Empty means "interpret
    guide-log timestamps in the server's local zone", which phase 1 recorded as
    a distinct case from a configured zone. A zone the user chose that happens
    to equal the server's is NOT unset: the first is a default nobody picked
    and cannot be trusted to describe the PHD2 machine, the second is a
    statement about where that machine is. Only the first trips the guard.

    Read from the raw settings JSON rather than through GeneralSettings: that
    schema's validator rejects an unloadable zone name, so a value stored
    before the validator existed would raise here instead of answering the
    question asked. The raw map also still carries the legacy
    `{"Rig A": "Askar 120"}` form on every install that predates per-rig zones,
    and normalize_profile_map inside the resolver is what tolerates it, so this
    function needs no shape handling of its own.

    Costs no query of its own on the paths that follow: correlate_dates then
    calls load_telescope_alias_map_sync, which reads the same row out of the
    Session's identity map.
    """
    row = db.get(UserSettings, SETTINGS_ROW_ID)
    general = (row.general if row is not None else None) or {}
    return profile_zone_resolver(
        general.get("phd2_profile_map"), general.get("observer_timezone")
    )


def _emit_timezone_unset_warning(db: Session, profiles: list[str]) -> None:
    """Say what was left out, once per pass, naming the profiles and the fix.

    Declining silently would trade one invisible failure for another, so this
    is not optional to the guard.

    Written on its own Session rather than the caller's. emit_sync commits, and
    the v16 data migration calls correlate_dates in the middle of its own
    transaction, so handing it the caller's Session would commit half a
    migration as a side effect of a warning. The bind is the caller's, so the
    row lands in the same database without a second engine being built.

    The Redis handle is the worker's single client, imported inside the
    function rather than at module scope: this is a service module, imported by
    the data migration and by tests that have no worker, and a module-level
    import of app.worker.tasks_common would build the worker's engine on every
    one of those imports. emit_sync swallows a publish failure, so a missing
    broker costs the activity row nothing.
    """
    try:
        from app.worker.tasks_common import _redis as redis_client
    except Exception:  # noqa: BLE001 - a warning must never break the pass
        logger.debug("phd2 correlation: no worker Redis client", exc_info=True)
        redis_client = None
    try:
        with Session(db.get_bind()) as adb:
            _emit_activity_sync(
                adb, redis=redis_client, category="scan", severity="warning",
                event_type=TIMEZONE_UNSET_EVENT,
                message=timezone_unset_message(profiles),
                details={
                    # Capped: a corpus can hold more profile names than an
                    # activity row should carry, and the message already names
                    # them for the reader.
                    "profiles": profiles[:50],
                    "setting": "phd2_profile_map",
                },
                actor="system",
            )
    except Exception:  # noqa: BLE001 - same reason
        logger.warning(
            "phd2 correlation: could not record the missing-timezone warning",
            exc_info=True,
        )


def attribute_sessions_to_rigs(
    sessions, image_rigs, alias_map: dict[str, str]
) -> tuple[dict[str, list], list[str]]:
    """Decide which guiding sessions describe which imaging rig, for one night.

    Returns (rig name -> [session rows], sorted names of profiles that were
    attributed nowhere).

    The per-rig decision is select_phd2_night_rows, the same selector the
    night summary and the /phd2/sessions route use, so a frame's guiding RMS
    can never come from a session the session card refuses to show. Both
    sides of the name comparison are user data written at different times -
    a profile mapped before the rig was grouped stores the raw name and the
    map is never rewritten - so the rig name is expanded to its canonical
    form plus every alias before comparing.

    One rule is added on top of the selector: its "the night's sole unmapped
    profile probably belongs to this rig" fallback is a helpful guess when
    there is one rig to guess about, and a wrong answer when there are two,
    because it would attach the guided rig's numbers to the other rig's
    frames as well. Spec decision 4: on a multi-rig night an unmapped profile
    attributes nothing and gets named instead.

    That "how many rigs" count is taken over CANONICAL names, while the keys
    of the returned map stay the raw stored spellings the caller matches its
    images by. A rig regularly appears under several spellings in one night's
    headers - the whole reason the alias map exists - and counting the raw
    strings would read one physical rig as two, veto its own sole unmapped
    profile, and leave the night empty with a warning naming a profile that
    was never ambiguous. Grouping only the cardinality decision keeps the
    veto measuring what it is meant to measure without disturbing which rig
    a given frame is filled from.
    """
    sessions = list(sessions)
    rigs = sorted({r for r in image_rigs if r})
    canonical_rigs = {normalize_equipment(r, alias_map) or r for r in rigs}
    multi_rig = len(canonical_rigs) > 1

    attributed: dict[str, list] = {}
    for rig in rigs:
        wanted = equipment_match_set([rig], alias_map)
        selected = select_phd2_night_rows(sessions, wanted)
        if selected and multi_rig and not any(s.telescope for s in selected):
            selected = []
        if selected:
            attributed[rig] = selected

    used = {s.id for rows in attributed.values() for s in rows}
    unattributed = sorted({
        s.equipment_profile
        for s in sessions
        if s.id not in used and not s.telescope and s.equipment_profile
    })
    return attributed, unattributed


def guide_samples(
    session_row, frames: list[tuple[float, float | None, float | None, bool]]
) -> list[tuple[float, float, float]]:
    """Absolute-time RA/Dec samples in arcsec for one guiding session.

    `frames` is the query's row shape, (time_offset, ra_raw, dec_raw,
    dropped), already ordered by time_offset. Returns
    [(epoch_seconds, ra_arcsec, dec_arcsec)] holding only the frames that
    count towards an RMS: DROP rows and rows inside a dither or settling
    window are excluded, exactly as compute_session_metrics excludes them.

    Empty when the session carries no pixel scale. Frames are stored in
    pixels precisely so a wrong scale in one section header cannot be baked
    into 390k rows; with no scale there is nothing to convert them with, and
    an arcsec figure would be invented rather than measured.
    """
    scale = session_row.pixel_scale_arcsec
    if not scale:
        return []
    last_t = frames[-1][0] if frames else None
    windows = dither_settle_windows_from_stored(session_row.events, last_t)
    base = session_row.started_at_utc
    if base.tzinfo is None:
        # DateTime(timezone=True) round-trips aware, but a hand-built row in
        # a test or a legacy driver can hand back a naive value; PHD2 times
        # are stored as UTC either way.
        base = base.replace(tzinfo=timezone.utc)
    base_epoch = base.timestamp()

    samples: list[tuple[float, float, float]] = []
    for time_offset, ra_raw, dec_raw, dropped in frames:
        if dropped or ra_raw is None or dec_raw is None:
            continue
        if _in_windows(time_offset, windows):
            continue
        samples.append(
            (base_epoch + time_offset, ra_raw * scale, dec_raw * scale)
        )
    return samples


def window_rms(
    samples: list[tuple[float, float, float]],
    start_epoch: float,
    end_epoch: float,
) -> tuple[float, float, float] | None:
    """Pooled (rms_ra, rms_dec, rms_total) in arcsec, or None below the gate.

    `samples` must be sorted by time. It is the concatenation of every
    session attributed to this rig, because PHD2 restarting mid-exposure
    produces two sessions covering one sub and both describe how that sub was
    guided. Sessions of a different rig are never pooled: their samples
    describe a different optical train.

    None means "leave the columns NULL". That is the honest answer for a
    short sub with sparse guiding, which is normal and warrants no warning.
    """
    if not samples:
        return None
    span = end_epoch - start_epoch
    if span <= 0:
        return None

    times = [s[0] for s in samples]
    lo = bisect.bisect_left(times, start_epoch)
    hi = bisect.bisect_right(times, end_epoch)
    window = samples[lo:hi]
    if len(window) < MIN_CORRELATION_FRAMES:
        return None
    if (window[-1][0] - window[0][0]) / span < MIN_CORRELATION_COVERAGE:
        return None

    rms_ra = _rms([s[1] for s in window])
    rms_dec = _rms([s[2] for s in window])
    if rms_ra is None or rms_dec is None:
        return None
    return (
        round(rms_ra, 6),
        round(rms_dec, 6),
        round(math.hypot(rms_ra, rms_dec), 6),
    )


def affected_dates(db: Session) -> list[date_type]:
    """Every night a full re-derive could change.

    The union of the nights holding a phd2-sourced frame (whose attribution
    may now be wrong) and the nights holding a guiding session (which may now
    attribute where they did not before). This is what a profile-map or
    equipment-alias edit invalidates, and it is bounded by the guide-log
    corpus rather than by the image catalog.
    """
    dates = {
        d for (d,) in db.execute(
            select(Image.session_date).where(
                Image.session_date.isnot(None),
                Image.guiding_rms_source == GUIDING_RMS_SOURCE_PHD2,
            ).distinct()
        ).all()
    }
    dates.update(
        d for (d,) in db.execute(
            select(Phd2Session.session_date)
            .where(Phd2Session.session_date.isnot(None))
            .distinct()
        ).all()
    )
    return sorted(dates)


def _dates_needing_fill(db: Session) -> list[date_type]:
    """Nights holding an unfilled image that a guiding session could cover.

    Two set-based DISTINCT scans over indexed date columns and an
    intersection, rather than a walk over every night in the catalog: a
    library with ten years of images and one month of guide logs must not pay
    for the other nine years and eleven months on every scan.

    The guide side is widened by a day either way. A guiding session's own
    session_date lands one day off the images it covers whenever the observer
    longitude is unset (the fingerprint tasks_phd2._session_date_sanity_check
    warns about), and the per-night session lookup below is a time overlap
    that would find it - but only if the night is visited at all.
    """
    image_dates = {
        d for (d,) in db.execute(
            select(Image.session_date).where(
                Image.session_date.isnot(None),
                Image.capture_date.isnot(None),
                Image.exposure_time.isnot(None),
                Image.exposure_time > 0,
                Image.image_type == "LIGHT",
                Image.guiding_rms_arcsec.is_(None),
            ).distinct()
        ).all()
    }
    if not image_dates:
        return []

    guide_dates: set[date_type] = set()
    for (d,) in db.execute(
        select(Phd2Session.session_date)
        .where(Phd2Session.session_date.isnot(None))
        .distinct()
    ).all():
        guide_dates.update({d - timedelta(days=1), d, d + timedelta(days=1)})

    return sorted(image_dates & guide_dates)


def _nights_with_no_configured_zone(
    db: Session,
    target_dates: list[date_type],
    resolve: Callable[[str | None], tuple[str, str]],
) -> dict[date_type, list[str]]:
    """The nights where EVERY overlapping profile resolves to no timezone.

    Returns {night: [profile names]}. Those nights are held out of the clear as
    well as out of the fill, which is the whole point: a blank setting must
    never DESTROY a value that was correct when it was written, and nothing
    records which zone a stored value was derived under. A night that mixes a
    configured profile with an unconfigured one is NOT here - it is processed
    normally with the unconfigured sessions dropped in _correlate_one_night.

    A night with no guiding session at all is NOT here either, and that is a
    deliberate non-vacuous reading of "every profile": treating the empty set
    as unconfigured would stop orphan cleanup from ever clearing the values a
    deleted log left behind, which is the one case where a stale value can
    never be re-derived by anything.

    The session side is widened by a day either way for the same reason
    _dates_needing_fill widens it: a guiding session's own session_date lands a
    day off the images it covers whenever the longitude behind it is unset,
    which is the out-of-the-box arrangement. The per-night fill finds such a
    session anyway, because it looks sessions up by time overlap rather than by
    date, so the guard has to see it too or it would clear the night that holds
    the images while refusing to refill it.
    """
    if not target_dates:
        return {}
    wanted = set(target_dates)
    lookup = sorted(
        {d + delta for d in wanted for delta in (-timedelta(days=1),
                                                 timedelta(days=0),
                                                 timedelta(days=1))}
    )
    by_night: dict[date_type, set[str | None]] = {}
    for session_date, profile in db.execute(
        select(Phd2Session.session_date, Phd2Session.equipment_profile)
        .where(Phd2Session.session_date.in_(lookup))
        .distinct()
    ).all():
        for delta in (-1, 0, 1):
            night = session_date + timedelta(days=delta)
            if night in wanted:
                by_night.setdefault(night, set()).add(profile)

    return {
        night: sorted({p or UNNAMED_PROFILE for p in found})
        for night, found in by_night.items()
        if all(resolve(p)[1] == "unset" for p in found)
    }


def _nights_the_pass_could_write(
    db: Session, nights: list[date_type], *, re_derive: bool
) -> set[date_type]:
    """Of these nights, the ones holding an image this pass could have written.

    Only used to decide whether a held-back night is worth warning about. A
    profile with no timezone that never meets an image the pass would have
    touched costs the user nothing, and naming it on every scan interval is how
    an activity feed stops being read.

    "Could have written" is wider on the re-derive path than on the incremental
    one: there the clear would have emptied the night's phd2-sourced values
    first, so keeping them is itself an effect worth explaining.
    """
    if not nights:
        return set()
    writable = Image.guiding_rms_arcsec.is_(None)
    if re_derive:
        writable = or_(
            writable, Image.guiding_rms_source == GUIDING_RMS_SOURCE_PHD2
        )
    return {
        d for (d,) in db.execute(
            select(Image.session_date).where(
                Image.session_date.in_(nights),
                Image.image_type == "LIGHT",
                Image.capture_date.isnot(None),
                Image.exposure_time.isnot(None),
                Image.exposure_time > 0,
                writable,
            ).distinct()
        ).all()
    }


def _correlate_one_night(
    db: Session,
    night: date_type,
    alias_map: dict[str, str],
    result: CorrelationResult,
    profiles: set[str],
    *,
    resolve: Callable[[str | None], tuple[str, str]],
    unzoned_profiles: set[str],
) -> None:
    """Fill every unfilled image on one imaging night. Caller commits."""
    images = db.execute(
        select(
            Image.id, Image.capture_date, Image.exposure_time, Image.telescope,
        ).where(
            Image.session_date == night,
            Image.image_type == "LIGHT",
            Image.capture_date.isnot(None),
            Image.exposure_time.isnot(None),
            Image.exposure_time > 0,
            Image.guiding_rms_arcsec.is_(None),
        )
    ).all()
    if not images:
        return
    result.images_considered += len(images)

    starts = []
    ends = []
    for _image_id, capture, exposure, _telescope in images:
        start = capture if capture.tzinfo else capture.replace(tzinfo=timezone.utc)
        starts.append(start)
        ends.append(start + timedelta(seconds=exposure))
    span_start = min(starts)
    span_end = max(ends)

    # Served by ix_phd2_sessions_started_at_utc, which revision 0022 created
    # for exactly this join. The lower bound is what keeps it an index range
    # scan rather than a full scan of the session table.
    sessions = db.execute(
        select(Phd2Session).where(
            Phd2Session.started_at_utc >= span_start - SESSION_LOOKBACK,
            Phd2Session.started_at_utc <= span_end,
            or_(
                Phd2Session.ended_at_utc.is_(None),
                Phd2Session.ended_at_utc >= span_start,
            ),
        )
    ).scalars().all()
    if not sessions:
        return

    # The multi-rig veto has to be decided over the night's FULL rig set, not
    # over the unfilled subset selected above. A rig whose subs all already
    # carry a CSV value is invisible to that query, and once it drops out of
    # the count a two-rig night reads as single-rig: the sole-unmapped-profile
    # fallback in select_phd2_night_rows stops being vetoed, and the
    # CSV-covered rig's guiding session gets stamped onto the OTHER rig's
    # frames. That failure is silent in every counter - the frame receives a
    # plausible arcsec figure and no profile is reported - which is exactly
    # the harm spec decision 4 exists to prevent. Which rigs a night spans is
    # a question about its images, not about which of them still need filling.
    night_rigs = {
        t for (t,) in db.execute(
            select(Image.telescope).where(
                Image.session_date == night,
                Image.image_type == "LIGHT",
                Image.telescope.isnot(None),
            ).distinct()
        ).all() if t
    }
    attributed, unattributed = attribute_sessions_to_rigs(
        sessions, night_rigs, alias_map
    )
    profiles.update(unattributed)
    if not attributed:
        return

    # Frames are loaded only for rigs that have something to fill. night_rigs
    # deliberately includes rigs whose images are all filled already, and
    # reducing their sample streams would be work with no possible output.
    #
    # The same pass drops every session whose profile resolves to no timezone.
    # Its wall-clock times were read in whatever zone the server happens to
    # run, so the window it describes may sit hours from the exposure it was
    # matched to, and a plausible arcsec figure derived from the wrong hour is
    # worse than the NULL that means "not known". Dropping here rather than
    # before the fill_rigs filter is what keeps the warning honest: a profile
    # is only named once it has actually met an image this pass would have
    # written. A rig left with no sessions fills nothing, which is already what
    # happens to a rig that was not guided.
    fill_rigs = {telescope for (_i, _c, _e, telescope) in images if telescope}
    relevant: dict[str, list] = {}
    for rig, rows in attributed.items():
        if rig not in fill_rigs:
            continue
        keep = []
        for row in rows:
            if resolve(row.equipment_profile)[1] == "unset":
                unzoned_profiles.add(row.equipment_profile or UNNAMED_PROFILE)
                continue
            keep.append(row)
        if keep:
            relevant[rig] = keep
    if not relevant:
        return

    needed = {s.id for rows in relevant.values() for s in rows}
    frames_by_session: dict = {session_id: [] for session_id in needed}
    for session_id, time_offset, ra_raw, dec_raw, dropped in db.execute(
        select(
            Phd2Frame.session_id, Phd2Frame.time_offset,
            Phd2Frame.ra_raw, Phd2Frame.dec_raw, Phd2Frame.dropped,
        )
        .where(Phd2Frame.session_id.in_(needed))
        .order_by(Phd2Frame.session_id, Phd2Frame.time_offset)
    ).all():
        frames_by_session[session_id].append(
            (time_offset, ra_raw, dec_raw, dropped)
        )

    samples_by_rig: dict[str, list[tuple[float, float, float]]] = {}
    for rig, rows in relevant.items():
        pooled: list[tuple[float, float, float]] = []
        for row in rows:
            pooled.extend(guide_samples(row, frames_by_session.get(row.id, [])))
        pooled.sort()
        samples_by_rig[rig] = pooled

    updates: list[dict] = []
    for image_id, capture, exposure, telescope in images:
        samples = samples_by_rig.get(telescope or "")
        if not samples:
            continue
        start = capture if capture.tzinfo else capture.replace(tzinfo=timezone.utc)
        start_epoch = start.timestamp()
        rms = window_rms(samples, start_epoch, start_epoch + exposure)
        if rms is None:
            result.below_gate += 1
            continue
        updates.append({
            "id": image_id,
            "guiding_rms_ra_arcsec": rms[0],
            "guiding_rms_dec_arcsec": rms[1],
            "guiding_rms_arcsec": rms[2],
            "guiding_rms_source": GUIDING_RMS_SOURCE_PHD2,
        })

    if updates:
        db.bulk_update_mappings(Image, updates)
        db.flush()
        result.filled += len(updates)


def correlate_dates(
    db: Session, dates=None, *, alias_map: dict[str, str] | None = None
) -> CorrelationResult:
    """Fill images.guiding_rms_* from PHD2 frames. Caller commits.

    `dates` is the set of imaging nights a guide-log pass just touched. Those
    nights are RE-DERIVED: every phd2-sourced value on them is cleared before
    the refill, because a re-ingested log (delete-then-reparse) or an edited
    profile map can invalidate a value that was correct when it was written,
    and a frame that no longer qualifies would otherwise keep yesterday's
    number forever. csv-sourced rows are never cleared and never overwritten.

    `dates=None` is the incremental mode used after an image scan: visit only
    the nights holding an image with no guiding RMS at all, fill what
    qualifies, re-derive nothing.

    Writes nothing for a guiding session whose equipment profile resolves to no
    timezone, neither its own nor the global fallback. See
    timezone_unset_message for why a value derived from an unvalidated clock is
    worse than no value. The exclusion is per profile rather than per pass, so
    a rig the user has configured keeps filling on a night that also holds one
    they have not.

    DECLINING rather than CLEARING is deliberate, and it is why a night on
    which EVERY overlapping profile is unzoned is held out of the clear as well
    as out of the fill. Whether a stored value is wrong depends on the zone
    configured when it was derived, and nothing records that, so an empty
    setting now says nothing about a value written last week under a correct
    one. Clearing would destroy correct data whenever the field is momentarily
    blank on the settings screen, and it is not needed to converge - saving a
    zone forces a re-parse, which re-derives these nights and rewrites every
    phd2-sourced value on them anyway.
    """
    result = CorrelationResult()

    if dates is None:
        target_dates = _dates_needing_fill(db)
    else:
        target_dates = sorted({d for d in dates if d is not None})

    resolve = load_zone_resolver(db)
    if alias_map is None:
        alias_map = load_telescope_alias_map_sync(db)

    held_back = _nights_with_no_configured_zone(db, target_dates, resolve)
    unzoned_profiles: set[str] = set()
    if held_back:
        # Named only for the nights where the exclusion actually cost the user
        # something. Incremental correlation is dispatched from the image-scan
        # seams, so it runs after every scan; a profile that is unconfigured
        # but never meets an image this pass would have touched must not put a
        # row in the activity feed on every scan interval.
        for night in _nights_the_pass_could_write(
            db, list(held_back), re_derive=dates is not None
        ):
            unzoned_profiles.update(held_back[night])
    fill_dates = [d for d in target_dates if d not in held_back]

    if dates is not None and fill_dates:
        cleared = db.execute(
            update(Image)
            .where(
                Image.session_date.in_(fill_dates),
                Image.guiding_rms_source == GUIDING_RMS_SOURCE_PHD2,
            )
            .values(
                guiding_rms_arcsec=None,
                guiding_rms_ra_arcsec=None,
                guiding_rms_dec_arcsec=None,
                guiding_rms_source=None,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        result.cleared = cleared or 0

    profiles: set[str] = set()
    for night in fill_dates:
        result.dates += 1
        _correlate_one_night(
            db, night, alias_map, result, profiles,
            resolve=resolve, unzoned_profiles=unzoned_profiles,
        )

    result.unattributed_profiles = sorted(profiles)
    result.timezone_unset_profiles = sorted(unzoned_profiles)
    if result.timezone_unset_profiles:
        # One row per pass, whatever the mix of nights and profiles was.
        # Declining silently would trade one invisible failure for another.
        message = timezone_unset_message(result.timezone_unset_profiles)
        logger.warning("phd2 correlation: %s", message)
        _emit_timezone_unset_warning(db, result.timezone_unset_profiles)
    logger.info("phd2 correlation: %s", result.summary())
    return result
