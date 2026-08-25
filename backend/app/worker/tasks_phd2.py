"""PHD2 guide-log ingest: scan_phd2_logs and the per-file work it drives.

Discovery happens inside the normal library walk (see scanner.scan_directory's
on_phd2_file callback); this module owns everything after a candidate path is
known. Each file is parsed whole and written in one transaction, so a log that
grew since the last scan is replaced rather than appended to - PHD2 rewrites
nothing, but a session that was still running last scan will now have more
frames, and delete-then-insert is the only way to get that right without
tracking per-section offsets.
"""
import logging
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models import Image
from app.models.phd2 import Phd2Calibration, Phd2Frame, Phd2Log, Phd2Session
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.schemas.settings import GeneralSettings
# Both of these are imported as modules rather than by name. phd2_parser has
# to be, because its dataclasses share names with the ORM models this module
# also imports. phd2_correlation is for the same reason its own callers use:
# the correlation entry points are resolved at call time, so a test or a data
# migration can substitute them on the defining module and have the
# substitution take effect here.
from app.services import (
    phd2_correlation, phd2_parser, phd2_profiles, phd2_sidereal,
)
from app.services.activity import emit_sync as _emit_activity_sync
from app.services.phd2_metrics import (
    build_calibration_row, build_frame_rows, compute_session_metrics,
)
from app.services.scan_state import (
    PHD2_STATE_IDLE, PHD2_STATE_RUNNING, increment_phd2_progress_sync,
    set_phd2_counts_sync, set_phd2_found_sync, set_phd2_state_sync,
)
from app.services.session_date import warn_imaging_night_fallback
from app.worker.celery_app import celery_app
from app.worker.tasks_common import (
    _activity_session, _invalidate_stats_cache, _redis, _sync_engine,
)
# The guide-log re-key is shared with recompute_session_dates rather than
# reimplemented here: both recompute session_date from a row's own
# started_at_utc and a per-profile longitude, and two implementations of that
# would eventually disagree about which night a rig's session belongs to.
from app.worker.tasks_sessions import _rekey_phd2_sessions

logger = logging.getLogger(__name__)

# Same tolerance the image scanner uses for mtime comparison: network
# filesystems and archive tools round mtimes, and a sub-second difference is
# never a real edit.
MTIME_TOLERANCE_S = 1.0

# Same value and same meaning as the image scanner's missing-mount guard in
# app/services/orphan_cleanup.py (`_threshold = max(1, known) * 0.5`): when at
# least half the catalogued files have vanished, the likely explanation is an
# unmounted or unreachable share, not half a library being deleted.
ORPHAN_MISSING_FRACTION_LIMIT = 0.5


class PointingSample(NamedTuple):
    """One guiding section's pointing, as the sidereal cross-check needs it.

    The first four fields are what the offset solve consumes: the equipment
    profile it belongs to, the UTC instant the configured zone assigned to the
    section's wall-clock start, and the RA and hour angle whose sum is local
    sidereal time. `dec_deg` and `alt_deg` ride along because the coherence
    gate that licenses that solve reads the same header line, and a sample that
    reached the pass without them could never be gated - the gate would have to
    re-open the file to find them.

    A section missing either RA or hour angle produces no sample at all: an
    ASIAIR-flavoured log writes no RA, so those files can be ingested and can
    never accuse a timezone.
    """

    profile: str | None
    started_at_utc: datetime
    ra_hr: float
    hour_angle_hr: float
    dec_deg: float | None
    alt_deg: float | None


def _profile_label(profile: str | None) -> str:
    """A profile name as a message may print it."""
    return profile or "(no equipment profile)"


def _read_settings() -> GeneralSettings:
    with Session(_sync_engine) as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        return GeneralSettings(**(row.general if row and row.general else {}))


def _safe_timezone(tz_name: str) -> str:
    """Return tz_name if it names a real zone, else "" (the server's zone).

    GeneralSettings.observer_timezone now rejects an unloadable zone at the
    schema, so this is the degrade path for a value stored before that
    validator existed, and the last line of defence if a zone the running
    tzdata knows disappears from a later one. Falling back to the server zone
    is the same answer the setting's own default gives, so a bad value
    degrades to the pre-configuration behaviour instead of raising on every
    file in the scan.
    """
    if not tz_name:
        return ""
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "phd2: observer_timezone %r is not a known IANA zone; "
            "interpreting guide-log timestamps in the server's local zone",
            tz_name,
        )
        return ""
    return tz_name


def apply_profile_map(db: Session, profile_map) -> int:
    """Re-resolve every stored session's telescope from the current map.

    The mapping is a user setting, not a property of the log, so editing it
    must not require re-reading files. Returns the number of rows whose
    telescope actually changed. Caller commits.

    The map arrives in whichever form the caller holds: the legacy
    `{"Rig A": "Askar 120"}`, the current per-profile entry carrying a
    telescope, a timezone and a site, or the pydantic models `GeneralSettings`
    builds from either. `phd2_profiles.telescope_map` is the one place that
    knows the difference, and it projects all of them down to the
    profile-to-telescope-name dict this function has always assigned from - so
    every existing caller and test that passes a plain string map keeps working
    unchanged, and none of them can write a settings object into a String
    column.
    """
    telescopes = phd2_profiles.telescope_map(profile_map)
    changed = 0
    rows = db.execute(select(Phd2Session)).scalars().all()
    for row in rows:
        wanted = telescopes.get(row.equipment_profile or "")
        if row.telescope != wanted:
            row.telescope = wanted
            changed += 1
    cal_rows = db.execute(select(Phd2Calibration)).scalars().all()
    for row in cal_rows:
        wanted = telescopes.get(row.equipment_profile or "")
        if row.telescope != wanted:
            row.telescope = wanted
            changed += 1
    return changed


def _stored_log_paths() -> list[str]:
    """Every guide-log path already in the catalog.

    This is the candidate list for a forced re-parse: a setting that changes
    how a log is read has to reach the files that were read under the old
    value, and no filesystem walk is running when that setting is saved.
    """
    with Session(_sync_engine) as db:
        return [p for (p,) in db.execute(select(Phd2Log.file_path)).all()]


def _record_parse_failure(
    db: Session, existing, path: str, stat, status: str, reason: str
) -> str:
    """Store one unusable guide log and say so, without stopping the pass."""
    if existing is not None:
        # Flushed before the replacement row is added: file_path is unique
        # and the unit of work orders same-table inserts ahead of deletes,
        # so without this the failure row collides with the row it
        # replaces.
        db.delete(existing)
        db.flush()
    db.add(Phd2Log(
        file_path=path, file_size=stat.st_size, file_mtime=stat.st_mtime,
        parse_status=status, parse_error=reason[:2000],
    ))
    db.commit()
    return "failed"


def ingest_phd2_log(
    db: Session,
    path: str,
    general: GeneralSettings,
    tz_name: str | None = None,
    force: bool = False,
    pointing: list | None = None,
) -> str:
    """Parse one guide log into the DB. Returns ok | empty | unchanged | failed.

    Everything for a single file happens in one transaction: the old rows are
    deleted and the new ones inserted together, so an interrupted re-parse can
    never leave a log half-replaced.

    `force` skips the size/mtime short-circuit. PHD2 never rewrites a closed
    log, so a file already stored is otherwise never read again and a change
    to the observer timezone could never reach it.

    `tz_name` is the already-resolved GLOBAL zone; the caller resolves it once
    per pass so a bad value is reported once rather than logged per file. It is
    the fallback behind each profile's own timezone, not the zone the file is
    read in: one guide log can hold sections from two rigs in two zones, so the
    zone and the longitude are both resolved per section from the equipment
    profile that section's header names.

    `pointing`, when given, collects a `PointingSample` per section whose
    header carries both RA and hour angle. It is evidence for the sidereal
    cross-check the caller runs at the end of the pass, and this function draws
    no conclusion from it.
    """
    file_path = Path(path)
    try:
        stat = file_path.stat()
    except OSError as exc:
        logger.warning("phd2: cannot stat %s: %s", path, exc)
        return "failed"

    existing = db.execute(
        select(Phd2Log).where(Phd2Log.file_path == path)
    ).scalar_one_or_none()
    if existing is not None:
        size_same = existing.file_size == stat.st_size
        mtime_same = (
            existing.file_mtime is not None
            and abs(existing.file_mtime - stat.st_mtime) <= MTIME_TOLERANCE_S
        )
        if size_same and mtime_same and not force:
            return "unchanged"

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("phd2: cannot read %s: %s", path, exc)
        return "failed"

    try:
        runs = phd2_parser.parse_guide_log(text)
    except phd2_parser.Phd2UnreadableLog as exc:
        # Caught ahead of the broad handler and given its own status. This is
        # the parser reporting a file it recognises as a guide log and cannot
        # read, which is a statement about the file rather than a crash: it
        # deserves no traceback, and "unreadable" tells it apart from a genuine
        # parser bug in the same column. parse_status is an unconstrained
        # String(20), so the new value needs no migration.
        logger.warning("phd2: unreadable guide log %s: %s", path, exc)
        return _record_parse_failure(
            db, existing, path, stat, "unreadable", str(exc)
        )
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
        logger.exception("phd2: parse failed for %s", path)
        return _record_parse_failure(
            db, existing, path, stat, "failed", str(exc)
        )

    if tz_name is None:
        tz_name = _safe_timezone(general.observer_timezone)
    use_night = general.use_imaging_night
    # Normalized once for the file, then handed to the resolvers rather than
    # re-normalized per section: a log with two hundred sections would
    # otherwise rebuild the same map two hundred times.
    profile_map = phd2_profiles.normalize_profile_map(general.phd2_profile_map)
    resolve_zone = phd2_profiles.profile_zone_resolver(profile_map, tz_name)
    resolve_longitude = phd2_profiles.longitude_resolver(
        profile_map, general.observer_longitude
    )
    telescopes = phd2_profiles.telescope_map(profile_map)

    if existing is not None:
        # Cascades remove this log's sessions, frames and calibrations.
        db.delete(existing)
        db.flush()

    session_total = sum(len(r.sections) for r in runs)
    cal_total = sum(len(r.calibrations) for r in runs)
    first_run = runs[0] if runs else None

    log_row = Phd2Log(
        file_path=path,
        file_size=stat.st_size,
        file_mtime=stat.st_mtime,
        parse_status="ok" if session_total or cal_total else "empty",
        phd2_version=first_run.phd2_version if first_run else None,
        log_version=first_run.log_version if first_run else None,
        run_count=len(runs),
        session_count=session_total,
        calibration_count=cal_total,
    )
    db.add(log_row)
    db.flush()

    for run_index, run in enumerate(runs):
        for warning in run.warnings:
            # WARNING, not INFO. These are the parser saying it threw data
            # away or could not read a section at all; at INFO they sat below
            # the default app-log capture level and nobody ever saw them.
            logger.warning("phd2: %s: %s", file_path.name, warning)
        for section_index, section in enumerate(run.sections):
            header = section.header
            profile = header.equipment_profile
            zone, _zone_source = resolve_zone(profile)
            metrics = compute_session_metrics(
                section,
                tz_name=zone,
                observer_longitude=resolve_longitude(profile),
                use_imaging_night=use_night,
            )
            session_row = Phd2Session(
                log_id=log_row.id,
                run_index=run_index,
                section_index=section_index,
                telescope=telescopes.get(metrics.equipment_profile or ""),
                **{
                    k: v for k, v in vars(metrics).items()
                },
            )
            db.add(session_row)
            db.flush()
            if (
                pointing is not None
                and header.ra_hr is not None
                and header.hour_angle_hr is not None
            ):
                pointing.append(PointingSample(
                    profile=profile,
                    started_at_utc=metrics.started_at_utc,
                    ra_hr=header.ra_hr,
                    hour_angle_hr=header.hour_angle_hr,
                    dec_deg=header.dec_deg,
                    alt_deg=header.alt_deg,
                ))
            frame_rows = build_frame_rows(section)
            if frame_rows:
                db.execute(
                    insert(Phd2Frame),
                    [{"session_id": session_row.id, **row} for row in frame_rows],
                )
        for calibration in run.calibrations:
            cal_profile = calibration.header.equipment_profile
            cal_zone, _cal_source = resolve_zone(cal_profile)
            row = build_calibration_row(
                calibration,
                tz_name=cal_zone,
                observer_longitude=resolve_longitude(cal_profile),
                use_imaging_night=use_night,
            )
            db.add(Phd2Calibration(
                log_id=log_row.id,
                telescope=telescopes.get(row["equipment_profile"] or ""),
                **row,
            ))

    db.commit()
    return "ok" if session_total or cal_total else "empty"


def _cleanup_orphans(
    db: Session,
    notices: list[tuple[str, str]] | None = None,
    force: bool = False,
    parent_activity_id: int | None = None,
) -> int:
    """Drop rows for guide logs that no longer exist on disk.

    Existence is the only test used, deliberately: scan include/exclude rules
    can narrow a run's roots, and a log outside this run's roots is not a
    deleted log.

    The whole pass is abandoned when at least ORPHAN_MISSING_FRACTION_LIMIT of
    the stored logs are missing at once, the same guard the image scanner
    applies: a share that dropped off makes every path look deleted, and this
    is the only destructive operation in the module.

    `force` is the admin's one-time cleanup flag arriving from the scan
    endpoint. The guard exists to catch an accident, not to overrule a person
    who has said they deliberately deleted files, and without the bypass a
    genuinely emptied log directory, or any deletion at all from a table of
    one or two rows, could never be reflected in the catalog.

    `notices` collects (event_type, message) pairs so the caller can surface
    them in the activity feed. Both cases are logged either way.

    A deletion here also makes image rows stale. phd2_sessions.log_id cascades,
    so the sessions and frames a deleted log owned go with it, while the images
    keep the guiding values correlation derived from those sessions. Nothing
    else revisits those nights: the end-of-pass dispatch covers the nights this
    pass ingested, a deleted log is by definition not one of them, and
    incremental correlation only visits images that hold no guiding RMS at all.
    So the nights the deleted logs covered are re-derived from here. A night
    left with no surviving guide sessions ends with its phd2-sourced values
    back at NULL, which is the right answer for it.
    """
    rows = db.execute(select(Phd2Log)).scalars().all()
    missing = [r for r in rows if not Path(r.file_path).exists()]
    if not missing:
        return 0

    threshold = max(1, len(rows)) * ORPHAN_MISSING_FRACTION_LIMIT
    large_removal = len(missing) >= threshold
    if large_removal and not force:
        message = (
            f"PHD2 orphan cleanup skipped: {len(missing)} of {len(rows)} "
            "stored guide logs are missing from disk - possible unmounted "
            "share or unreachable storage"
        )
        logger.warning("phd2: %s", message)
        if notices is not None:
            notices.append(("phd2_orphan_warning", message))
        return 0

    # Read before the delete: the cascade takes these session rows with it, so
    # after the commit there is nothing left to ask which nights were affected.
    stale_dates = {
        d for (d,) in db.execute(
            select(Phd2Session.session_date)
            .join(Phd2Log, Phd2Session.log_id == Phd2Log.id)
            .where(
                Phd2Log.id.in_([r.id for r in missing]),
                Phd2Session.session_date.isnot(None),
            )
            .distinct()
        ).all()
    }

    for log_row in missing:
        db.delete(log_row)
    db.commit()

    # After the commit, never before it: a worker that started re-deriving
    # while the rows were still present would refill these nights from the
    # sessions that are about to vanish. This is a second dispatch in a pass
    # that also ingested files, and deliberately so - re-derive is idempotent,
    # and folding these dates into the end-of-pass set would move the dispatch
    # back before the point where the deletion is durable.
    if stale_dates:
        _dispatch_correlation(stale_dates, parent_activity_id)

    if large_removal:
        # Mirrors the image side's orphan_force_warning: the admin asked for
        # this, but a bypass that removed most of the catalog is worth saying
        # out loud in case the share was down when they asked.
        message = (
            f"Forced PHD2 orphan cleanup removed {len(missing)} of "
            f"{len(rows)} stored guide logs. If the storage was unreachable "
            "rather than emptied, re-scan once it is back to re-ingest them."
        )
        logger.warning("phd2: %s", message)
        if notices is not None:
            notices.append(("phd2_orphan_force_warning", message))
    return len(missing)


def _session_date_sanity_check(
    db: Session, session_dates: set[date_type]
) -> tuple[list[str], bool]:
    """Find guiding nights with no images, and say whether they are day-skewed.

    PHD2 timestamps are bare local wall-clock, so a session date can land on
    the wrong night for two different reasons, and the fix differs:

    - A wrong observer_timezone moves the stored UTC instant by a few hours,
      which pushes some sessions over the boundary and leaves others alone.
    - An unset observer_longitude drops the guide-log pass back to
      UTC-midnight grouping while images, which read SITELONG per frame, keep
      solar-noon grouping. For an evening session west of Greenwich that is a
      uniform whole-day offset: every guiding night lands exactly one day
      after the images it belongs with.

    The second element of the return is True when that fingerprint is present:
    no images on the reported night, images on the night before it, for every
    night reported. Only then may the diagnostic blame the longitude.

    Either way this is worth a warning and never a failure - an unguided or
    discarded night looks exactly the same.
    """
    suspicious: list[str] = []
    day_skewed = 0
    for session_date in sorted(session_dates):
        count = db.execute(
            select(func.count()).select_from(Image)
            .where(Image.session_date == session_date)
        ).scalar_one()
        if count:
            continue
        suspicious.append(session_date.isoformat())
        previous = db.execute(
            select(func.count()).select_from(Image)
            .where(Image.session_date == session_date - timedelta(days=1))
        ).scalar_one()
        if previous:
            day_skewed += 1
    return suspicious, bool(suspicious) and day_skewed == len(suspicious)


def _format_offset(hours: float) -> str:
    """A UTC offset written the way a user selects one: UTC-04:00, UTC+05:45.

    Never rounded to whole hours. Real zones sit on quarter hours (Kathmandu
    +5:45, Eucla +8:45), and phd2_sidereal already quantises to a quarter for
    exactly that reason; printing whole hours here would undo it.
    """
    sign = "-" if hours < 0 else "+"
    minutes = int(round(abs(hours) * 60.0))
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _offset_with_alias(hours: float) -> str:
    """An implied offset, plus its 24 h alias where that alias is selectable.

    Pointing fixes the offset only modulo 24 h. `phd2_sidereal` folds its
    answer into [-12, 12) so the value is always one a zone could have, but the
    two-hour band -12 to -10 overlaps the real +12 to +14 zones, so a value
    there is equally consistent with its counterpart 24 h east and the wording
    has to offer both.

    A frame correlation would collapse the pair - an overlapping FITS frame
    carries true UTC, and a 24 h alias would displace the session a whole
    calendar day away from it - but this pass holds no per-profile correlation
    result to test that with, so both readings are offered whenever the band
    applies. Naming two offsets when one could have been ruled out is the safe
    side of that trade; naming one wrongly is not.
    """
    if -12.0 <= hours < -10.0:
        return (
            f"{_format_offset(hours)} (or, equally consistent with the same "
            f"evidence, {_format_offset(hours + 24.0)})"
        )
    return _format_offset(hours)


def _sidereal_findings(
    pointing: list[PointingSample],
    general: GeneralSettings,
    profile_map: dict[str, dict],
    global_tz: str,
) -> list[dict]:
    """Per-profile sidereal verdicts from the pointing this pass collected.

    Evidence only. Nothing here writes a stored value, and a profile with no
    verdict simply produces no entry.

    Everything is resolved PER PROFILE, which is the whole point of the
    feature: a rig carrying its own site is checkable whether or not the
    global observer longitude is set, and that travelling rig is exactly the
    one worth checking.

    - A profile that resolves a longitude - its own, or the global value
      behind it - is compared against that longitude. The tolerance is the
      tight one either way, but the WORDING is not: `site_known` is
      `profile_has_own_longitude` and nothing else, and only a rig standing at
      a longitude the user entered for it may have its finding stated as fact.
      An inherited longitude produces the either/or wording, because "this rig
      is not where you think it is" is then one of the live explanations.
    - A profile that resolves no longitude at all, but does resolve a
      timezone, falls back to that zone's standard meridian: wider tolerance,
      hedged wording, and a suggested longitude as the actionable output.
    - A profile that resolves no timezone is skipped whatever site it carries.
      The correlation pass already names it in
      `phd2_correlation_timezone_unset`, and one cause must not produce two
      warnings.
    - Each section must pass `pointing_is_coherent(...) is True`. The test is
      against True and never against `is not False`: None means the mount wrote
      no altitude, or no latitude is configured for the rig, and neither is
      evidence that the pointing is sound.

    The tier never turns on `profile_site`'s pair-level source, which reads
    "profile" when the entry supplied only a latitude.
    """
    resolve_zone = phd2_profiles.profile_zone_resolver(profile_map, global_tz)
    resolve_longitude = phd2_profiles.longitude_resolver(
        profile_map, general.observer_longitude
    )
    grouped: dict[str | None, list[PointingSample]] = defaultdict(list)
    for sample in pointing:
        grouped[sample.profile].append(sample)

    findings: list[dict] = []
    for profile in sorted(grouped, key=lambda name: (name is None, name or "")):
        zone, _source = resolve_zone(profile)
        longitude = resolve_longitude(profile)
        if not zone:
            # No configured zone, whatever site the profile carries. Besides
            # the one-warning rule above: the comparison is only meaningful
            # against the offset of a zone the user chose, and these sections
            # were read in the server's own zone, so an error measured here
            # would be manufactured out of a known-broken input.
            continue
        # profile_site is asked only for the latitude the coherence gate
        # needs; the longitude comes from the resolver above so that the two
        # questions this function asks about a site stay separate.
        latitude, _lat_pair_lon, _site_source = phd2_profiles.profile_site(
            profile_map, profile,
            general.observer_latitude, general.observer_longitude,
        )
        site_known = phd2_profiles.profile_has_own_longitude(profile_map, profile)
        tier = (
            phd2_sidereal.TIER_SITE_KNOWN if longitude is not None
            else phd2_sidereal.TIER_ZONE_MERIDIAN
        )

        errors: list[float] = []
        implied: list[float] = []
        zone_offsets: set[float] = set()
        for sample in grouped[profile]:
            coherent = phd2_sidereal.pointing_is_coherent(
                sample.alt_deg, sample.dec_deg, sample.hour_angle_hr, latitude
            )
            if coherent is not True:
                continue
            implied_hours = phd2_sidereal.implied_longitude_hours(
                sample.ra_hr, sample.hour_angle_hr, sample.started_at_utc
            )
            meridian = phd2_sidereal.zone_meridian_longitude_deg(
                zone, sample.started_at_utc
            )
            reference = longitude if longitude is not None else meridian
            error = phd2_sidereal.offset_error_hours(implied_hours, reference)
            if error is None or implied_hours is None:
                continue
            errors.append(error)
            implied.append(implied_hours)
            if meridian is not None:
                zone_offsets.add(meridian / 15.0)

        # The offset the configured zone was ACTUALLY using on the nights
        # measured, which is what turns a difference into an offset the user
        # can select. Nights that straddle a daylight-saving change have no
        # single such offset, so none is quoted and the verdict falls back to
        # naming the disagreement itself.
        configured_offset = (
            next(iter(zone_offsets)) if len(zone_offsets) == 1 else None
        )
        outcome = phd2_sidereal.verdict(
            errors,
            tier=tier,
            implied_longitudes_hours=implied,
            configured_offset_hours=configured_offset,
        )
        if outcome is None:
            continue
        findings.append({
            "profile": profile,
            "zone": zone,
            "verdict": outcome,
            "configured_offset_hours": configured_offset,
            "site_known": site_known,
            "longitude_deg": longitude,
        })
    return findings


def _sidereal_clause(finding: dict) -> str:
    """One profile's sentence inside the sidereal warning.

    Three shapes, and which one is used turns on `site_known` rather than on
    the tier alone. A rig compared against a longitude it did not supply is
    measured just as tightly, but "this rig is not at the configured observer
    longitude" is then one of the explanations, so its finding may not be
    stated as fact.
    """
    outcome = finding["verdict"]
    name = _profile_label(finding["profile"])
    # Never empty: a profile with no configured zone never reaches a finding.
    zone = f"timezone '{finding['zone']}'"
    magnitude = round(abs(outcome.nearest_quarter_hours), 2)

    if outcome.tier == phd2_sidereal.TIER_SITE_KNOWN and finding["site_known"]:
        clause = (
            f"{name}: the pointing disagrees with {zone} by about "
            f"{magnitude:g} hours"
        )
        if outcome.implied_utc_offset_hours is not None:
            clause += (
                f", which puts this rig on "
                f"{_offset_with_alias(outcome.implied_utc_offset_hours)} rather "
                f"than the "
                f"{_format_offset(finding['configured_offset_hours'])} that "
                "zone was using"
            )
        elif not outcome.direction_known:
            clause += (
                " - close enough to 12 hours that which way round it goes "
                "cannot be told from pointing alone"
            )
        return (
            clause + ". The likely cause is a wrong timezone on the profile or "
            "a wrong clock on the mount. A longitude entered on the profile "
            "with the wrong sign looks exactly like a timezone error, so check "
            "both."
        )

    if outcome.tier == phd2_sidereal.TIER_SITE_KNOWN:
        # Same arithmetic and the same tolerance, but the longitude was
        # inherited from Observer Location rather than entered for this rig, so
        # the site is a premise rather than a fact and the wording says so.
        clause = (
            f"{name}: read at the configured observer longitude, the pointing "
            f"disagrees with {zone} by about {magnitude:g} hours"
        )
        if outcome.implied_utc_offset_hours is not None:
            clause += (
                f"; if this rig really does stand at that longitude, its clock "
                f"is on "
                f"{_offset_with_alias(outcome.implied_utc_offset_hours)} rather "
                f"than the "
                f"{_format_offset(finding['configured_offset_hours'])} that "
                "zone was using"
            )
        elif not outcome.direction_known:
            clause += (
                " - close enough to 12 hours that which way round it goes "
                "cannot be told from pointing alone"
            )
        return (
            clause + ". Either the profile timezone is wrong, or this rig is "
            "not at the configured observer longitude, or the mount clock is "
            "wrong. Entering this rig's own longitude in Settings > "
            "Equipment > PHD2 Profiles is what tells those apart."
        )

    clause = (
        f"{name}: probably wrong - the pointing disagrees with the standard "
        f"meridian of {zone} by about {magnitude:g} "
        "hours, which is more than the width of any timezone explains"
    )
    if outcome.direction_known and outcome.implied_longitude_deg is not None:
        clause += (
            f". Taking that timezone as correct, the pointing implies a "
            f"longitude near {outcome.implied_longitude_deg:+.1f} degrees, in "
            "the same sign convention as Observer Location; entering it on the "
            "profile in Settings > Equipment > PHD2 Profiles turns this into a "
            "check against a known site"
        )
    return (
        clause + ". This profile carries no longitude of its own, so the "
        "comparison is against a whole timezone rather than a site and only "
        "gross errors show up in it."
    )


def _sidereal_message(findings: list[dict]) -> str:
    """The one activity message the whole pass emits about pointing."""
    names = ", ".join(_profile_label(f["profile"]) for f in findings)
    clauses = " ".join(_sidereal_clause(f) for f in findings)
    return (
        "The guide logs' own pointing disagrees with the configured timezone "
        f"for PHD2 profile(s) {names}. RA plus hour angle is local sidereal "
        "time, which together with the site longitude fixes the UTC offset "
        f"these logs were really written at. {clauses} GalactiLog changed "
        "nothing on the strength of this: the configured timezone is still "
        "what was used to read these logs."
    )


def _sidereal_details(findings: list[dict], general: GeneralSettings) -> dict:
    return {
        "profiles": [
            {
                "profile": f["profile"],
                "median_error_hours": round(f["verdict"].median_error_hours, 4),
                "sections": f["verdict"].sample_count,
                "tier": f["verdict"].tier,
                "confident": f["verdict"].confident,
                "direction_known": f["verdict"].direction_known,
                "implied_utc_offset_hours": f["verdict"].implied_utc_offset_hours,
                "implied_longitude_deg": (
                    None if f["verdict"].implied_longitude_deg is None
                    else round(f["verdict"].implied_longitude_deg, 3)
                ),
                "configured_timezone": f["zone"],
                "site_known": f["site_known"],
                "compared_longitude_deg": f["longitude_deg"],
            }
            for f in findings[:10]
        ],
        "observer_longitude": general.observer_longitude,
    }


def _is_scan_pass(paths: list[str] | None, force: bool) -> bool:
    """True when this pass came from a library walk, not from a settings save.

    A walk happened only when this task was handed the candidate list a scan
    produced. That list is the evidence the library is reachable, and it is
    the only thing that licenses deleting rows or writing the scan-state
    counters.
    """
    return paths is not None and not force


@celery_app.task(name="app.worker.tasks.scan_phd2_logs")
def scan_phd2_logs(
    paths: list[str] | None = None,
    parent_activity_id: int | None = None,
    remap_only: bool = False,
    force: bool = False,
    force_orphan_cleanup: bool = False,
) -> dict:
    """Run the guide-log pass, holding the scan-state in-flight flag around it.

    Only the flag lives here; all the work is in `_run_phd2_pass`. run_scan
    marks the pass pending when it dispatches, and the scan screen's "complete"
    is not the whole truth until this clears - so the flag has to come down on
    every exit, including a crash, or a poller waits on a task that has already
    stopped running. A settings-triggered pass never touches it: it is not part
    of any scan.
    """
    scanned = _is_scan_pass(paths, force)
    if scanned:
        set_phd2_state_sync(_redis, PHD2_STATE_RUNNING)
    try:
        return _run_phd2_pass(
            paths=paths,
            parent_activity_id=parent_activity_id,
            remap_only=remap_only,
            force=force,
            force_orphan_cleanup=force_orphan_cleanup,
        )
    finally:
        if scanned:
            # set_phd2_counts_sync already cleared this on the normal path;
            # rewriting the same value is harmless and covers the paths that
            # never reach it (scanning disabled, or an unhandled failure).
            set_phd2_state_sync(_redis, PHD2_STATE_IDLE)


def _run_phd2_pass(
    paths: list[str] | None = None,
    parent_activity_id: int | None = None,
    remap_only: bool = False,
    force: bool = False,
    force_orphan_cleanup: bool = False,
) -> dict:
    """Ingest the PHD2 guide logs discovered by the library scan.

    `paths` is the full candidate list from this scan's walk; passing None
    means "no discovery happened", which is how the settings-triggered remap
    reaches this task without touching the filesystem.

    `force` re-parses every guide log already in the catalog, bypassing the
    size/mtime short-circuit. That is what a change to observer_timezone needs:
    the zone is applied while parsing, and PHD2 never rewrites a closed log, so
    without it the stored UTC timestamps stay frozen at the zone configured on
    the first ingest. It also re-keys every stored row's night afterwards,
    which is what reaches the rows the re-parse could not: a log whose file has
    since been deleted or unmounted fails at the stat() and keeps its stored
    dates otherwise forever.

    A pass triggered by a settings save (`remap_only`, or `force` with no
    candidate list) corrects rows already held. It never deletes rows, never
    writes the scan-state counters and never claims a scan finished, because
    none of those are true of it.

    `force_orphan_cleanup` is the admin's one-time flag from the scan
    endpoint, forwarded by run_scan alongside the image side's copy of it. It
    lifts the missing-share guard on this pass only, so a deliberate bulk
    deletion of guide logs reaches the catalog. It has no effect on a
    settings-triggered pass, which never purges at all.
    """
    general = _read_settings()

    # Normalized once for the whole pass. Every resolver below is built from
    # this dict rather than from the raw setting, so the stored map is coerced
    # a single time however many files and rows the pass touches.
    profile_map = phd2_profiles.normalize_profile_map(general.phd2_profile_map)

    # phd2_scan_enabled gates discovery of guide logs on disk. Re-keying and
    # re-parsing rows that are already in the catalog correct data the user
    # already has, so they run whether or not discovery is switched on -
    # otherwise a profile-map or timezone edit is a silent no-op.
    if remap_only:
        with Session(_sync_engine) as db:
            changed = apply_profile_map(db, profile_map)
            db.commit()
            # A remap changes which rig a session belongs to, so every frame
            # whose guiding came from one of these sessions is now potentially
            # attributed to the wrong telescope. Incremental mode would never
            # revisit those frames - they already hold a value - so the
            # affected nights are re-derived explicitly.
            dates = phd2_correlation.affected_dates(db)
        _invalidate_stats_cache()
        logger.info("phd2: profile map applied, %d rows re-keyed", changed)
        if dates:
            _dispatch_correlation(dates)
        return {"status": "remapped", "rows": changed}

    scanned = _is_scan_pass(paths, force)

    if force:
        candidates = list(paths) if paths else _stored_log_paths()
    elif not general.phd2_scan_enabled:
        logger.info("phd2: scanning disabled, skipping")
        return {"status": "skipped", "reason": "disabled"}
    else:
        candidates = list(paths or [])

    # Resolved once for the whole pass: an unusable zone is one fact about the
    # settings, not one fact per file, and the user has to be told about it.
    tz_name = _safe_timezone(general.observer_timezone)
    tz_invalid = bool(general.observer_timezone) and not tz_name

    # AUD-021, guide-log side. Images resolve a longitude per frame from
    # SITELONG, so imaging-night grouping keeps working for them whatever the
    # settings say. A guide log carries no coordinates of its own, so the
    # longitude comes from the equipment profile it names or from the global
    # observer_longitude behind it, and with neither set the affected sessions
    # silently drop back to UTC-midnight grouping while the images they should
    # line up with keep the solar-noon boundary.
    #
    # This is now a per-profile question, so the answer is a SET of profile
    # names rather than one flag: a user who gave the travelling rig its own
    # site and left the home rig on the global value has one grouped correctly
    # and one not. The warning is still emitted once per pass, which is what
    # warn_imaging_night_fallback's own docstring requires of its callers, and
    # is raised after the ingest loop because only then is it known which
    # profiles this pass actually saw.
    resolve_longitude = phd2_profiles.longitude_resolver(
        profile_map, general.observer_longitude
    )

    found = len(candidates)
    ingested = 0
    failed = 0
    empty = 0
    ingested_paths: list[str] = []
    touched_dates: set[date_type] = set()
    orphan_notices: list[tuple[str, str]] = []
    pointing: list[PointingSample] = []
    seen_profiles: set[str | None] = set()

    # Publish the denominator now rather than at the end. The scan screen
    # counts "N of M" guide logs while the pass runs, and M has been known
    # since the candidate list was built; writing it only in the pass's final
    # counter write left the UI counting against zero for the whole pass.
    # Gated on `scanned` for the same reason that write is: a
    # settings-triggered pass is not a scan and has no scan progress to
    # describe.
    if scanned:
        set_phd2_found_sync(_redis, found)

    # The scan screen's numerator counts files LOOKED AT, not files ingested:
    # on a routine rescan nearly everything short-circuits as unchanged, and a
    # numerator of ingested+failed reads "0 of 179" for the whole pass and
    # then jumps to done. Flushed in batches because a Redis round trip per
    # unchanged file is the overhead the progress counters' contract promises
    # to avoid; the end-of-pass counts write settles the remainder.
    checked_batch = 0
    CHECKED_FLUSH_EVERY = 25

    with Session(_sync_engine) as db:
        for path in candidates:
            # Collected per file and kept only when the file went in whole. A
            # file that crashed mid-parse has already contributed sections, and
            # pointing from a log the catalog does not hold is not evidence
            # about anything the user can see.
            file_pointing: list[PointingSample] = []
            checked_batch += 1
            flush = 0
            if checked_batch >= CHECKED_FLUSH_EVERY:
                flush, checked_batch = checked_batch, 0
            try:
                result = ingest_phd2_log(
                    db, path, general, tz_name=tz_name, force=force,
                    pointing=file_pointing,
                )
            except Exception:  # noqa: BLE001 - one bad file must not stop the pass
                logger.exception("phd2: ingest crashed for %s", path)
                db.rollback()
                failed += 1
                if scanned:
                    increment_phd2_progress_sync(_redis, failed=1, checked=flush)
                continue
            if result == "ok":
                ingested += 1
                ingested_paths.append(path)
                pointing.extend(file_pointing)
                if scanned:
                    increment_phd2_progress_sync(_redis, ingested=1, checked=flush)
            elif result == "empty":
                empty += 1
                if scanned and flush:
                    increment_phd2_progress_sync(_redis, checked=flush)
            elif result == "unchanged":
                if scanned and flush:
                    increment_phd2_progress_sync(_redis, checked=flush)
            elif result == "failed":
                failed += 1
                if scanned:
                    increment_phd2_progress_sync(_redis, failed=1, checked=flush)

        # The map may have changed since the last scan; re-applying it here
        # keeps existing rows converged without a second task.
        apply_profile_map(db, profile_map)

        # A forced pass is what a timezone edit dispatches, and it must reach
        # every stored row - not only the ones it managed to re-parse. A log
        # whose file has since vanished returns "failed" before any row is
        # rewritten, and orphan cleanup never runs on a settings-triggered
        # pass, so without this its session_date stays frozen under whatever
        # site was configured when it was first read. session_date is derived
        # from started_at_utc, which no longitude affects, so re-keying needs
        # no file at all. Re-keying a row this pass has just written compares
        # equal and writes nothing, which is what makes it safe to run over
        # both.
        if force:
            rekeyed = _rekey_phd2_sessions(
                db,
                use_night=general.use_imaging_night,
                resolve_longitude=resolve_longitude,
            )
            if rekeyed:
                logger.info(
                    "phd2: %d stored guide-log row(s) moved to another night",
                    rekeyed,
                )
        db.commit()

        # Purging is a scan's conclusion, never a settings save's. Saving the
        # observer timezone while the share is unreachable used to fail every
        # stat() and then delete every row, from a UI action nobody would
        # associate with a purge.
        removed = (
            _cleanup_orphans(
                db, orphan_notices, force_orphan_cleanup,
                parent_activity_id=parent_activity_id,
            )
            if scanned else 0
        )

        if ingested_paths:
            # Only the nights this pass actually wrote. Querying every date in
            # the table would re-report the entire history as suspicious on
            # every scan that ingests a single new file.
            touched_dates = {
                d for (d,) in db.execute(
                    select(Phd2Session.session_date)
                    .join(Phd2Log, Phd2Session.log_id == Phd2Log.id)
                    .where(
                        Phd2Log.file_path.in_(ingested_paths),
                        Phd2Session.session_date.isnot(None),
                    )
                    .distinct()
                ).all()
            }
            # Which rigs this pass saw. Both the imaging-night fallback and the
            # unmapped-profile notice below are questions about the profiles in
            # play, and calibrations name a profile exactly as sessions do, so
            # a file holding only calibrations still answers them.
            for model in (Phd2Session, Phd2Calibration):
                seen_profiles.update(
                    p for (p,) in db.execute(
                        select(model.equipment_profile)
                        .join(Phd2Log, model.log_id == Phd2Log.id)
                        .where(Phd2Log.file_path.in_(ingested_paths))
                        .distinct()
                    ).all()
                )
        suspicious, day_skewed = (
            _session_date_sanity_check(db, touched_dates)
            if touched_dates else ([], False)
        )

    # The profiles this pass saw that resolved to no longitude at either
    # level, which is what actually decides whether grouping fell back.
    night_fallback = sorted(
        _profile_label(profile) for profile in seen_profiles
        if general.use_imaging_night and resolve_longitude(profile) is None
    )
    if night_fallback:
        warn_imaging_night_fallback(logger)

    # Risk the per-rig site introduced: a profile renamed in PHD2, or one that
    # was never mapped, inherits the home longitude silently and is filed under
    # the home night while looking entirely normal. Naming the profiles this
    # pass saw with no entry at all is what makes that visible; it rides on the
    # pass's own report rather than becoming a warning of its own, because the
    # correlation pass already warns about unattributed profiles and one cause
    # must not produce two messages.
    unmapped_profiles = sorted(
        profile for profile in seen_profiles
        if profile and profile not in profile_map
    )
    if unmapped_profiles:
        logger.info(
            "phd2: profile(s) with no entry in the PHD2 profile map: %s",
            ", ".join(unmapped_profiles),
        )

    # The sidereal cross-check, over the sections this pass parsed. Never on a
    # remap, which returned long ago and parsed nothing. There is deliberately
    # no global-longitude gate here: whether a rig can be checked, and how
    # confidently, is a per-profile question that _sidereal_findings answers
    # profile by profile. A rig carrying its own site is checkable while the
    # global longitude is unset, and that travelling rig is the one this whole
    # feature exists for.
    sidereal = (
        _sidereal_findings(pointing, general, profile_map, tz_name)
        if pointing else []
    )

    # The scan-state counters describe the library scan on the scan screen.
    # A settings save is not a scan, and writing them from one made the panel
    # report a scan that never ran.
    if scanned:
        set_phd2_counts_sync(_redis, found, ingested, failed)
    _invalidate_stats_cache()

    # Re-derive the nights this pass wrote. A guide log is replaced whole on
    # re-ingest (delete then reparse), so a frame's stored guiding RMS can be
    # derived from sessions that no longer exist; only a re-derive of the
    # touched nights clears that. Nights this pass did not touch keep their
    # values and cost nothing.
    if touched_dates:
        _dispatch_correlation(touched_dates, parent_activity_id)

    if scanned:
        message = (
            f"PHD2 logs: {ingested} ingested, {empty} empty, {failed} failed, "
            f"{removed} removed of {found} found"
        )
        event_type = "phd2_scan_complete"
    else:
        message = (
            f"PHD2 guide logs re-read after a settings change: {ingested} "
            f"updated, {empty} empty, {failed} failed of {found} stored"
        )
        event_type = "phd2_settings_reapplied"

    with _activity_session() as adb:
        _emit_activity_sync(
            adb, redis=_redis, category="scan", severity="info",
            event_type=event_type, message=message,
            details={
                "found": found, "ingested": ingested, "empty": empty,
                "failed": failed, "removed": removed,
                "unmapped_profiles": unmapped_profiles[:20],
            },
            actor="system", parent_id=parent_activity_id,
        )
        for notice_type, notice in orphan_notices:
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type=notice_type, message=notice,
                details={"forced": force_orphan_cleanup}, actor="system",
                parent_id=parent_activity_id,
            )
        if tz_invalid:
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type="phd2_timezone_invalid",
                message=(
                    f"Observer timezone '{general.observer_timezone}' is not a "
                    "known IANA zone. Guide-log timestamps were read in the "
                    "server's local zone instead."
                ),
                details={"observer_timezone": general.observer_timezone},
                actor="system", parent_id=parent_activity_id,
            )
        if suspicious and night_fallback and day_skewed:
            # Every reported night has its images on the night before: that is
            # the missing-longitude fingerprint, not a timezone error, and
            # telling the user to check the timezone sends them to a setting
            # that is already right (smoke test, finding 4.1).
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type="phd2_longitude_missing",
                message=(
                    f"Guiding sessions on {len(suspicious)} night(s) landed "
                    "one day after the images they belong with. This happens "
                    "when no observer longitude is set for the PHD2 profile(s) "
                    f"{', '.join(night_fallback[:10])}: guide sessions are "
                    "then grouped by UTC midnight while images are grouped by "
                    "local solar noon. Open Settings > Library > Observer "
                    "Location and set Longitude to the longitude of your "
                    "imaging site, or, for a rig that stands somewhere else, "
                    "set a longitude on its profile in Settings > Equipment > "
                    "PHD2 Profiles."
                ),
                details={
                    "session_dates": suspicious[:50],
                    "observer_longitude": general.observer_longitude,
                    "profiles": night_fallback[:10],
                    "use_imaging_night": True,
                },
                actor="system", parent_id=parent_activity_id,
            )
        elif suspicious:
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type="phd2_timezone_mismatch",
                message=(
                    f"Guiding sessions on {len(suspicious)} night(s) matched "
                    "no images. The usual cause is that the timezone "
                    "GalactiLog assumes for PHD2 log timestamps is not the "
                    "timezone of the PC that runs PHD2, because PHD2 writes "
                    "local wall-clock time with no zone. Open Settings > "
                    "Library > Observer Location and set Timezone to the "
                    "timezone of the PC that runs PHD2, or set a timezone on "
                    "the profile in Settings > Equipment > PHD2 Profiles for a "
                    "rig that runs on a clock of its own."
                ),
                details={"session_dates": suspicious[:50]},
                actor="system", parent_id=parent_activity_id,
            )
        if sidereal:
            # One row for the whole pass however many profiles it names: this
            # is a statement about the configuration, and a row per profile per
            # scan is how a feed stops being read.
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type="phd2_timezone_sidereal_mismatch",
                message=_sidereal_message(sidereal),
                details=_sidereal_details(sidereal, general),
                actor="system", parent_id=parent_activity_id,
            )

    logger.info("phd2: %s", message)
    return {
        "status": "complete", "found": found, "ingested": ingested,
        "empty": empty, "failed": failed, "removed": removed,
        "timezone_warnings": len(suspicious),
        "sidereal_warnings": len(sidereal),
    }


def _dispatch_correlation(
    dates, parent_activity_id: int | None = None, countdown: int = 5
) -> None:
    """Queue the per-image correlation pass, best effort.

    Correlation is auxiliary to the guide-log pass: by the time it is queued
    the sessions and frames are already committed, so a broker problem at
    this one call must not raise out of a pass that succeeded. The next scan
    picks the work up either way, because incremental mode looks for images
    with no guiding RMS rather than for a marker this call would have left.

    Every caller names its nights in guide-log date space: `stale_dates` and
    `touched_dates` are Phd2Session.session_date values, and so is half of
    phd2_correlation.affected_dates. correlate_dates consumes them as
    Image.session_date. Those are two different spaces - with the observer
    longitude unset, which is the default, guide sessions group by UTC
    midnight while images keep solar-noon grouping, so a session dated D
    covers frames dated D-1 (the fingerprint _session_date_sanity_check warns
    about). So each night is widened by a day either way before it is
    dispatched, the same widening and for the same reason as
    phd2_correlation._dates_needing_fill. Widening here rather than at the
    three call sites is deliberate: this is the single seam every re-derive
    crosses, and a later caller gets the correction for free. The cost is a
    bounded 3x on nights visited, and re-derive is idempotent, so a widened
    night that holds nothing simply finds nothing.

    `dates` crosses the broker as ISO strings. Celery kwargs are
    JSON-serialised and a datetime.date does not survive the round trip; it
    arrives as a string the task would then have to parse anyway, so it is
    converted here where the failure is visible.
    """
    if dates is None:
        payload = None
    else:
        widened: set[date_type] = set()
        for d in dates:
            widened.update({d - timedelta(days=1), d, d + timedelta(days=1)})
        payload = sorted(d.isoformat() for d in widened)
    try:
        correlate_phd2_images.apply_async(
            countdown=countdown,
            kwargs={"dates": payload, "parent_activity_id": parent_activity_id},
        )
    except Exception:
        logger.warning(
            "phd2: could not dispatch the per-image correlation pass "
            "(%s); the next scan will pick it up",
            "incremental" if payload is None else f"{len(payload)} night(s)",
            exc_info=True,
        )


def _emit_correlation_activity(result, parent_activity_id: int | None) -> None:
    """Report a correlation pass, but only when it changed something.

    An idle scan runs this pass and finds nothing to do. Emitting then would
    add a row to the activity feed on every scan interval, which is how a
    feed stops being read.
    """
    if not (result.filled or result.cleared or result.unattributed_profiles):
        return
    with _activity_session() as adb:
        if result.filled or result.cleared:
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="info",
                event_type="phd2_correlation_complete",
                message=f"PHD2 guiding matched to frames: {result.summary()}",
                details={
                    "dates": result.dates,
                    "images_considered": result.images_considered,
                    "filled": result.filled,
                    "cleared": result.cleared,
                    "below_gate": result.below_gate,
                },
                actor="system", parent_id=parent_activity_id,
            )
        if result.unattributed_profiles:
            names = ", ".join(result.unattributed_profiles)
            _emit_activity_sync(
                adb, redis=_redis, category="scan", severity="warning",
                event_type="phd2_correlation_unattributed",
                message=(
                    f"Guiding from PHD2 profile(s) {names} was not matched to "
                    "any frame: the night used more than one telescope and the "
                    "profile is not mapped to one of them. Open Settings > "
                    "Equipment > PHD2 Profiles and map the profile to the "
                    "telescope it guides."
                ),
                details={
                    "profiles": result.unattributed_profiles,
                    "action": {
                        "label": "Map PHD2 profiles",
                        "href": "/settings?tab=equipment#phd2-profiles",
                    },
                },
                actor="system", parent_id=parent_activity_id,
            )


@celery_app.task(name="app.worker.tasks.correlate_phd2_images")
def correlate_phd2_images(
    dates: list[str] | None = None,
    parent_activity_id: int | None = None,
) -> dict:
    """Fill each frame's guiding RMS from the PHD2 samples that cover it.

    `dates` is the ISO-string list of imaging nights to RE-DERIVE: every
    phd2-sourced value on them is cleared and recomputed, which is what a
    re-ingested log or an edited profile map requires. `None` is incremental
    mode, run from the image-scan seams: fill frames that have no guiding RMS
    at all and re-derive nothing.
    """
    parsed = None
    if dates is not None:
        parsed = []
        for value in dates:
            try:
                parsed.append(date_type.fromisoformat(value))
            except (TypeError, ValueError):
                logger.warning(
                    "phd2: ignoring unparsable correlation date %r", value
                )

    with Session(_sync_engine) as db:
        result = phd2_correlation.correlate_dates(db, parsed)
        db.commit()

    _invalidate_stats_cache()
    _emit_correlation_activity(result, parent_activity_id)
    logger.info("phd2 correlation: %s", result.summary())
    return {
        "status": "complete",
        "dates": result.dates,
        "images_considered": result.images_considered,
        "filled": result.filled,
        "cleared": result.cleared,
        "below_gate": result.below_gate,
        "unattributed_profiles": result.unattributed_profiles,
    }
