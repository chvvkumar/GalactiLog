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
from datetime import date as date_type, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models import Image
from app.models.phd2 import Phd2Calibration, Phd2Frame, Phd2Log, Phd2Session
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.schemas.settings import GeneralSettings
from app.services import phd2_parser
from app.services.activity import emit_sync as _emit_activity_sync
from app.services.phd2_metrics import (
    build_calibration_row, build_frame_rows, compute_session_metrics,
)
from app.services.scan_state import (
    PHD2_STATE_IDLE, PHD2_STATE_RUNNING, set_phd2_counts_sync,
    set_phd2_state_sync,
)
from app.services.session_date import warn_imaging_night_fallback
from app.worker.celery_app import celery_app
from app.worker.tasks_common import (
    _activity_session, _invalidate_stats_cache, _redis, _sync_engine,
)

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


def apply_profile_map(db: Session, profile_map: dict[str, str]) -> int:
    """Re-resolve every stored session's telescope from the current map.

    The mapping is a user setting, not a property of the log, so editing it
    must not require re-reading files. Returns the number of rows whose
    telescope actually changed. Caller commits.
    """
    changed = 0
    rows = db.execute(select(Phd2Session)).scalars().all()
    for row in rows:
        wanted = profile_map.get(row.equipment_profile or "")
        if row.telescope != wanted:
            row.telescope = wanted
            changed += 1
    cal_rows = db.execute(select(Phd2Calibration)).scalars().all()
    for row in cal_rows:
        wanted = profile_map.get(row.equipment_profile or "")
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


def ingest_phd2_log(
    db: Session,
    path: str,
    general: GeneralSettings,
    tz_name: str | None = None,
    force: bool = False,
) -> str:
    """Parse one guide log into the DB. Returns ok | empty | unchanged | failed.

    Everything for a single file happens in one transaction: the old rows are
    deleted and the new ones inserted together, so an interrupted re-parse can
    never leave a log half-replaced.

    `force` skips the size/mtime short-circuit. PHD2 never rewrites a closed
    log, so a file already stored is otherwise never read again and a change
    to the observer timezone could never reach it.

    `tz_name` is the already-resolved zone; the caller resolves it once per
    pass so a bad value is reported once rather than logged per file.
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
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the scan
        logger.exception("phd2: parse failed for %s", path)
        if existing is not None:
            # Flushed before the replacement row is added: file_path is unique
            # and the unit of work orders same-table inserts ahead of deletes,
            # so without this the failure row collides with the row it
            # replaces.
            db.delete(existing)
            db.flush()
        db.add(Phd2Log(
            file_path=path, file_size=stat.st_size, file_mtime=stat.st_mtime,
            parse_status="failed", parse_error=str(exc)[:2000],
        ))
        db.commit()
        return "failed"

    if tz_name is None:
        tz_name = _safe_timezone(general.observer_timezone)
    longitude = general.observer_longitude
    use_night = general.use_imaging_night
    profile_map = general.phd2_profile_map or {}

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
            logger.info("phd2: %s: %s", file_path.name, warning)
        for section_index, section in enumerate(run.sections):
            metrics = compute_session_metrics(
                section,
                tz_name=tz_name,
                observer_longitude=longitude,
                use_imaging_night=use_night,
            )
            session_row = Phd2Session(
                log_id=log_row.id,
                run_index=run_index,
                section_index=section_index,
                telescope=profile_map.get(metrics.equipment_profile or ""),
                **{
                    k: v for k, v in vars(metrics).items()
                },
            )
            db.add(session_row)
            db.flush()
            frame_rows = build_frame_rows(section)
            if frame_rows:
                db.execute(
                    insert(Phd2Frame),
                    [{"session_id": session_row.id, **row} for row in frame_rows],
                )
        for calibration in run.calibrations:
            row = build_calibration_row(
                calibration,
                tz_name=tz_name,
                observer_longitude=longitude,
                use_imaging_night=use_night,
            )
            db.add(Phd2Calibration(
                log_id=log_row.id,
                telescope=profile_map.get(row["equipment_profile"] or ""),
                **row,
            ))

    db.commit()
    return "ok" if session_total or cal_total else "empty"


def _cleanup_orphans(
    db: Session,
    notices: list[tuple[str, str]] | None = None,
    force: bool = False,
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

    for log_row in missing:
        db.delete(log_row)
    db.commit()

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
    the first ingest.

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

    # phd2_scan_enabled gates discovery of guide logs on disk. Re-keying and
    # re-parsing rows that are already in the catalog correct data the user
    # already has, so they run whether or not discovery is switched on -
    # otherwise a profile-map or timezone edit is a silent no-op.
    if remap_only:
        with Session(_sync_engine) as db:
            changed = apply_profile_map(db, general.phd2_profile_map or {})
            db.commit()
        _invalidate_stats_cache()
        logger.info("phd2: profile map applied, %d rows re-keyed", changed)
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
    # settings say. A guide log carries no coordinates at all, so the global
    # observer_longitude is the only source there is, and leaving it unset
    # silently drops this whole pass back to UTC-midnight grouping while the
    # images it should line up with keep the solar-noon boundary. Warned once
    # per pass, exactly as the image scanner and the session-date recompute
    # warn for their own paths, rather than once per file.
    night_fallback = general.use_imaging_night and general.observer_longitude is None
    if night_fallback and candidates:
        warn_imaging_night_fallback(logger)

    found = len(candidates)
    ingested = 0
    failed = 0
    empty = 0
    ingested_paths: list[str] = []
    touched_dates: set[date_type] = set()
    orphan_notices: list[tuple[str, str]] = []

    with Session(_sync_engine) as db:
        for path in candidates:
            try:
                result = ingest_phd2_log(
                    db, path, general, tz_name=tz_name, force=force
                )
            except Exception:  # noqa: BLE001 - one bad file must not stop the pass
                logger.exception("phd2: ingest crashed for %s", path)
                db.rollback()
                failed += 1
                continue
            if result == "ok":
                ingested += 1
                ingested_paths.append(path)
            elif result == "empty":
                empty += 1
            elif result == "failed":
                failed += 1

        # The map may have changed since the last scan; re-applying it here
        # keeps existing rows converged without a second task.
        apply_profile_map(db, general.phd2_profile_map or {})
        db.commit()

        # Purging is a scan's conclusion, never a settings save's. Saving the
        # observer timezone while the share is unreachable used to fail every
        # stat() and then delete every row, from a UI action nobody would
        # associate with a purge.
        removed = (
            _cleanup_orphans(db, orphan_notices, force_orphan_cleanup)
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
        suspicious, day_skewed = (
            _session_date_sanity_check(db, touched_dates)
            if touched_dates else ([], False)
        )

    # The scan-state counters describe the library scan on the scan screen.
    # A settings save is not a scan, and writing them from one made the panel
    # report a scan that never ran.
    if scanned:
        set_phd2_counts_sync(_redis, found, ingested, failed)
    _invalidate_stats_cache()

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
                    "when the observer longitude is not set: guide sessions "
                    "are then grouped by UTC midnight while images are "
                    "grouped by local solar noon. Open Settings > Library > "
                    "Observer Location and set Longitude to the longitude of "
                    "your imaging site."
                ),
                details={
                    "session_dates": suspicious[:50],
                    "observer_longitude": None,
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
                    "timezone of the PC that runs PHD2."
                ),
                details={"session_dates": suspicious[:50]},
                actor="system", parent_id=parent_activity_id,
            )

    logger.info("phd2: %s", message)
    return {
        "status": "complete", "found": found, "ingested": ingested,
        "empty": empty, "failed": failed, "removed": removed,
        "timezone_warnings": len(suspicious),
    }
