import logging
import time
from datetime import datetime
from pathlib import Path

import fitsio
from sqlalchemy import create_engine, func, select, text, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Image, Target
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.csv_metadata import parse_image_metadata_csv, parse_weather_csv
from app.services.scanner import extract_metadata, CALIBRATION_FRAME_TYPES
from app.services.simbad import (
    normalize_object_name, resolve_target_name_cached,
    curate_simbad_result, get_cached_simbad,
)
from app.services.target_resolver import resolve_target, normalize_sql_expr
from app.services.thumbnail import generate_thumbnail
from app.services.xisf_parser import extract_xisf_metadata, generate_xisf_thumbnail
from app.services.session_date import compute_session_date, extract_longitude
from app.schemas.settings import GeneralSettings
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Celery uses sync - create a sync engine for the worker
# Replace asyncpg with psycopg2 for sync operations
_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=1800)

from app.config import get_sync_redis
from app.services.scan_state import (
    increment_completed_sync, increment_failed_sync, increment_csv_enriched_sync,
    increment_skipped_calibration_sync,
    start_scanning_sync, set_ingesting_sync, set_idle_sync,
    set_rebuild_running_sync, set_rebuild_progress_sync, set_rebuild_complete_sync,
    set_rebuild_cancelled_sync,
    set_discovered_sync, is_cancel_requested_sync, clear_cancel_sync, set_cancelled_sync,
    check_complete_sync,
    add_skipped_path_sync, get_skipped_paths_sync, clear_skipped_paths_sync,
)
from app.services.activity import emit_sync as _emit_activity_sync


def _activity_session():
    """Return a context-managed sync Session for activity writes in Celery tasks."""
    return Session(_sync_engine)


_redis = get_sync_redis()


def _invalidate_stats_cache():
    """Delete the stats cache key from Redis so the next stats request is fresh."""
    try:
        _redis.delete("galactilog:stats:cache", "galactilog:fits_keys")
    except Exception:
        pass


@celery_app.task(bind=True)
def run_scan(self, include_calibration: bool = True) -> dict:
    """Scan the FITS directory and queue ingest tasks for new files.

    Runs entirely inside Celery so the HTTP endpoint returns immediately.
    """
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

    # Include previously skipped calibration paths so they aren't re-queued
    if not include_calibration:
        known_paths |= get_skipped_paths_sync(_redis)
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
    def _queue_file(path: Path) -> None:
        ingest_file.delay(str(path), include_calibration=include_calibration)

    def _queue_changed_file(path: Path) -> None:
        """Re-ingest a known file whose size or mtime changed on disk."""
        reingest_changed_file.delay(str(path), include_calibration=include_calibration)

    new_files: list[Path] = []
    changed_files: list[Path] = []
    all_disk_paths: set[str] = set()

    for scan_root in filter_config.roots(fits_root):
        if is_cancel_requested_sync(_redis):
            break
        nf, cf, paths = scan_directory(
            scan_root,
            known_paths=known_paths,
            known_file_stats=known_file_stats,
            on_progress=lambda count: set_discovered_sync(_redis, count),
            is_cancelled=lambda: is_cancel_requested_sync(_redis),
            on_new_file=_queue_file,
            on_changed_file=_queue_changed_file,
            filter_config=filter_config,
            fits_root=fits_root,
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
    # CRITICAL: only consider rows the walker would have actually visited
    # under the current filter config. When include_paths or excludes narrow
    # the scan, out-of-scope rows appear "missing from disk" even though the
    # walker never looked for them. Those must NOT be treated as orphans.
    in_scope_known_paths = {
        p for p in known_paths
        if p and filter_config.should_include_file(Path(p), fits_root)
    }
    orphaned_paths = in_scope_known_paths - all_disk_paths
    removed = 0
    if orphaned_paths and len(orphaned_paths) < max(1, len(in_scope_known_paths)) * 0.5:
        # Safety: only clean up if less than 50% of files appear missing
        # (protects against unmounted shares / unreachable storage)
        with Session(_sync_engine) as session:
            for batch_start in range(0, len(orphaned_paths), 500):
                batch = list(orphaned_paths)[batch_start:batch_start + 500]
                rows = session.execute(
                    select(Image.id, Image.thumbnail_path).where(
                        Image.file_path.in_(batch)
                    )
                ).all()
                for img_id, thumb_path in rows:
                    if thumb_path:
                        try:
                            Path(thumb_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    session.execute(
                        text("DELETE FROM images WHERE id = :id"),
                        {"id": img_id},
                    )
                    removed += 1
                session.commit()
        if removed:
            logger.info("Removed %d orphaned image records (files deleted from disk)", removed)
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="scan", severity="info",
                    event_type="orphan_cleanup",
                    message=f"Removed {removed} deleted file{'s' if removed != 1 else ''} from catalog",
                    details={"removed": removed}, actor="system",
                )
    elif orphaned_paths:
        logger.warning(
            "Skipped orphan cleanup: %d of %d in-scope files missing (>50%%) - "
            "possible unmounted share or unreachable storage",
            len(orphaned_paths), len(in_scope_known_paths),
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="scan", severity="warning",
                event_type="orphan_warning",
                message=f"Orphan cleanup skipped: {len(orphaned_paths)} of {len(in_scope_known_paths)} in-scope files missing (>50%) - possible unmounted share",
                details={"missing": len(orphaned_paths), "total_known": len(in_scope_known_paths)},
                actor="system",
            )

    total_queued = len(new_files) + len(changed_files)
    if not total_queued:
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
        return {"status": "complete", "new_files_queued": 0, "already_known": cataloged, "removed": removed}

    # Transition to ingesting with final total - ingest tasks are already running
    set_ingesting_sync(_redis, total=total_queued, removed=removed, new_files=len(new_files), changed_files=len(changed_files))
    # Some tasks may have already completed during discovery, check now
    check_complete_sync(_redis)

    # Post-scan tasks (smart_rebuild, detect_mosaic, detect_duplicates, backfill_dark_hours,
    # generate_reference_thumbnails) are dispatched from check_complete_sync with parent_activity_id.
    _invalidate_stats_cache()

    return {
        "status": "ingesting",
        "new_files_queued": len(new_files),
        "changed_files_queued": len(changed_files),
        "already_known": len(known_paths),
        "removed": removed,
    }


@celery_app.task
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

    # Load imaging night setting (cached per-process via module-level settings row)
    with Session(_sync_engine) as settings_session:
        settings_row = settings_session.get(UserSettings, SETTINGS_ROW_ID)
        general = GeneralSettings(**(settings_row.general if settings_row and settings_row.general else {}))

    effective_lon = site_lon if site_lon is not None else general.observer_longitude
    session_date_val = compute_session_date(
        meta.get("capture_date"),
        use_imaging_night=general.use_imaging_night,
        longitude=effective_lon,
    )

    try:
        with Session(_sync_engine) as session:
            image = Image(
                file_path=meta["file_path"],
                file_name=meta["file_name"],
                file_size=file_size,
                file_mtime=file_mtime,
                capture_date=meta.get("capture_date"),
                session_date=session_date_val,
                thumbnail_path=str(thumb_path) if thumb_path else None,
                resolved_target_id=target_id,
                exposure_time=meta.get("exposure_time"),
                filter_used=meta.get("filter_used"),
                sensor_temp=meta.get("sensor_temp"),
                camera_gain=meta.get("camera_gain"),
                image_type=meta.get("image_type"),
                telescope=meta.get("telescope"),
                camera=meta.get("camera"),
                median_hfr=meta.get("median_hfr"),
                eccentricity=meta.get("eccentricity"),
                raw_headers=meta.get("raw_headers", {}),
                # CSV metrics (N.I.N.A. Session Metadata)
                hfr_stdev=meta.get("hfr_stdev"),
                fwhm=meta.get("fwhm"),
                detected_stars=meta.get("detected_stars"),
                guiding_rms_arcsec=meta.get("guiding_rms_arcsec"),
                guiding_rms_ra_arcsec=meta.get("guiding_rms_ra_arcsec"),
                guiding_rms_dec_arcsec=meta.get("guiding_rms_dec_arcsec"),
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
    except Exception:
        # Clean up orphaned thumbnail if DB insert failed
        if thumb_path and thumb_path.exists():
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
                    existing.image_ids = list(existing.image_ids or []) + [image.id]
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
                        image_ids=[image.id],
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
                pass

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
    # Other OSError subtypes - check for known unrecoverable messages
    if isinstance(exc, OSError):
        msg = str(exc)
        return any(s in msg for s in ("SIMPLE card", "not a valid FITS"))
    return False


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def reingest_changed_file(self, fits_path: str, include_calibration: bool = True) -> dict:
    """Re-ingest a file that changed on disk (delta rescan).

    Deletes the existing DB record + thumbnail, then runs the full ingest pipeline.
    """
    path = Path(fits_path)
    logger.info("Re-ingesting changed file: %s", path.name)

    try:
        # Delete existing record
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


@celery_app.task(name="purge_and_regenerate_thumbnails")
def purge_and_regenerate_thumbnails() -> dict:
    """Delete every thumbnail file on disk, then queue regeneration for all images.

    Logs start, per-batch progress, and completion of the delete phase to the
    activity log. The final "scan complete" activity is emitted by the usual
    check_complete_sync flow once all regenerate_thumbnail tasks finish.
    """
    with Session(_sync_engine) as session:
        rows = session.execute(
            select(Image.id, Image.file_path, Image.thumbnail_path)
        ).all()

    total = len(rows)
    if not total:
        set_idle_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="thumb_purge_complete",
                message="Regen thumbnails: no images to process",
                details={"deleted": 0, "queued": 0}, actor="system",
            )
        return {"status": "complete", "deleted": 0, "queued": 0}

    if is_cancel_requested_sync(_redis):
        set_cancelled_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message="Thumbnail purge cancelled before start",
                details={"deleted": 0, "queued": 0, "total": total}, actor="system",
            )
        return {"status": "cancelled", "deleted": 0, "queued": 0}

    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="thumb_purge_start",
            message=f"Deleting existing thumbnails for {total} image{'s' if total != 1 else ''}...",
            details={"total": total}, actor="system",
        )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _unlink_one(thumb_path: str) -> str:
        """Return 'deleted', 'missing', or 'error'. Network-IO bound."""
        try:
            Path(thumb_path).unlink()
            return "deleted"
        except FileNotFoundError:
            return "missing"
        except OSError as exc:
            logger.warning("Failed to delete thumbnail %s: %s", thumb_path, exc)
            return "error"

    paths = [tp for (_id, _fp, tp) in rows if tp]
    deleted = 0
    missing = 0
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = [pool.submit(_unlink_one, tp) for tp in paths]
        for fut in as_completed(futures):
            result = fut.result()
            if result == "deleted":
                deleted += 1
            elif result == "missing":
                missing += 1

    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="thumb_purge_complete",
            message=f"Deleted {deleted} thumbnail{'s' if deleted != 1 else ''}"
                    + (f" ({missing} already missing)" if missing else "")
                    + f", queueing {total} for regeneration...",
            details={"deleted": deleted, "missing": missing, "queued": total},
            actor="system",
        )

    if is_cancel_requested_sync(_redis):
        set_cancelled_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message=f"Thumbnail purge cancelled after deleting {deleted} files; regen skipped",
                details={"deleted": deleted, "missing": missing, "queued": 0, "total": total},
                actor="system",
            )
        return {"status": "cancelled", "deleted": deleted, "missing": missing, "queued": 0}

    set_ingesting_sync(_redis, total=total)

    queued = 0
    for image_id, file_path, thumb_path in rows:
        if file_path and thumb_path:
            regenerate_thumbnail.delay(str(image_id), file_path, thumb_path)
            queued += 1

    return {"status": "ingesting", "deleted": deleted, "missing": missing, "queued": queued}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def regenerate_thumbnail(self, image_id: str, fits_path: str, thumb_path: str) -> dict:
    """Regenerate a single thumbnail using the current stretch algorithm."""
    path = Path(fits_path)
    output = Path(thumb_path)

    # Drain queued tasks on cancel so scan state transitions to complete via check_complete_sync.
    if is_cancel_requested_sync(_redis):
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "cancelled"}

    logger.info("Regenerating thumbnail: %s", path.name)

    try:
        if path.suffix.lower() == ".xisf":
            generate_xisf_thumbnail(path, output, max_width=settings.thumbnail_max_width)
        else:
            generate_thumbnail(path, output, max_width=settings.thumbnail_max_width)
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "ok"}
    except Exception as exc:
        logger.error("Failed to regenerate thumbnail for %s: %s", path, exc)
        if self.request.retries >= self.max_retries:
            increment_failed_sync(_redis, file_path=str(path), error=str(exc))
            return {"file": str(path), "status": "failed", "error": str(exc)}
        raise self.retry(exc=exc)


@celery_app.task(name="detect_duplicate_targets")
def detect_duplicate_targets(parent_activity_id: int | None = None):
    """Detect potential duplicate targets by comparing unresolved names against resolved targets.

    Strategy:
    1. Try SIMBAD resolution to find the canonical catalog ID, then match against existing targets.
    2. Fall back to trigram similarity if SIMBAD doesn't resolve or match.
    """
    from sqlalchemy import text as sa_text, select as sa_select, func as sa_func
    from app.models.target import Target
    from app.models.image import Image
    from app.models.merge_candidate import MergeCandidate
    from app.services.simbad import resolve_target_name_cached, normalize_object_name

    with Session(_sync_engine) as db:
        # Find distinct unresolved OBJECT names with image counts
        unresolved_query = (
            sa_select(
                Image.raw_headers["OBJECT"].astext.label("object_name"),
                sa_func.count(Image.id).label("img_count"),
            )
            .where(
                Image.resolved_target_id.is_(None),
                Image.image_type == "LIGHT",
                Image.raw_headers["OBJECT"].astext.isnot(None),
            )
            .group_by(Image.raw_headers["OBJECT"].astext)
        )
        unresolved = db.execute(unresolved_query).all()

        # Get existing candidates to avoid duplicates. Include "dismissed" so
        # suggestions the user explicitly rejected don't come back on re-runs
        # triggered by scans, manual matches, or smart rebuilds.
        existing = db.execute(
            sa_select(MergeCandidate.source_name).where(
                MergeCandidate.status.in_(["pending", "accepted", "dismissed"])
            )
        )
        existing_names = {row[0] for row in existing.all()}

        candidates_found = 0
        orphan_count = 0

        for obj_name, img_count in unresolved:
            if not obj_name or obj_name in existing_names:
                continue

            matched = False

            # Strategy 1: SIMBAD resolution - resolve the name and match against existing targets
            simbad_result = resolve_target_name_cached(obj_name, db)
            if simbad_result:
                catalog_id = simbad_result.get("catalog_id")
                simbad_aliases = [normalize_object_name(a) for a in simbad_result.get("aliases", [])]
                if catalog_id:
                    simbad_aliases.append(normalize_object_name(catalog_id))

                # Check if any existing target shares the same catalog_id or aliases
                if simbad_aliases:
                    alias_match_query = sa_text("""
                        SELECT t.id, t.primary_name
                        FROM targets t
                        WHERE t.merged_into_id IS NULL
                          AND (
                            upper(t.catalog_id) = ANY(:aliases)
                            OR EXISTS (
                              SELECT 1 FROM unnest(t.aliases) a
                              WHERE upper(a) = ANY(:aliases)
                            )
                          )
                        LIMIT 1
                    """)
                    result = db.execute(alias_match_query, {"aliases": simbad_aliases}).first()
                    if result:
                        target_id, target_name = result
                        db.add(MergeCandidate(
                            source_name=obj_name,
                            source_image_count=img_count,
                            suggested_target_id=target_id,
                            similarity_score=1.0,
                            method="simbad",
                            reason_text=f'SIMBAD resolves "{obj_name}" to the same object as "{target_name}"',
                        ))
                        candidates_found += 1
                        matched = True

            if matched:
                continue

            # SIMBAD resolved the name but no existing target matched - create the target
            # and resolve images directly instead of suggesting a wrong trigram match.
            if simbad_result:
                logger.info("detect_duplicates: '%s' resolved by SIMBAD to '%s' - creating target and resolving images",
                            obj_name, simbad_result.get("primary_name"))
                target_id = resolve_target(obj_name, db, redis=_redis)
                if target_id:
                    from sqlalchemy import update as sa_update
                    db.execute(
                        sa_update(Image)
                        .where(
                            Image.raw_headers["OBJECT"].astext == obj_name,
                            Image.resolved_target_id.is_(None),
                        )
                        .values(resolved_target_id=target_id)
                    )
                    db.commit()
                    logger.info("detect_duplicates: resolved %d images for '%s' to target %s",
                                img_count, obj_name, target_id)
                continue

            # Strategy 2: Trigram similarity fallback (only for names SIMBAD can't resolve)
            trgm_query = sa_text("""
                SELECT t.id, t.primary_name,
                       GREATEST(
                           similarity(t.primary_name, :name),
                           COALESCE((SELECT MAX(similarity(a, :name)) FROM unnest(t.aliases) a), 0)
                       ) AS score
                FROM targets t
                WHERE t.merged_into_id IS NULL
                  AND GREATEST(
                      similarity(t.primary_name, :name),
                      COALESCE((SELECT MAX(similarity(a, :name)) FROM unnest(t.aliases) a), 0)
                  ) > 0.4
                ORDER BY score DESC
                LIMIT 1
            """)
            result = db.execute(trgm_query, {"name": obj_name}).first()

            if result:
                target_id, target_name, score = result
                db.add(MergeCandidate(
                    source_name=obj_name,
                    source_image_count=img_count,
                    suggested_target_id=target_id,
                    similarity_score=float(score),
                    method="trigram",
                    reason_text=f'Name is {int(float(score) * 100)}% similar to "{target_name}"',
                ))
                candidates_found += 1
            else:
                db.add(MergeCandidate(
                    source_name=obj_name,
                    source_image_count=img_count,
                    suggested_target_id=None,
                    similarity_score=0.0,
                    method="orphan",
                    status="pending",
                    reason_text="No match found in SIMBAD or existing targets",
                ))
                candidates_found += 1
                orphan_count += 1

        db.commit()

        # --- Pass 2: Detect active targets sharing the same normalized name or overlapping aliases ---
        # Re-fetch existing candidate names after the commit above so we skip
        # anything just created in Pass 1.
        existing_pass2 = db.execute(
            sa_select(MergeCandidate.source_name).where(
                MergeCandidate.status.in_(["pending", "accepted", "dismissed"])
            )
        )
        existing_names_p2 = {row[0] for row in existing_pass2.all()}

        # Load all active (non-merged) targets with their image counts
        active_targets_query = sa_text("""
            SELECT t.id, t.primary_name, t.aliases,
                   (SELECT COUNT(*) FROM images i
                    WHERE i.resolved_target_id = t.id) AS img_count
            FROM targets t
            WHERE t.merged_into_id IS NULL
        """)
        active_rows = db.execute(active_targets_query).all()

        # Build a mapping from each normalized name to the list of targets that use it
        # (either as primary_name or as an alias)
        from collections import defaultdict
        name_to_targets: dict[str, list[tuple]] = defaultdict(list)
        for row in active_rows:
            tid, pname, aliases, img_count = row
            norm_primary = normalize_object_name(pname)
            name_to_targets[norm_primary].append((tid, pname, img_count))
            if aliases:
                for alias in aliases:
                    norm_alias = normalize_object_name(alias)
                    name_to_targets[norm_alias].append((tid, pname, img_count))

        # Find groups of targets that share any normalized name.
        # Use union-find to merge overlapping groups.

        # Map target id to its info
        target_info = {row[0]: (row[1], row[3]) for row in active_rows}  # id -> (primary_name, img_count)

        # For each normalized name that maps to multiple distinct targets, union them
        visited_targets: dict = {}  # target_id -> group leader id

        def find_leader(tid):
            while visited_targets.get(tid, tid) != tid:
                visited_targets[tid] = visited_targets.get(visited_targets[tid], visited_targets[tid])
                tid = visited_targets[tid]
            return tid

        def union(tid1, tid2):
            l1 = find_leader(tid1)
            l2 = find_leader(tid2)
            if l1 != l2:
                visited_targets[l2] = l1

        # Also track a representative shared name for each group leader
        group_shared_name: dict = {}  # leader_id -> norm_name that triggered the union

        for norm_name, target_list in name_to_targets.items():
            # Deduplicate target ids within this name
            unique_ids = list({t[0] for t in target_list})
            if len(unique_ids) < 2:
                continue
            # Union all targets sharing this name
            for i in range(1, len(unique_ids)):
                union(unique_ids[0], unique_ids[i])
            # Record a shared name for this group (first one encountered wins)
            leader_after = find_leader(unique_ids[0])
            if leader_after not in group_shared_name:
                group_shared_name[leader_after] = norm_name

        # Collect groups
        groups: dict[str, list] = defaultdict(list)
        for tid in target_info:
            leader = find_leader(tid)
            if leader != tid or visited_targets.get(tid) is not None:
                groups[find_leader(tid)].append(tid)

        # Only keep groups with 2+ members
        dup_candidates_found = 0
        for leader, members in groups.items():
            if len(members) < 2:
                continue

            # Pick the target with the most images as the suggested winner
            members_with_info = [(tid, *target_info[tid]) for tid in members]
            members_with_info.sort(key=lambda x: x[2], reverse=True)  # sort by img_count desc
            winner_id = members_with_info[0][0]
            winner_name = members_with_info[0][1]
            shared_name = group_shared_name.get(leader, "")

            for tid, pname, img_count in members_with_info[1:]:
                if pname in existing_names_p2:
                    continue
                db.add(MergeCandidate(
                    source_name=pname,
                    source_image_count=img_count,
                    suggested_target_id=winner_id,
                    similarity_score=1.0,
                    method="duplicate",
                    status="pending",
                    reason_text=f'Shares alias "{shared_name}" with "{winner_name}"',
                ))
                existing_names_p2.add(pname)
                dup_candidates_found += 1
                candidates_found += 1

        if dup_candidates_found > 0:
            db.commit()
            logger.info("detect_duplicates: found %d duplicate-name candidates", dup_candidates_found)

    # Update scan summary in Redis with duplicates_found and unresolved_names counts
    try:
        import json as _json
        raw = _redis.get("galactilog:scan_summary")
        if raw:
            _summary = _json.loads(raw)
            _summary["duplicates_found"] = candidates_found
            _summary["unresolved_names"] = orphan_count
            _redis.set("galactilog:scan_summary", _json.dumps(_summary))
    except Exception:
        logger.warning("detect_duplicate_targets: failed to update scan_summary in Redis")

    return {"candidates_found": candidates_found}


@celery_app.task(bind=True)
def rebuild_targets(self) -> dict:
    """Full target database rebuild: delete all targets, re-resolve from FITS headers.

    1. Clear resolved_target_id on all images
    2. Delete all targets and merge candidates
    3. Clear negative cache
    4. Get distinct OBJECT names from LIGHT frames
    5. Re-resolve each through SIMBAD (using resolve_target)
    6. Re-link images to new targets
    """
    logger.info("rebuild_targets: starting full rebuild")
    # Clear a sticky cancel flag from a prior run so this run isn't killed immediately.
    clear_cancel_sync(_redis)
    set_rebuild_running_sync(_redis, "full", "Clearing existing targets...")

    # Phase 1: Clear everything
    with Session(_sync_engine) as session:
        session.execute(text("UPDATE images SET resolved_target_id = NULL"))
        session.execute(text("DELETE FROM merge_candidates"))
        session.execute(text("DELETE FROM targets"))
        session.commit()
    logger.info("rebuild_targets: cleared all targets and links")

    _redis.delete("target_resolver:negative")

    # Phase 2: Get distinct OBJECT names from LIGHT frames
    with Session(_sync_engine) as session:
        result = session.execute(text("""
            SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
            FROM images
            WHERE image_type = 'LIGHT'
              AND raw_headers->>'OBJECT' IS NOT NULL
              AND raw_headers->>'OBJECT' != ''
            GROUP BY raw_headers->>'OBJECT'
            ORDER BY cnt DESC
        """))
        object_names = result.all()

    total = len(object_names)
    logger.info("rebuild_targets: found %d unique OBJECT names", total)
    set_rebuild_progress_sync(_redis, f"Resolving 0/{total} object names...")

    resolved = 0
    failed = 0

    # Phase 3: Resolve each and link images
    for i, (obj_name, img_count) in enumerate(object_names):
        if is_cancel_requested_sync(_redis):
            details = {"resolved": resolved, "failed": failed, "total": total, "processed": i}
            set_rebuild_cancelled_sync(
                _redis,
                f"Cancelled after {i}/{total} names ({resolved} resolved, {failed} failed)",
                details,
            )
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="rebuild", severity="info",
                    event_type="rebuild_cancelled",
                    message=f"Full Rebuild cancelled after {i}/{total} names",
                    details=details, actor="system",
                )
            logger.info("rebuild_targets: cancelled after %d/%d", i, total)
            return {"status": "cancelled", **details}

        with Session(_sync_engine) as session:
            target_id = resolve_target(obj_name, session, redis=_redis)

        if target_id:
            with Session(_sync_engine) as session:
                session.execute(text("""
                    UPDATE images
                    SET resolved_target_id = :tid
                    WHERE resolved_target_id IS NULL
                      AND raw_headers->>'OBJECT' = :obj_name
                """), {"tid": target_id, "obj_name": obj_name})
                session.commit()
            resolved += 1
            logger.info("rebuild_targets: %s -> %s (%d images)", obj_name, target_id, img_count)
        else:
            failed += 1
            logger.info("rebuild_targets: FAILED %s (%d images)", obj_name, img_count)

        if (i + 1) % 5 == 0 or i + 1 == total:
            set_rebuild_progress_sync(_redis, f"Resolving {i + 1}/{total} object names...")

        time.sleep(0.3)  # Rate limit SIMBAD

    # Phase 4: Queue post-rebuild tasks
    detect_duplicate_targets.apply_async(countdown=10)
    detect_mosaic_panels_task.apply_async(countdown=20)

    details = {"resolved": resolved, "failed": failed, "total": total}
    set_rebuild_complete_sync(
        _redis,
        f"Resolved {resolved} targets, {failed} failed out of {total} object names",
        details,
    )
    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="rebuild", severity="info",
            event_type="rebuild_complete",
            message=f"Full Rebuild: {resolved} resolved, {failed} failed out of {total} names",
            details={"resolved": resolved, "failed": failed, "total": total},
            actor="system",
        )
    if failed > 0:
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="enrichment", severity="warning",
                event_type="enrichment_query_failed",
                message=f"Full Rebuild: enrichment failed for {failed} of {total} object names",
                details={"failed_targets": failed, "total": total}, actor="system",
            )
    logger.info("rebuild_targets: done - resolved=%d, failed=%d", resolved, failed)
    return {"status": "complete", **details}


@celery_app.task(bind=True)
def retry_unresolved(self) -> dict:
    """Clear SIMBAD negative cache and SESAME cache, then re-resolve unresolved targets.

    Unlike Full Rebuild, this only touches unresolved images - existing targets are untouched.
    Useful after adding SESAME fallback or when upstream resolvers have new data.
    """
    logger.info("retry_unresolved: starting")
    clear_cancel_sync(_redis)
    set_rebuild_running_sync(_redis, "retry", "Clearing caches...")

    # Phase 1: Clear negative caches so names get a fresh shot
    with Session(_sync_engine) as session:
        session.execute(text("DELETE FROM simbad_cache WHERE main_id IS NULL"))
        session.execute(text("DELETE FROM sesame_cache"))
        session.commit()
    _redis.delete("target_resolver:negative")
    logger.info("retry_unresolved: cleared SIMBAD negatives and SESAME cache")

    # Phase 2: Get distinct OBJECT names from unresolved LIGHT frames
    with Session(_sync_engine) as session:
        result = session.execute(text("""
            SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
            FROM images
            WHERE image_type = 'LIGHT'
              AND resolved_target_id IS NULL
              AND raw_headers->>'OBJECT' IS NOT NULL
              AND raw_headers->>'OBJECT' != ''
            GROUP BY raw_headers->>'OBJECT'
            ORDER BY cnt DESC
        """))
        object_names = result.all()

    total = len(object_names)
    logger.info("retry_unresolved: found %d unresolved object names", total)
    set_rebuild_progress_sync(_redis, f"Retrying 0/{total} unresolved names...")

    resolved = 0
    failed = 0

    # Phase 3: Resolve each and link images
    for i, (obj_name, img_count) in enumerate(object_names):
        if is_cancel_requested_sync(_redis):
            details = {"resolved": resolved, "failed": failed, "total": total, "processed": i}
            set_rebuild_cancelled_sync(
                _redis,
                f"Cancelled after {i}/{total} names ({resolved} resolved, {failed} still unresolved)",
                details,
            )
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="rebuild", severity="info",
                    event_type="rebuild_cancelled",
                    message=f"Retry Unresolved cancelled after {i}/{total} names",
                    details=details, actor="system",
                )
            logger.info("retry_unresolved: cancelled after %d/%d", i, total)
            return {"status": "cancelled", **details}

        with Session(_sync_engine) as session:
            target_id = resolve_target(obj_name, session, redis=_redis)

        if target_id:
            with Session(_sync_engine) as session:
                session.execute(text("""
                    UPDATE images
                    SET resolved_target_id = :tid
                    WHERE resolved_target_id IS NULL
                      AND raw_headers->>'OBJECT' = :obj_name
                """), {"tid": target_id, "obj_name": obj_name})
                session.commit()
            resolved += 1
            logger.info("retry_unresolved: %s -> %s (%d images)", obj_name, target_id, img_count)
        else:
            failed += 1

        if (i + 1) % 5 == 0 or i + 1 == total:
            set_rebuild_progress_sync(_redis, f"Retrying {i + 1}/{total} unresolved names...")

        time.sleep(0.3)  # Rate limit external services

    details = {"resolved": resolved, "failed": failed, "total": total}
    set_rebuild_complete_sync(
        _redis,
        f"Retry: {resolved} resolved, {failed} still unresolved out of {total} names",
        details,
    )
    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="rebuild", severity="info",
            event_type="rebuild_complete",
            message=f"Retry Unresolved: {resolved} resolved, {failed} still unresolved out of {total} names",
            details=details, actor="system",
        )
    if failed > 0:
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="enrichment", severity="warning",
                event_type="enrichment_query_failed",
                message=f"Retry Unresolved: enrichment failed for {failed} of {total} object names",
                details={"failed_targets": failed, "total": total}, actor="system",
            )
    logger.info("retry_unresolved: done - resolved=%d, failed=%d", resolved, failed)
    return {"status": "complete", **details}


SMART_REBUILD_LOCK = "smart_rebuild:lock"
SMART_REBUILD_LOCK_TTL = 300  # 5 minutes


@celery_app.task(bind=True)
def smart_rebuild_targets(self, manual: bool = False, parent_activity_id: int | None = None) -> dict:
    """Quick fix: repair target data using only local DB + SIMBAD cache.

    No SIMBAD network calls. Fixes:
    1. Images pointing to soft-deleted (merged) targets → redirect to winner
    2. Unresolved images that match existing target aliases → link them
    3. Missing FITS OBJECT names in aliases → add them
    4. primary_name inconsistent with catalog_id + common_name → rebuild
    5. Re-derive catalog_id/common_name from cached SIMBAD data if available
    6. Stale merge candidates → clean up
    """
    if not _redis.set(SMART_REBUILD_LOCK, "1", nx=True, ex=SMART_REBUILD_LOCK_TTL):
        logger.info("smart_rebuild: already running, skipping")
        return {"status": "skipped", "reason": "already running"}

    try:
        return _smart_rebuild_inner(manual=manual, parent_activity_id=parent_activity_id)
    finally:
        _redis.delete(SMART_REBUILD_LOCK)


def _smart_rebuild_inner(manual: bool = False, parent_activity_id: int | None = None) -> dict:
    logger.info("smart_rebuild: starting")
    clear_cancel_sync(_redis)
    set_rebuild_running_sync(_redis, "smart", "Running quick fix...")
    stats = {}

    def _emit_cancelled(extra: dict | None = None) -> dict:
        details = {**stats, **(extra or {})}
        set_rebuild_cancelled_sync(_redis, "Quick Fix cancelled", details)
        if manual or parent_activity_id:
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="rebuild", severity="info",
                    event_type="rebuild_cancelled",
                    message="Quick Fix cancelled by user",
                    details=details, actor="system",
                    parent_id=parent_activity_id,
                )
        logger.info("smart_rebuild: cancelled")
        return {"status": "cancelled", **details}

    if is_cancel_requested_sync(_redis):
        return _emit_cancelled()

    with Session(_sync_engine) as session:
        # Phase 1: Redirect images pointing to merged targets
        result = session.execute(text("""
            UPDATE images
            SET resolved_target_id = t.merged_into_id
            FROM targets t
            WHERE images.resolved_target_id = t.id
              AND t.merged_into_id IS NOT NULL
        """))
        stats["redirected_merged"] = result.rowcount
        logger.info("smart_rebuild: redirected %d images from merged targets", result.rowcount)

        # Phase 2: Link unresolved images to existing targets via alias match
        norm_expr = normalize_sql_expr("images.raw_headers->>'OBJECT'")
        result = session.execute(text(f"""
            UPDATE images
            SET resolved_target_id = t.id
            FROM targets t
            WHERE images.resolved_target_id IS NULL
              AND images.image_type = 'LIGHT'
              AND images.raw_headers->>'OBJECT' IS NOT NULL
              AND t.merged_into_id IS NULL
              AND t.aliases @> ARRAY[{norm_expr}]::varchar[]
        """))
        stats["linked_unresolved"] = result.rowcount
        logger.info("smart_rebuild: linked %d unresolved images via alias match", result.rowcount)

        # Phase 3: Ensure all FITS OBJECT names are in target aliases
        norm_expr = normalize_sql_expr("img.raw_headers->>'OBJECT'")
        result = session.execute(text(f"""
            WITH target_fits AS (
                SELECT
                    img.resolved_target_id as tid,
                    array_agg(DISTINCT {norm_expr}) as fits_names
                FROM images img
                WHERE img.resolved_target_id IS NOT NULL
                  AND img.image_type = 'LIGHT'
                  AND img.raw_headers->>'OBJECT' IS NOT NULL
                GROUP BY img.resolved_target_id
            )
            UPDATE targets t
            SET aliases = (
                SELECT array(
                    SELECT DISTINCT unnest(array_cat(t.aliases, tf.fits_names::varchar[]))
                )
            )
            FROM target_fits tf
            WHERE t.id = tf.tid
              AND t.merged_into_id IS NULL
              AND NOT (t.aliases @> tf.fits_names::varchar[])
        """))
        stats["aliases_updated"] = result.rowcount
        logger.info("smart_rebuild: updated aliases for %d targets", result.rowcount)

        # Phase 4: Re-derive catalog_id/common_name from SIMBAD cache
        if is_cancel_requested_sync(_redis):
            session.commit()
            return _emit_cancelled()
        from app.models.simbad_cache import SimbadCache
        targets = session.execute(
            select(Target).where(Target.merged_into_id.is_(None))
        ).scalars().all()

        rederived = 0
        for target in targets:
            if is_cancel_requested_sync(_redis):
                stats["rederived"] = rederived
                session.commit()
                return _emit_cancelled()
            if target.name_locked:
                continue
            # Try to find cached SIMBAD data for this target
            cached = get_cached_simbad(normalize_object_name(target.catalog_id or target.primary_name), session)
            if cached and not cached.get("_negative"):
                # Get FITS names for this target
                fits_result = session.execute(text("""
                    SELECT DISTINCT raw_headers->>'OBJECT'
                    FROM images
                    WHERE resolved_target_id = :tid
                      AND raw_headers->>'OBJECT' IS NOT NULL
                """), {"tid": target.id})
                fits_names = [r[0] for r in fits_result.all() if r[0]]

                curated = curate_simbad_result(cached, fits_names=fits_names)
                new_primary = curated["primary_name"]
                new_catalog = curated["catalog_id"]
                new_common = curated["common_name"]

                if (target.primary_name != new_primary or
                        target.catalog_id != new_catalog or
                        target.common_name != new_common):
                    target.catalog_id = new_catalog
                    target.common_name = new_common
                    target.primary_name = new_primary
                    rederived += 1

        stats["rederived"] = rederived
        logger.info("smart_rebuild: re-derived catalog_id/common_name for %d targets", rederived)

        # Phase 5: Rebuild primary_name for any remaining mismatches
        # Only rebuild when catalog_id or common_name can drive the name;
        # skip targets where both are NULL and a non-trivial name already
        # exists (e.g. manually created asterisms with FITS-derived names).
        result = session.execute(text("""
            UPDATE targets
            SET primary_name = CASE
                WHEN catalog_id IS NOT NULL AND common_name IS NOT NULL
                    THEN catalog_id || ' - ' || common_name
                WHEN catalog_id IS NOT NULL THEN catalog_id
                WHEN common_name IS NOT NULL THEN common_name
                ELSE 'Unknown'
            END
            WHERE merged_into_id IS NULL
              AND (catalog_id IS NOT NULL OR common_name IS NOT NULL)
              AND name_locked = FALSE
              AND primary_name != CASE
                WHEN catalog_id IS NOT NULL AND common_name IS NOT NULL
                    THEN catalog_id || ' - ' || common_name
                WHEN catalog_id IS NOT NULL THEN catalog_id
                WHEN common_name IS NOT NULL THEN common_name
                ELSE 'Unknown'
            END
        """))
        stats["names_rebuilt"] = result.rowcount
        logger.info("smart_rebuild: rebuilt %d primary_names", result.rowcount)

        # Phase 6: Clean stale merge candidates
        result = session.execute(text("""
            DELETE FROM merge_candidates
            WHERE suggested_target_id NOT IN (
                SELECT id FROM targets WHERE merged_into_id IS NULL
            )
        """))
        stats["stale_candidates_removed"] = result.rowcount
        logger.info("smart_rebuild: removed %d stale merge candidates", result.rowcount)

        session.commit()

    # Queue post-fix tasks
    detect_duplicate_targets.apply_async(countdown=5, kwargs={"parent_activity_id": parent_activity_id})
    detect_mosaic_panels_task.apply_async(countdown=15, kwargs={"parent_activity_id": parent_activity_id})

    # Build summary message
    parts = []
    if stats.get("redirected_merged"): parts.append(f"{stats['redirected_merged']} orphaned images fixed")
    if stats.get("linked_unresolved"): parts.append(f"{stats['linked_unresolved']} unresolved images linked")
    if stats.get("aliases_updated"): parts.append(f"{stats['aliases_updated']} target aliases updated")
    if stats.get("rederived"): parts.append(f"{stats['rederived']} targets re-derived from cache")
    if stats.get("names_rebuilt"): parts.append(f"{stats['names_rebuilt']} names rebuilt")
    if stats.get("stale_candidates_removed"): parts.append(f"{stats['stale_candidates_removed']} stale candidates removed")
    message = "; ".join(parts) if parts else "No issues found"

    set_rebuild_complete_sync(_redis, message, stats)
    _invalidate_stats_cache()

    # Update scan summary with targets_updated from aliases updated this run
    try:
        import json as _json
        raw = _redis.get("galactilog:scan_summary")
        if raw:
            _summary = _json.loads(raw)
            _summary["targets_updated"] = stats.get("aliases_updated", 0)
            _redis.set("galactilog:scan_summary", _json.dumps(_summary))
    except Exception:
        logger.warning("smart_rebuild: failed to update scan_summary in Redis")

    if manual or parent_activity_id:
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="rebuild", severity="info",
                event_type="rebuild_complete",
                message=f"Quick Fix: {message}",
                details=stats, actor="system",
                parent_id=parent_activity_id,
            )
    logger.info("smart_rebuild: done - %s", stats)
    return {"status": "complete", **stats}


MOSAIC_DETECT_LOCK = "mosaic_detect:lock"
MOSAIC_DETECT_LOCK_TTL = 120  # 2 minutes


@celery_app.task(name="detect_mosaic_panels_task")
def detect_mosaic_panels_task(parent_activity_id: int | None = None):
    """Run mosaic panel detection as a background Celery task."""
    if not _redis.set(MOSAIC_DETECT_LOCK, "1", nx=True, ex=MOSAIC_DETECT_LOCK_TTL):
        logger.info("detect_mosaic_panels_task: already running, skipping")
        return {"status": "skipped", "reason": "already running"}

    try:
        import asyncio
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.services.mosaic_detection import detect_mosaic_panels

        async def _run():
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                count = await detect_mosaic_panels(session)
                await session.commit()
            await engine.dispose()
            return count

        count = asyncio.run(_run())
        logger.info("detect_mosaic_panels_task: found %d new suggestions", count)
        try:
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="mosaic", severity="info",
                    event_type="mosaic_detection_complete",
                    message=f"Mosaic detection complete: {count} new suggestion{'s' if count != 1 else ''} found",
                    details={"candidates": count}, actor="system",
                    parent_id=parent_activity_id,
                )
        except Exception:
            logger.warning("detect_mosaic_panels_task: failed to emit mosaic_detection_complete")
        return {"status": "complete", "new_suggestions": count}
    finally:
        _redis.delete(MOSAIC_DETECT_LOCK)


@celery_app.task(bind=True)
def backfill_csv_metrics(self):
    """Walk FITS tree and backfill Image rows with CSV metric data."""
    import redis as _redis

    redis_conn = _redis.from_url(settings.redis_url)
    root = Path(settings.fits_data_path)

    # Collect all directories containing ImageMetaData.csv
    csv_dirs = [csv_file.parent for csv_file in root.rglob("ImageMetaData.csv")]

    if not csv_dirs:
        set_idle_sync(redis_conn)
        return {"updated": 0, "dirs": 0}

    set_ingesting_sync(redis_conn, total=len(csv_dirs))
    total_updated = 0

    with _sync_engine.connect() as conn:
        for csv_dir in csv_dirs:
            try:
                # Parse CSV data for this directory
                image_data = parse_image_metadata_csv(csv_dir)
                if not image_data:
                    increment_completed_sync(redis_conn)
                    continue

                weather_data = parse_weather_csv(csv_dir)

                # Query images in this directory missing CSV data
                dir_prefix = str(csv_dir)
                stmt = select(Image.id, Image.file_name).where(
                    Image.file_path.like(f"{dir_prefix}%"),
                    Image.detected_stars.is_(None),
                )
                rows = conn.execute(stmt).fetchall()

                for row in rows:
                    img_entry = image_data.get(row.file_name)
                    if img_entry is None:
                        continue

                    # Build update dict from image CSV data
                    update_data = dict(img_entry)

                    # Join weather data by ExposureStartUTC
                    exposure_start = update_data.pop("_exposure_start_utc", None)
                    if exposure_start and weather_data:
                        weather_entry = weather_data.get(exposure_start)
                        if weather_entry:
                            update_data.update(weather_entry)

                    if update_data:
                        conn.execute(
                            sa_update(Image)
                            .where(Image.id == row.id)
                            .values(**update_data)
                        )
                        total_updated += 1

                conn.commit()
                increment_completed_sync(redis_conn)

            except Exception:
                increment_failed_sync(redis_conn)
                conn.rollback()

    set_idle_sync(redis_conn)
    return {"updated": total_updated, "dirs": len(csv_dirs)}


DATA_MIGRATION_LOCK = "data_migration:lock"
DATA_MIGRATION_LOCK_TTL = 600  # 10 minutes


@celery_app.task(bind=True)
def run_data_migrations(self, from_version: int) -> dict:
    """Run pending data migrations dispatched by startup version check."""
    from app.services.data_migrations import (
        DATA_VERSION, get_pending_migrations, set_data_version,
    )

    # Acquire lock to prevent duplicate runs on rapid restarts
    if not _redis.set(DATA_MIGRATION_LOCK, "1", nx=True, ex=DATA_MIGRATION_LOCK_TTL):
        logger.info("data_migrations: another migration is already running, skipping")
        return {"status": "skipped"}

    try:
        pending = get_pending_migrations(from_version)
        if not pending:
            logger.info("data_migrations: no pending migrations (v%d is current)", from_version)
            return {"status": "noop"}

        logger.info("data_migrations: upgrading v%d -> v%d (%d migrations)",
                    from_version, DATA_VERSION, len(pending))

        results = []
        with Session(_sync_engine) as session:
            for ver, desc, func in pending:
                logger.info("data_migrations: running v%d - %s", ver, desc)
                try:
                    summary = func(session)
                    set_data_version(session, ver)
                    session.commit()
                    results.append(f"v{ver}: {summary}")
                    logger.info("data_migrations: v%d complete - %s", ver, summary)
                except Exception as e:
                    session.rollback()
                    error_msg = f"Data upgrade failed at v{ver} ({desc}): {e}"
                    logger.exception("data_migrations: %s", error_msg)
                    with _activity_session() as _db:
                        _emit_activity_sync(
                            _db, redis=_redis, category="migration", severity="error",
                            event_type="data_upgrade_failed",
                            message=f"{error_msg}. Press Quick Fix to retry.",
                            details={"version": ver, "error": str(e)},
                            actor="system",
                        )
                    return {"status": "error", "version": ver, "error": str(e)}

        summary_msg = "Data upgrade complete: " + "; ".join(results)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="migration", severity="info",
                event_type="data_upgrade_complete",
                message=summary_msg,
                details={"from_version": from_version, "to_version": DATA_VERSION},
                actor="system",
            )
        logger.info("data_migrations: %s", summary_msg)

        # Queue quick fix + mosaic detection after data migrations
        smart_rebuild_targets.apply_async(countdown=5)
        detect_mosaic_panels_task.apply_async(countdown=30)

        return {"status": "complete", "from": from_version, "to": DATA_VERSION}
    finally:
        _redis.delete(DATA_MIGRATION_LOCK)


DARK_HOURS_LOCK = "dark_hours:lock"
DARK_HOURS_LOCK_TTL = 300  # 5 minutes


@celery_app.task
def backfill_dark_hours(parent_activity_id: int | None = None) -> dict:
    """Compute astronomical dark hours for all imaging dates missing from site_dark_hours.

    Extracts site coordinates from FITS headers, then batch-computes dark hours
    for every unique capture_date not yet in the table. Runs on startup and after scans.
    """
    from app.models.site_dark_hours import SiteDarkHours
    from app.services.astro_night import dark_hours_batch
    from app.api.stats import _extract_site_coords_sync
    from datetime import date as date_type

    # Prevent overlapping runs
    if not _redis.set(DARK_HOURS_LOCK, "1", nx=True, ex=DARK_HOURS_LOCK_TTL):
        return {"status": "skipped", "reason": "already running"}

    try:
        with Session(_sync_engine) as session:
            # Get site coordinates from FITS headers
            site_coords = _extract_site_coords_sync(session)
            if not site_coords:
                logger.info("dark_hours: no site coordinates in FITS headers, skipping")
                return {"status": "skipped", "reason": "no site coords"}

            lat, lon = site_coords.latitude, site_coords.longitude

            # Find unique capture dates that are missing from site_dark_hours
            existing_q = select(SiteDarkHours.date).where(
                SiteDarkHours.latitude == lat,
                SiteDarkHours.longitude == lon,
            )
            existing_dates = {row[0] for row in session.execute(existing_q).all()}

            all_dates_q = select(
                func.distinct(Image.session_date)
            ).where(
                Image.session_date.isnot(None),
                Image.image_type == "LIGHT",
            )
            all_imaging_dates = {row[0] for row in session.execute(all_dates_q).all()}

            missing = sorted(all_imaging_dates - existing_dates)
            if not missing:
                logger.info("dark_hours: all %d dates already computed", len(existing_dates))
                return {"status": "noop", "existing": len(existing_dates)}

            logger.info("dark_hours: computing %d missing dates (lat=%.2f, lon=%.2f)",
                        len(missing), lat, lon)

            # Batch compute in chunks to avoid memory issues
            CHUNK = 200
            computed = 0
            for i in range(0, len(missing), CHUNK):
                chunk = missing[i:i + CHUNK]
                dark_values = dark_hours_batch(chunk, lat, lon)
                for d, dh in zip(chunk, dark_values):
                    session.merge(SiteDarkHours(
                        date=d, dark_hours=dh, latitude=lat, longitude=lon,
                    ))
                session.commit()
                computed += len(chunk)
                logger.info("dark_hours: %d/%d dates computed", computed, len(missing))

            logger.info("dark_hours: backfill complete, %d dates added", computed)
            return {"status": "complete", "computed": computed, "total": len(all_imaging_dates)}
    except Exception:
        logger.exception("dark_hours: backfill failed")
        raise
    finally:
        _redis.delete(DARK_HOURS_LOCK)


@celery_app.task(name="detect_filename_targets")
def detect_filename_targets():
    """Scan uncategorized images (no OBJECT header) and extract targets from filenames."""
    import uuid
    from sqlalchemy import text as sa_text, select as sa_select, func as sa_func, or_
    from app.models.image import Image
    from app.models.filename_candidate import FilenameCandidate
    from app.services.filename_parser import extract_target_from_filename
    from app.services.filename_resolver import resolve_filename_candidate

    with Session(_sync_engine) as db:
        # Clear all pending candidates - re-detect from scratch with latest parser
        from sqlalchemy import delete as sa_delete
        db.execute(
            sa_delete(FilenameCandidate).where(FilenameCandidate.status == "pending")
        )
        db.commit()

        # Build noise set from known equipment/filter names in the DB
        db_noise: set[str] = set()
        for col in (Image.camera, Image.telescope, Image.filter_used):
            rows = db.execute(sa_select(col).where(col.isnot(None)).distinct()).all()
            for (val,) in rows:
                if val:
                    db_noise.add(val.lower())
                    # Also add individual words for multi-word names
                    # e.g. "ZWO ASI2600MM Pro" -> {"zwo asi2600mm pro", "zwo", "asi2600mm", "pro"}
                    for word in val.split():
                        db_noise.add(word.lower())

        # Find images with no resolved target and no OBJECT header
        unresolved_query = (
            sa_select(Image.id, Image.file_path)
            .where(
                Image.resolved_target_id.is_(None),
                Image.image_type == "LIGHT",
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
            )
        )
        unresolved = db.execute(unresolved_query).all()

        if not unresolved:
            return {"candidates_found": 0}

        # Get image_ids already tracked by accepted or dismissed candidates so
        # we don't re-process them. Dismissed means the user explicitly
        # rejected the suggestion - a rescan must not resurrect it.
        existing_candidates = db.execute(
            sa_select(FilenameCandidate.image_ids)
            .where(FilenameCandidate.status.in_(["accepted", "dismissed"]))
        ).all()
        tracked_image_ids = set()
        for row in existing_candidates:
            if row[0]:
                tracked_image_ids.update(row[0])

        # Also collect extracted_names that are currently dismissed, so groups
        # keyed by directory (no extracted_name) or by new images that weren't
        # in the original dismissed image_ids still get skipped by name.
        dismissed_names_rows = db.execute(
            sa_select(FilenameCandidate.extracted_name)
            .where(FilenameCandidate.status == "dismissed")
        ).all()
        dismissed_names = {row[0] for row in dismissed_names_rows if row[0]}

        # Group by extracted name
        groups: dict[str | None, list[tuple]] = {}  # key -> [(image_id, file_path)]
        for image_id, file_path in unresolved:
            if image_id in tracked_image_ids:
                continue
            extracted = extract_target_from_filename(Path(file_path), db_noise=db_noise)
            # For "no guess" files, key by parent directory
            key = extracted if extracted else f"__dir__:{Path(file_path).parent}"
            groups.setdefault(key, []).append((image_id, file_path))

        candidates_found = 0
        for key, files in groups.items():
            image_ids = [f[0] for f in files]
            file_paths = [f[1] for f in files]

            is_no_guess = key.startswith("__dir__:")
            extracted_name = None if is_no_guess else key

            if extracted_name and extracted_name in dismissed_names:
                continue

            # Check if a pending candidate with this extracted_name already exists
            if extracted_name:
                existing = db.execute(
                    sa_select(FilenameCandidate)
                    .where(
                        FilenameCandidate.extracted_name == extracted_name,
                        FilenameCandidate.status == "pending",
                    )
                ).scalar_one_or_none()
                if existing:
                    # Append to existing candidate
                    existing.image_ids = list(set(list(existing.image_ids or []) + image_ids))
                    existing.file_paths = list(set(list(existing.file_paths or []) + file_paths))
                    existing.file_count = len(existing.image_ids)
                    continue

            # Resolve the extracted name
            if extracted_name:
                resolution = resolve_filename_candidate(extracted_name, db, redis=_redis)
            else:
                resolution = {
                    "method": "none",
                    "confidence": 0.0,
                    "suggested_target_id": None,
                    "suggested_target_name": None,
                }

            suggested_id = resolution.get("suggested_target_id")

            db.add(FilenameCandidate(
                extracted_name=extracted_name,
                suggested_target_id=uuid.UUID(suggested_id) if suggested_id else None,
                method=resolution["method"],
                confidence=resolution["confidence"],
                status="pending",
                file_count=len(files),
                file_paths=file_paths,
                image_ids=image_ids,
            ))
            candidates_found += 1

        db.commit()
        return {"candidates_found": candidates_found}


@celery_app.task(bind=True)
def generate_reference_thumbnails(self, force: bool = False, parent_activity_id: int | None = None) -> dict:
    """Fetch DSS reference thumbnails for all targets."""
    from app.services.skyview import fetch_reference_thumbnail

    clear_cancel_sync(_redis)
    set_rebuild_running_sync(_redis, "ref_thumbnails", "Finding targets needing thumbnails...")
    output_dir = Path(settings.thumbnails_path) / "reference"

    with Session(_sync_engine) as session:
        q = select(Target).where(
            Target.merged_into_id.is_(None),
            Target.ra.isnot(None),
            Target.dec.isnot(None),
        )
        if not force:
            q = q.where(Target.reference_thumbnail_path.is_(None))
        targets = session.execute(q).scalars().all()

        total = len(targets)
        set_rebuild_progress_sync(
            _redis, f"Fetching reference thumbnails 0/{total}..."
        )
        fetched = 0
        cancelled = False
        for i, target in enumerate(targets):
            if is_cancel_requested_sync(_redis):
                cancelled = True
                break
            path = fetch_reference_thumbnail(target, output_dir)
            if path:
                target.reference_thumbnail_path = path
                fetched += 1
            if (i + 1) % 5 == 0 or i + 1 == total:
                set_rebuild_progress_sync(
                    _redis, f"Reference thumbnails: {i + 1}/{total} ({fetched} fetched)"
                )
            time.sleep(1.0)  # Rate limit
        session.commit()

    if cancelled:
        stats = {"fetched": fetched, "total": total}
        set_rebuild_cancelled_sync(
            _redis, f"Cancelled after fetching {fetched}/{total} reference thumbnails", stats
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message=f"Reference Thumbnails cancelled after {fetched}/{total}",
                details=stats, actor="system",
                parent_id=parent_activity_id,
            )
        return {"status": "cancelled", **stats}

    _invalidate_stats_cache()
    stats = {"fetched": fetched, "total": total}
    set_rebuild_complete_sync(
        _redis, f"Fetched {fetched}/{total} reference thumbnails", stats
    )
    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="ref_thumbnails_complete",
            message=f"Reference Thumbnails: fetched {fetched}/{total}",
            details=stats, actor="system",
            parent_id=parent_activity_id,
        )
    return stats


@celery_app.task(name="recompute_session_dates", bind=True)
def recompute_session_dates(self):
    """Recompute session_date for all images and re-key session notes/custom values."""
    from collections import Counter
    from datetime import date as date_type, timedelta
    from app.models.session_note import SessionNote
    from app.models.custom_column import CustomColumnValue

    with Session(_sync_engine) as session:
        # Load settings
        settings_row = session.get(UserSettings, SETTINGS_ROW_ID)
        general = GeneralSettings(**(settings_row.general if settings_row and settings_row.general else {}))
        fallback_lon = general.observer_longitude
        use_night = general.use_imaging_night

        # Phase 1: Recompute all image session_dates in batches
        BATCH = 5000
        offset = 0
        total = 0
        while True:
            rows = session.execute(
                select(Image.id, Image.capture_date, Image.raw_headers)
                .where(Image.capture_date.isnot(None))
                .order_by(Image.id)
                .offset(offset)
                .limit(BATCH)
            ).all()
            if not rows:
                break

            for img_id, capture_date, raw_headers in rows:
                site_lon = extract_longitude(raw_headers)
                effective_lon = site_lon if site_lon is not None else fallback_lon
                new_date = compute_session_date(
                    capture_date,
                    use_imaging_night=use_night,
                    longitude=effective_lon,
                )
                session.execute(
                    sa_update(Image)
                    .where(Image.id == img_id)
                    .values(session_date=new_date)
                )

            session.commit()
            total += len(rows)
            offset += BATCH
            self.update_state(state="PROGRESS", meta={"images_updated": total})

        # Phase 2: Re-key SessionNote rows
        notes = session.execute(select(SessionNote)).scalars().all()
        for note in notes:
            old_date = note.session_date
            window_start = datetime.combine(old_date - timedelta(days=1), datetime.min.time())
            window_end = datetime.combine(old_date + timedelta(days=2), datetime.min.time())
            img_dates = session.execute(
                select(Image.session_date)
                .where(
                    Image.resolved_target_id == note.target_id,
                    Image.capture_date >= window_start,
                    Image.capture_date < window_end,
                    Image.session_date.isnot(None),
                )
            ).scalars().all()
            if img_dates:
                most_common = Counter(img_dates).most_common(1)[0][0]
                if most_common != note.session_date:
                    existing = session.execute(
                        select(SessionNote.id).where(
                            SessionNote.target_id == note.target_id,
                            SessionNote.session_date == most_common,
                            SessionNote.id != note.id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        note.session_date = most_common

        session.commit()

        # Phase 3: Re-key CustomColumnValue rows
        cvs = session.execute(
            select(CustomColumnValue).where(CustomColumnValue.session_date.isnot(None))
        ).scalars().all()
        for cv in cvs:
            old_date = cv.session_date
            window_start = datetime.combine(old_date - timedelta(days=1), datetime.min.time())
            window_end = datetime.combine(old_date + timedelta(days=2), datetime.min.time())
            img_dates = session.execute(
                select(Image.session_date)
                .where(
                    Image.resolved_target_id == cv.target_id,
                    Image.capture_date >= window_start,
                    Image.capture_date < window_end,
                    Image.session_date.isnot(None),
                )
            ).scalars().all()
            if img_dates:
                from sqlalchemy import func
                most_common = Counter(img_dates).most_common(1)[0][0]
                if most_common != cv.session_date:
                    existing = session.execute(
                        select(CustomColumnValue.id).where(
                            CustomColumnValue.column_id == cv.column_id,
                            CustomColumnValue.target_id == cv.target_id,
                            func.coalesce(CustomColumnValue.session_date, date_type(1970, 1, 1)) == most_common,
                            CustomColumnValue.id != cv.id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        cv.session_date = most_common

        session.commit()

        logger.info("recompute_session_dates: updated %d images", total)
        return {"status": "done", "images_updated": total}
