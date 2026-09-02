"""Discovery + ingest pipeline: run_scan, auto_scan_tick, ingest_file,
reingest_changed_file, and the shared _do_ingest core they both call."""
import logging
import time
from pathlib import Path

import fitsio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Image
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.scanner import extract_metadata, CALIBRATION_FRAME_TYPES
from app.services.target_resolver import resolve_target
from app.services.mosaic_detection import resolve_panel_membership, prune_stale_panel_sessions
from app.services.orphan_cleanup import (
    cleanup_orphaned_images,
    thumbnail_referenced as _thumbnail_referenced_impl,
)
from app.services.thumbnail import generate_thumbnail
from app.services.xisf_parser import extract_xisf_metadata, generate_xisf_thumbnail
from app.services.session_date import (
    compute_session_date,
    extract_longitude,
    warn_imaging_night_fallback,
)
from app.schemas.settings import GeneralSettings
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis, _activity_session, _invalidate_stats_cache
from app.worker.tasks_thumbnails import generate_reference_thumbnails
from app.worker.tasks_target_dedup import detect_duplicate_targets
from app.worker.tasks_sessions import backfill_dark_hours
from app.worker.tasks_phd2 import correlate_phd2_images, scan_phd2_logs
from app.services.scan_state import (
    increment_completed_sync, increment_failed_sync, increment_csv_enriched_sync,
    increment_skipped_calibration_sync,
    start_scanning_sync, set_ingesting_sync, set_idle_sync,
    set_discovered_sync, is_cancel_requested_sync, clear_cancel_sync, set_cancelled_sync,
    check_complete_sync, dispatch_pending_rescan_sync, arm_pending_rescan_sync,
    add_skipped_path_sync, get_skipped_paths_sync, clear_skipped_paths_sync,
    rebuild_skipped_paths_sync,
    reset_phd2_counts_sync, set_phd2_state_sync, PHD2_STATE_IDLE,
)
from app.services.activity import emit_sync as _emit_activity_sync

logger = logging.getLogger(__name__)

# Guards run_scan against duplicate concurrent execution (AUD-016): a second
# dispatch (double-click, or auto_scan_tick racing a manual trigger) bails
# out immediately instead of enumerating the tree twice. TTL covers only the
# enumeration/dispatch phase of run_scan, not the async ingest tasks it queues,
# so it self-heals quickly if a worker dies mid-scan.
SCAN_RUN_LOCK = "scan:run_lock"
SCAN_RUN_LOCK_TTL = 300  # 5 minutes

# AUD-021: _do_ingest runs once per image, so the imaging-night UTC-fallback
# warning must not be emitted per call (tens of thousands per scan, and app.*
# loggers feed the DB-backed app_logs sink). Module-level once-per-process
# guard: each worker process warns at most once.
_imaging_night_fallback_warned = False

# Per-process cache of the GeneralSettings row. _do_ingest read this row (a new
# Session + query) for EVERY ingested file; a 20k-file scan meant 20k redundant
# sessions/queries for a value that changes rarely. Cache it in-process with a
# short TTL (pattern: normalization._alias_cache). The TTL bounds staleness for
# a setting change made mid-scan without needing an explicit invalidation hook.
_general_settings_cache: "GeneralSettings | None" = None
_general_settings_cache_ts: float = 0.0
_GENERAL_SETTINGS_CACHE_TTL = 30.0


def _dispatch_phd2_scan(
    paths: list[str],
    parent_activity_id=None,
    force_orphan_cleanup: bool = False,
) -> None:
    """Queue the PHD2 guide-log pass at the tail of a scan, best effort.

    The guide-log pass is auxiliary to the image scan: by the time it is
    dispatched the ingest tasks are already queued and the orphan cleanup is
    already committed, so a broker problem at this one call must not raise out
    of run_scan and mark an otherwise-complete scan as failed. The candidates
    are rediscovered by the next walk either way.

    `force_orphan_cleanup` is forwarded so an admin who asked to reflect a
    deliberate bulk deletion gets it applied to guide logs as well as to
    images. Without it the guide-log side has no route past its own
    missing-share guard, and a genuinely emptied log directory could never be
    cleared from the catalog.

    The scan-state counters for this pass are zeroed here rather than in the
    task, because the task only starts running a minute later: until then
    scan:state would still be publishing the previous scan's guide-log totals
    next to a state of "complete", and a caller polling for completeness would
    read them as this run's.

    The candidate count goes with them, for the same reason and with the
    opposite sign: the pass is claimed here but does not start for another 50
    seconds, so the denominator the task publishes when it starts arrives long
    after the job row is on screen. The number is already in hand here, so the
    row can carry "0 of N logs" from its first render rather than showing an
    unlabelled bar for the whole countdown.
    """
    reset_phd2_counts_sync(_redis, len(paths))
    try:
        scan_phd2_logs.apply_async(
            countdown=50,
            kwargs={
                "paths": paths,
                "parent_activity_id": parent_activity_id,
                "force_orphan_cleanup": force_orphan_cleanup,
            },
        )
    except Exception:
        # Nothing will run, so nothing may claim to be in flight: leaving the
        # flag set would strand a poller waiting on a task that was never
        # queued.
        set_phd2_state_sync(_redis, PHD2_STATE_IDLE)
        logger.warning(
            "run_scan: could not dispatch the PHD2 guide-log pass (%d candidates); "
            "they will be picked up by the next scan",
            len(paths), exc_info=True,
        )


def _get_cached_general_settings() -> GeneralSettings:
    """Return the GeneralSettings row, cached per process with a short TTL."""
    global _general_settings_cache, _general_settings_cache_ts
    now = time.monotonic()
    if (
        _general_settings_cache is not None
        and (now - _general_settings_cache_ts) < _GENERAL_SETTINGS_CACHE_TTL
    ):
        return _general_settings_cache
    with Session(_sync_engine) as s:
        row = s.get(UserSettings, SETTINGS_ROW_ID)
        general = GeneralSettings(**(row.general if row and row.general else {}))
    _general_settings_cache = general
    _general_settings_cache_ts = now
    return general


@celery_app.task(bind=True, name="app.worker.tasks.run_scan")
def run_scan(
    self,
    include_calibration: bool = True,
    force_orphan_cleanup: bool = False,
    queued: bool = False,
) -> dict:
    """Scan the FITS directory and queue ingest tasks for new files.

    Runs entirely inside Celery so the HTTP endpoint returns immediately.

    When ``force_orphan_cleanup`` is True, the 50%-missing safety threshold on
    orphan cleanup is bypassed so a deliberate bulk deletion is reflected in the
    catalog. This flag is ephemeral and never set by auto-scans.
    """
    if not _redis.set(SCAN_RUN_LOCK, "1", nx=True, ex=SCAN_RUN_LOCK_TTL):
        logger.info(
            "run_scan: a scan is already running (run lock held), "
            "skipping duplicate dispatch; queued as a follow-up instead"
        )
        # A follow-up that bails here does no work at all, and the flag that
        # asked for it was already consumed by the dispatch - so the queued
        # rescan would just vanish. Put it back and let whoever holds the lock
        # dispatch it again when they finish. Only ``queued`` runs re-arm: an
        # ordinary duplicate dispatch (auto_scan_tick racing a manual scan)
        # bails and stays bailed, as it always has.
        if queued:
            arm_pending_rescan_sync(_redis, include_calibration)
        return {"status": "skipped", "reason": "already running"}
    try:
        from app.services.scanner import scan_directory

        clear_cancel_sync(_redis)
        start_scanning_sync(_redis)

        # Get known paths and file stats from DB for delta scanning
        with Session(_sync_engine) as session:
            result = session.execute(
                select(Image.file_path, Image.file_size, Image.file_mtime)
            )
            rows = result.all()
            known_paths = {row[0] for row in rows}
            known_file_stats = {row[0]: (row[1], row[2]) for row in rows}

        # Include previously skipped calibration paths so they aren't re-queued.
        # Rebuild the tracked set to only paths still present on disk (files
        # that were deleted or moved since the last scan are dropped) so it
        # can't grow unbounded; the 7-day TTL in rebuild_skipped_paths_sync is
        # a backstop on top of this.
        if not include_calibration:
            prior_skipped = get_skipped_paths_sync(_redis)
            still_present = {p for p in prior_skipped if Path(p).exists()}
            rebuild_skipped_paths_sync(_redis, still_present)
            known_paths |= still_present
        else:
            # Calibration now included - clear the skip cache so they get ingested
            clear_skipped_paths_sync(_redis)

        fits_root = Path(settings.fits_data_path)

        # Load scan filters from user settings
        from app.services.scan_filters import ScanFilterConfig
        with Session(_sync_engine) as session:
            us = session.execute(
                select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
            ).scalar_one_or_none()
            general = (us.general if us else {}) or {}
        try:
            filter_config = ScanFilterConfig.from_settings(general, fits_root)
        except ValueError as exc:
            logger.error("Invalid scan filters, scanning with no filters: %s", exc)
            filter_config = ScanFilterConfig(include_paths=[], exclude_paths=[], name_rules=[])

        # Dispatch ingest tasks as files are discovered (parallel discovery + ingestion)
        # Calibration filtering is deferred to the ingest phase to avoid opening
        # every file during discovery (costly on NFS).
        # Guard against dispatching the same path twice within one scan
        # (AUD-015). roots() already drops nested include paths, but this is a
        # cheap belt-and-suspenders against any other overlap source (e.g.
        # symlinks resolving two roots onto the same tree).
        queued_paths: set[str] = set()

        # PHD2 guide logs discovered by the same walk. Collected rather than
        # dispatched per file: the whole set is needed at once so the ingest
        # task can tell a deleted log from one that simply moved out of this
        # run's roots.
        phd2_paths: list[str] = []

        def _queue_phd2_file(path: Path) -> None:
            phd2_paths.append(str(path))

        def _queue_file(path: Path) -> None:
            key = str(path)
            if key in queued_paths:
                return
            queued_paths.add(key)
            ingest_file.delay(str(path), include_calibration=include_calibration)

        def _queue_changed_file(path: Path) -> None:
            """Re-ingest a known file whose size or mtime changed on disk."""
            key = str(path)
            if key in queued_paths:
                return
            queued_paths.add(key)
            reingest_changed_file.delay(str(path), include_calibration=include_calibration)

        new_files: list[Path] = []
        changed_files: list[Path] = []
        all_disk_paths: set[str] = set()

        def _on_discovery_progress(count: int) -> None:
            # Refresh the run lock while the (possibly long, NFS-bound) tree walk
            # is in progress. The lock's 5-minute TTL otherwise expires under a
            # slow walk, letting a second scan start concurrently.
            set_discovered_sync(_redis, count)
            try:
                _redis.expire(SCAN_RUN_LOCK, SCAN_RUN_LOCK_TTL)
            except Exception:
                logger.debug("run_scan: failed to refresh scan run lock TTL", exc_info=True)

        for scan_root in filter_config.roots(fits_root):
            if is_cancel_requested_sync(_redis):
                break
            nf, cf, paths = scan_directory(
                scan_root,
                known_paths=known_paths,
                known_file_stats=known_file_stats,
                on_progress=_on_discovery_progress,
                is_cancelled=lambda: is_cancel_requested_sync(_redis),
                on_new_file=_queue_file,
                on_changed_file=_queue_changed_file,
                filter_config=filter_config,
                fits_root=fits_root,
                on_phd2_file=_queue_phd2_file,
            )
            new_files.extend(nf)
            changed_files.extend(cf)
            all_disk_paths.update(paths)

        if is_cancel_requested_sync(_redis):
            set_cancelled_sync(_redis)
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="scan", severity="info",
                    event_type="scan_stopped",
                    message=f"Scan stopped by user ({len(new_files)} files discovered before stop)",
                    details={"discovered": len(new_files)}, actor="system",
                )
            return {"status": "cancelled"}

        if changed_files:
            logger.info("Delta scan: %d changed files queued for re-ingest", len(changed_files))
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="scan", severity="info",
                    event_type="delta_scan",
                    message=f"Delta scan: {len(changed_files)} changed file{'s' if len(changed_files) != 1 else ''} detected and re-queued",
                    details={"changed_files": len(changed_files)}, actor="system",
                )

        # Detect and remove orphaned DB records (files deleted from disk).
        # The 50%-missing safety threshold, 500-row delete batching, and
        # activity events (orphan_cleanup / orphan_force_warning /
        # orphan_warning) live in cleanup_orphaned_images now; the module-level
        # names below are forwarded explicitly (rather than imported directly
        # in the service module) so tests that patch them on this module keep
        # working unchanged.
        cleanup_result = cleanup_orphaned_images(
            _sync_engine,
            _redis,
            known_paths,
            all_disk_paths,
            filter_config,
            fits_root,
            force_orphan_cleanup,
            session_factory=Session,
            activity_session_factory=_activity_session,
            emit_fn=_emit_activity_sync,
            prune_fn=prune_stale_panel_sessions,
        )
        removed = cleanup_result["removed"]

        total_queued = len(new_files) + len(changed_files)
        if not total_queued:
            # Zero the guide-log counters, publish this pass's candidate count
            # and flag the pass as queued BEFORE the scan is published as
            # complete. scan:state survives a
            # finished scan, so between set_idle_sync and this reset a poller
            # could read `state == "complete"` next to the previous run's
            # phd2_* totals and take them for this run's. The dispatch itself
            # still happens after the activity row exists, because it wants
            # that row as its parent.
            reset_phd2_counts_sync(_redis, len(phd2_paths))
            set_idle_sync(_redis)
            cataloged = len(known_paths) - removed
            msg = f"Scan complete: no new files found ({cataloged} already cataloged)"
            if removed:
                msg += f", {removed} deleted files purged from catalog"
            with _activity_session() as _db:
                scan_activity_id = _emit_activity_sync(
                    _db, redis=_redis, category="scan", severity="info",
                    event_type="scan_complete", message=msg,
                    details={"completed": 0, "failed": 0, "already_known": cataloged, "removed": removed},
                    actor="system",
                )
            generate_reference_thumbnails.apply_async(countdown=20, kwargs={"parent_activity_id": scan_activity_id})
            detect_duplicate_targets.apply_async(countdown=30, kwargs={"parent_activity_id": scan_activity_id})
            backfill_dark_hours.apply_async(countdown=45, kwargs={"parent_activity_id": scan_activity_id})
            _dispatch_phd2_scan(phd2_paths, scan_activity_id, force_orphan_cleanup)
            # Incremental fill for frames ingested by an earlier scan whose
            # guide logs only arrived later. The countdown clears the guide-log
            # pass above (dispatched at 50 s), which re-derives the nights it
            # writes; running before it would do the same work twice and the
            # second pass would find nothing.
            try:
                correlate_phd2_images.apply_async(
                    countdown=120,
                    kwargs={"parent_activity_id": scan_activity_id},
                )
            except Exception:
                logger.warning(
                    "run_scan: could not dispatch the guiding correlation pass",
                    exc_info=True,
                )
            # Scan over here: no ingest tasks were queued, so check_complete_sync
            # (which handles the same hand-off for the ingesting path) never
            # runs. A trigger that arrived during this walk gets its rescan.
            dispatch_pending_rescan_sync(_redis)
            return {"status": "complete", "new_files_queued": 0, "already_known": cataloged, "removed": removed, "phd2_found": len(phd2_paths)}

        # Transition to ingesting with final total - ingest tasks are already running
        set_ingesting_sync(_redis, total=total_queued, removed=removed, new_files=len(new_files), changed_files=len(changed_files))
        # Some tasks may have already completed during discovery, check now
        check_complete_sync(_redis)

        # Post-scan tasks (smart_rebuild, detect_mosaic, detect_duplicates, backfill_dark_hours,
        # generate_reference_thumbnails) are dispatched from check_complete_sync with parent_activity_id.

        # Dispatched from here rather than from check_complete_sync's post-scan
        # cascade because the candidate path list only exists in this scope;
        # the PHD2 pass is independent of image ingest and need not wait for it.
        _dispatch_phd2_scan(phd2_paths, force_orphan_cleanup=force_orphan_cleanup)

        _invalidate_stats_cache()

        return {
            "status": "ingesting",
            "new_files_queued": len(new_files),
            "changed_files_queued": len(changed_files),
            "already_known": len(known_paths),
            "removed": removed,
            "phd2_found": len(phd2_paths),
        }
    finally:
        _redis.delete(SCAN_RUN_LOCK)


@celery_app.task(name="app.worker.tasks.auto_scan_tick")
def auto_scan_tick():
    """Heartbeat task: check if an auto-scan is due and dispatch if so."""
    # Read auto-scan config from DB (migrated from Redis)
    with Session(_sync_engine) as db_session:
        row = db_session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        ).scalar_one_or_none()

    if row is None or not (row.general or {}).get("auto_scan_enabled", True):
        return

    # Gate auto-scan on first boot until the user has reviewed scan filters.
    # The onboarding banner lets them either configure rules or explicitly
    # accept defaults, which flips this flag. Manual scans remain unaffected.
    if not (row.general or {}).get("scan_filters_configured"):
        return

    interval_minutes = (row.general or {}).get("auto_scan_interval", 240)
    last_run_str = _redis.get("autoscan:last_run")
    now = time.time()

    if last_run_str:
        last_run = float(last_run_str)
        if now - last_run < interval_minutes * 60:
            return

    # Check if a scan is already running
    from app.services.scan_state import parse_snapshot, SCAN_KEY
    data = _redis.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    if snap.state in ("scanning", "ingesting"):
        return

    # Dispatch scan
    _redis.set("autoscan:last_run", str(now))
    logger.info("Auto-scan triggered (interval=%dm)", interval_minutes)
    include_cal = (row.general or {}).get("include_calibration", False)
    run_scan.delay(include_calibration=include_cal)


def _thumbnail_referenced(thumb_path_str: str) -> bool:
    """Return True if any Image row references this thumbnail file.

    Thin wrapper around app.services.orphan_cleanup.thumbnail_referenced,
    kept under this name (rather than calling the service directly at the
    _do_ingest call site) because tests patch `_thumbnail_referenced` on
    this module.
    """
    return _thumbnail_referenced_impl(thumb_path_str, _sync_engine)


def _do_ingest(fits_path: str, include_calibration: bool = True) -> dict:
    """Core ingest logic for a single FITS/XISF file.

    Shared by ingest_file (new files) and reingest_changed_file (delta rescan).
    Raises exceptions for the caller to handle retry/failure logic.

    1. Extract metadata from headers
    2. Generate stretched JPEG thumbnail
    3. Resolve target name via SIMBAD (with local cache)
    4. Insert database record
    """
    import hashlib

    path = Path(fits_path)

    # Validate path is within the configured FITS data directory
    fits_root = Path(settings.fits_data_path).resolve()
    try:
        path.resolve().relative_to(fits_root)
    except ValueError:
        raise ValueError(f"Path {fits_path} is outside configured FITS data directory")

    # Step 1: Extract metadata (dispatches by format)
    is_xisf = path.suffix.lower() == ".xisf"
    if is_xisf:
        meta = extract_xisf_metadata(path)
    else:
        # Read header once - pixel data is read separately (decimated)
        # only if a thumbnail is needed.
        header = fitsio.read_header(str(path), ext=0)
        meta = extract_metadata(path, header=header)

    image_type = (meta.get("image_type") or "").upper()
    is_calibration = image_type in CALIBRATION_FRAME_TYPES

    # Skip calibration frames if not requested (deferred from discovery phase
    # to avoid opening every file during the directory walk)
    if is_calibration and not include_calibration:
        increment_completed_sync(_redis)
        increment_skipped_calibration_sync(_redis)
        add_skipped_path_sync(_redis, str(path))
        return {"file": str(path), "status": "skipped_calibration"}

    # Step 2: Generate thumbnail (skip calibration frames)
    thumb_path = None
    if not is_calibration:
        path_hash = hashlib.md5(str(path).encode()).hexdigest()[:12]
        thumb_filename = f"{path.stem}_{path_hash}.jpg"
        thumb_path = Path(settings.thumbnails_path) / thumb_filename
        if is_xisf:
            generate_xisf_thumbnail(path, thumb_path, max_width=settings.thumbnail_max_width)
        else:
            generate_thumbnail(path, thumb_path, max_width=settings.thumbnail_max_width)

    # Step 3: Resolve target (sync wrapper for async SIMBAD call)
    # Skip SIMBAD for calibration frames - they're not astronomical targets
    target_id = None
    filename_candidate_name = None
    if not is_calibration:
        object_name = meta.get("object_name")
        if object_name:
            with Session(_sync_engine) as session:
                target_id = resolve_target(object_name, session, redis=_redis)
        else:
            # No OBJECT header -- try extracting target from filename
            from app.services.filename_parser import extract_target_from_filename
            filename_candidate_name = extract_target_from_filename(path)

    # Step 4: Insert into database
    # Capture file stat for delta rescans (detect changed files without re-reading headers)
    try:
        stat = path.stat()
        file_size = stat.st_size
        file_mtime = stat.st_mtime
    except OSError:
        file_size = None
        file_mtime = None

    # Compute session_date from capture_date + longitude
    raw_hdrs = meta.get("raw_headers", {})
    site_lon = extract_longitude(raw_hdrs)

    # Load imaging night setting (cached per-process with a short TTL so a 20k
    # file scan does not open 20k settings sessions).
    general = _get_cached_general_settings()

    effective_lon = site_lon if site_lon is not None else general.observer_longitude
    if general.use_imaging_night and effective_lon is None:
        global _imaging_night_fallback_warned
        if not _imaging_night_fallback_warned:
            # Warn once per worker process, not once per ingested image.
            warn_imaging_night_fallback(logger)
            _imaging_night_fallback_warned = True
    session_date_val = compute_session_date(
        meta.get("capture_date"),
        use_imaging_night=general.use_imaging_night,
        longitude=effective_lon,
    )

    # Step 4b: Parse panel membership (Phase 5). Only LIGHT frames with a
    # resolved target and a usable OBJECT string can carry a panel token;
    # calibration frames and unresolved targets are never assigned a panel.
    # Kept in the same transaction as the Image insert below so panel
    # membership is atomic with ingest, not a separate round trip.
    panel_label = None
    panel_id = None
    object_name_for_panel = meta.get("object_name")
    parse_panel = (
        image_type == "LIGHT" and target_id is not None and bool(object_name_for_panel)
    )

    try:
        with Session(_sync_engine) as session:
            if parse_panel:
                panel_label, panel_id = resolve_panel_membership(
                    session, target_id, object_name_for_panel, general.mosaic_keywords,
                )
            image = Image(
                file_path=meta["file_path"],
                file_name=meta["file_name"],
                file_size=file_size,
                file_mtime=file_mtime,
                capture_date=meta.get("capture_date"),
                session_date=session_date_val,
                thumbnail_path=str(thumb_path) if thumb_path else None,
                resolved_target_id=target_id,
                panel_label=panel_label,
                panel_id=panel_id,
                exposure_time=meta.get("exposure_time"),
                filter_used=meta.get("filter_used"),
                sensor_temp=meta.get("sensor_temp"),
                camera_gain=meta.get("camera_gain"),
                image_type=meta.get("image_type"),
                telescope=meta.get("telescope"),
                camera=meta.get("camera"),
                median_hfr=meta.get("median_hfr"),
                median_fwhm=meta.get("median_fwhm"),
                eccentricity=meta.get("eccentricity"),
                eccentricity_source=meta.get("eccentricity_source"),
                altitude_deg=meta.get("altitude_deg"),
                arcsec_per_pixel=meta.get("arcsec_per_pixel"),
                raw_headers=meta.get("raw_headers", {}),
                # CSV metrics (N.I.N.A. Session Metadata)
                hfr_stdev=meta.get("hfr_stdev"),
                fwhm=meta.get("fwhm"),
                detected_stars=meta.get("detected_stars"),
                guiding_rms_arcsec=meta.get("guiding_rms_arcsec"),
                guiding_rms_ra_arcsec=meta.get("guiding_rms_ra_arcsec"),
                guiding_rms_dec_arcsec=meta.get("guiding_rms_dec_arcsec"),
                guiding_rms_source=meta.get("guiding_rms_source"),
                adu_stdev=meta.get("adu_stdev"),
                adu_mean=meta.get("adu_mean"),
                adu_median=meta.get("adu_median"),
                adu_min=meta.get("adu_min"),
                adu_max=meta.get("adu_max"),
                focuser_position=meta.get("focuser_position"),
                focuser_temp=meta.get("focuser_temp"),
                rotator_position=meta.get("rotator_position"),
                pier_side=meta.get("pier_side"),
                airmass=meta.get("airmass"),
                ambient_temp=meta.get("ambient_temp"),
                dew_point=meta.get("dew_point"),
                humidity=meta.get("humidity"),
                pressure=meta.get("pressure"),
                wind_speed=meta.get("wind_speed"),
                wind_direction=meta.get("wind_direction"),
                wind_gust=meta.get("wind_gust"),
                cloud_cover=meta.get("cloud_cover"),
                sky_quality=meta.get("sky_quality"),
            )
            session.add(image)
            session.commit()
            # Capture the generated id while the instance is still bound to an
            # open session. After the `with` block closes the session, `image`
            # is detached and touching any attribute raises
            # DetachedInstanceError (accessing `image.id` here refreshes it).
            image_id = image.id
    except IntegrityError:
        # A row with this file_path already exists (UNIQUE constraint). The
        # thumbnail we just (re)generated has a deterministic, path-derived
        # filename, so it is the SAME file the pre-existing row's
        # thumbnail_path points at. Do NOT unlink it -- deleting it would
        # leave the surviving row pointing at a missing thumbnail (AUD-015).
        raise
    except Exception:
        # Genuinely orphaned insert (non-duplicate failure): clean up the
        # thumbnail we generated, but only if no existing row references it.
        if thumb_path and thumb_path.exists() and not _thumbnail_referenced(str(thumb_path)):
            thumb_path.unlink(missing_ok=True)
        raise

    # Step 5: Track filename candidate for images without OBJECT header
    if not is_calibration and not target_id and not meta.get("object_name"):
        try:
            with Session(_sync_engine) as session:
                import uuid
                from app.models.filename_candidate import FilenameCandidate
                from app.services.filename_resolver import resolve_filename_candidate as _resolve_fn
                from sqlalchemy import select as _sel

                extracted = filename_candidate_name

                # Look up any existing candidate (pending or dismissed) with same
                # extracted name. Dismissed means the user rejected this suggestion,
                # so we must not create a fresh pending row for it on re-ingest.
                existing = None
                is_dismissed = False
                if extracted:
                    rows = session.execute(
                        _sel(FilenameCandidate).where(
                            FilenameCandidate.extracted_name == extracted,
                            FilenameCandidate.status.in_(["pending", "dismissed"]),
                        )
                    ).scalars().all()
                    is_dismissed = any(r.status == "dismissed" for r in rows)
                    existing = next((r for r in rows if r.status == "pending"), None)

                if is_dismissed:
                    pass
                elif existing:
                    existing.image_ids = list(existing.image_ids or []) + [image_id]
                    existing.file_paths = list(existing.file_paths or []) + [str(path)]
                    existing.file_count = len(existing.image_ids)
                else:
                    # Resolve the candidate
                    if extracted:
                        resolution = _resolve_fn(extracted, session, redis=_redis)
                    else:
                        resolution = {"method": "none", "confidence": 0.0, "suggested_target_id": None}

                    suggested_id = resolution.get("suggested_target_id")
                    session.add(FilenameCandidate(
                        extracted_name=extracted,
                        suggested_target_id=uuid.UUID(suggested_id) if suggested_id else None,
                        method=resolution["method"],
                        confidence=resolution["confidence"],
                        status="pending",
                        file_count=1,
                        file_paths=[str(path)],
                        image_ids=[image_id],
                    ))
                session.commit()
        except Exception:
            logger.warning("Failed to create filename candidate for %s", path.name, exc_info=True)
            try:
                with _activity_session() as _db:
                    _emit_activity_sync(
                        _db, redis=_redis, category="scan", severity="warning",
                        event_type="filename_candidate_failed",
                        message=f"Filename candidate resolution failed for {path.name}",
                        details={"path": str(path)}, actor="system",
                    )
            except Exception:
                logger.debug(
                    "Failed to emit filename_candidate_failed activity for %s",
                    path.name, exc_info=True,
                )

    logger.info("Ingested: %s (target=%s)", path.name, target_id)
    increment_completed_sync(_redis)
    if meta.get("detected_stars") is not None:
        increment_csv_enriched_sync(_redis)
    return {"file": str(path), "status": "ok"}


def _is_unrecoverable(exc: Exception) -> bool:
    # ValueError from our own path validation or from FITS/XISF parsing
    if isinstance(exc, ValueError):
        return True
    # FileNotFoundError is always unrecoverable (file was deleted)
    if isinstance(exc, FileNotFoundError):
        return True
    # PermissionError won't resolve on retry
    if isinstance(exc, PermissionError):
        return True
    # Other OSError subtypes - check for known unrecoverable messages.
    # FITSIO status 107 is a read past the end of the file: the file is
    # truncated, so every retry re-reads the same short bytes and fails the
    # same way. Retrying it only delays the scan and the failure report.
    if isinstance(exc, OSError):
        msg = str(exc)
        return any(s in msg for s in (
            "SIMPLE card",
            "not a valid FITS",
            "status = 107",
            "move past end of file",
            "could not interpret primary array header",
        ))
    return False


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="app.worker.tasks.ingest_file")
def ingest_file(self, fits_path: str, include_calibration: bool = True) -> dict:
    """Celery task: ingest a new FITS/XISF file."""
    path = Path(fits_path)

    if is_cancel_requested_sync(_redis):
        increment_failed_sync(_redis, file_path=fits_path, error="Scan cancelled")
        return {"status": "cancelled", "file": fits_path}

    logger.info("Ingesting: %s", path.name)

    try:
        return _do_ingest(fits_path, include_calibration=include_calibration)

    except IntegrityError:
        logger.info("Already ingested (duplicate): %s", path.name)
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "duplicate"}

    except Exception as exc:
        logger.error("Failed to ingest %s: %s", path, exc)
        if _is_unrecoverable(exc) or self.request.retries >= self.max_retries:
            increment_failed_sync(_redis, file_path=str(path), error=str(exc))
            return {"file": str(path), "status": "failed", "error": str(exc)}
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="app.worker.tasks.reingest_changed_file")
def reingest_changed_file(self, fits_path: str, include_calibration: bool = True) -> dict:
    """Re-ingest a file that changed on disk (delta rescan).

    Deletes the existing DB record + thumbnail, then runs the full ingest pipeline.
    """
    path = Path(fits_path)
    logger.info("Re-ingesting changed file: %s", path.name)

    try:
        # AUD-029: validate the file is readable BEFORE deleting the existing
        # catalog row. A file that is mid-write/truncated at the moment the
        # size-change was detected raises here (ValueError/OSError). If we
        # deleted first and then failed, an unrecoverable error would leave the
        # frame with no catalog row until a later scan re-detected it. Reading
        # the header/metadata is the failable I/O, so do it up front and bail
        # without touching the DB or thumbnail when it fails.
        if path.suffix.lower() == ".xisf":
            extract_xisf_metadata(path)
        else:
            fitsio.read_header(str(path), ext=0)

        # File is intact - now safe to delete the old record + thumbnail and
        # re-run the full ingest pipeline.
        with Session(_sync_engine) as session:
            existing = session.execute(
                select(Image).where(Image.file_path == fits_path)
            ).scalar_one_or_none()
            if existing:
                if existing.thumbnail_path:
                    try:
                        Path(existing.thumbnail_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                session.delete(existing)
                session.commit()

        return _do_ingest(fits_path, include_calibration=include_calibration)

    except Exception as exc:
        logger.error("Failed to re-ingest %s: %s", path, exc)
        if _is_unrecoverable(exc) or self.request.retries >= self.max_retries:
            increment_failed_sync(_redis, file_path=fits_path, error=str(exc))
            return {"file": fits_path, "status": "failed", "error": str(exc)}
        raise self.retry(exc=exc)
