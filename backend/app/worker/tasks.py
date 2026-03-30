import logging
from pathlib import Path

from sqlalchemy import create_engine, select, text, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Image, Target
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.csv_metadata import parse_image_metadata_csv, parse_weather_csv
from app.services.scanner import extract_metadata
from app.services.simbad import (
    resolve_target_name, normalize_object_name, resolve_target_name_cached,
    curate_simbad_result, get_cached_simbad, save_simbad_cache,
    curate_aliases, extract_catalog_id, extract_common_name, build_primary_name,
    _normalize_ws,
)
from app.services.thumbnail import generate_thumbnail
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Celery uses sync — create a sync engine for the worker
# Replace asyncpg with psycopg2 for sync operations
_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url)

# Ensure database tables exist when worker starts
from app.models import Base
Base.metadata.create_all(_sync_engine)

from app.config import get_sync_redis
from app.services.scan_state import (
    increment_completed_sync, increment_failed_sync, increment_csv_enriched_sync,
    start_scanning_sync, set_ingesting_sync, set_idle_sync,
    set_rebuild_running_sync, set_rebuild_progress_sync, set_rebuild_complete_sync,
    set_discovered_sync, is_cancel_requested_sync, clear_cancel_sync, set_cancelled_sync,
    append_activity_sync, check_complete_sync,
)

_redis = get_sync_redis()


@celery_app.task(bind=True)
def run_scan(self, include_calibration: bool = True) -> dict:
    """Scan the FITS directory and queue ingest tasks for new files.

    Runs entirely inside Celery so the HTTP endpoint returns immediately.
    """
    from app.services.scanner import scan_directory

    clear_cancel_sync(_redis)
    start_scanning_sync(_redis)

    # Get known paths from DB
    with Session(_sync_engine) as session:
        result = session.execute(select(Image.file_path))
        known_paths = {row[0] for row in result.all()}

    fits_root = Path(settings.fits_data_path)

    # Dispatch ingest tasks as files are discovered (parallel discovery + ingestion)
    def _queue_file(path: Path) -> None:
        ingest_file.delay(str(path))

    new_files, all_disk_paths = scan_directory(
        fits_root, known_paths=known_paths, include_calibration=include_calibration,
        on_progress=lambda count: set_discovered_sync(_redis, count),
        is_cancelled=lambda: is_cancel_requested_sync(_redis),
        on_new_file=_queue_file,
    )

    if is_cancel_requested_sync(_redis):
        set_cancelled_sync(_redis)
        append_activity_sync(_redis, {
            "type": "scan_stopped",
            "message": f"Scan stopped by user ({len(new_files)} files discovered before stop)",
            "details": {"discovered": len(new_files)},
            "timestamp": __import__('time').time(),
        })
        return {"status": "cancelled"}

    # Detect and remove orphaned DB records (files deleted from disk)
    orphaned_paths = known_paths - all_disk_paths
    removed = 0
    if orphaned_paths and len(orphaned_paths) < len(known_paths) * 0.5:
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
    elif orphaned_paths:
        logger.warning(
            "Skipped orphan cleanup: %d of %d files missing (>50%%) — "
            "possible unmounted share or unreachable storage",
            len(orphaned_paths), len(known_paths),
        )

    if not new_files:
        set_idle_sync(_redis)
        cataloged = len(known_paths) - removed
        msg = f"Scan complete: no new files found ({cataloged} already cataloged)"
        if removed:
            msg += f", {removed} deleted files purged from catalog"
        append_activity_sync(_redis, {
            "type": "scan_complete",
            "message": msg,
            "details": {"completed": 0, "failed": 0, "already_known": cataloged, "removed": removed},
            "timestamp": __import__('time').time(),
        })
        return {"status": "complete", "new_files_queued": 0, "already_known": cataloged, "removed": removed}

    # Transition to ingesting with final total — ingest tasks are already running
    set_ingesting_sync(_redis, total=len(new_files), removed=removed)
    # Some tasks may have already completed during discovery, check now
    check_complete_sync(_redis)

    # Queue duplicate detection after ingest
    detect_duplicate_targets.apply_async(countdown=30)

    return {
        "status": "ingesting",
        "new_files_queued": len(new_files),
        "already_known": len(known_paths),
        "removed": removed,
    }


@celery_app.task
def auto_scan_tick():
    """Heartbeat task: check if an auto-scan is due and dispatch if so."""
    import time

    # Read auto-scan config from DB (migrated from Redis)
    with Session(_sync_engine) as db_session:
        row = db_session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        ).scalar_one_or_none()

    if row is None or not (row.general or {}).get("auto_scan_enabled", True):
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
    include_cal = (row.general or {}).get("include_calibration", True)
    run_scan.delay(include_calibration=include_cal)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_file(self, fits_path: str) -> dict:
    """Full ingest pipeline for a single FITS file.

    1. Extract metadata from FITS headers
    2. Generate stretched JPEG thumbnail
    3. Resolve target name via SIMBAD (with local cache)
    4. Insert/update database record
    """
    path = Path(fits_path)

    # Skip if scan was cancelled
    if is_cancel_requested_sync(_redis):
        increment_failed_sync(_redis, file_path=fits_path, error="Scan cancelled")
        return {"status": "cancelled", "file": fits_path}

    logger.info("Ingesting: %s", path.name)

    try:
        # Step 1: Extract metadata
        meta = extract_metadata(path)

        image_type = (meta.get("image_type") or "").upper()
        is_calibration = image_type in ("DARK", "FLAT", "BIAS", "DARKFLAT")

        # Step 2: Generate thumbnail (skip calibration frames)
        thumb_path = None
        if not is_calibration:
            import hashlib
            path_hash = hashlib.md5(str(path).encode()).hexdigest()[:12]
            thumb_filename = f"{path.stem}_{path_hash}.jpg"
            thumb_path = Path(settings.thumbnails_path) / thumb_filename
            generate_thumbnail(path, thumb_path, max_width=settings.thumbnail_max_width)

        # Step 3: Resolve target (sync wrapper for async SIMBAD call)
        # Skip SIMBAD for calibration frames — they're not astronomical targets
        target_id = None
        if not is_calibration:
            object_name = meta.get("object_name")
            if object_name:
                target_id = _resolve_or_cache_target(object_name)

        # Step 4: Insert into database
        with Session(_sync_engine) as session:
            image = Image(
                file_path=meta["file_path"],
                file_name=meta["file_name"],
                capture_date=meta.get("capture_date"),
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
            logger.info("Ingested: %s (target=%s)", path.name, target_id)
            increment_completed_sync(_redis)
            if meta.get("detected_stars") is not None:
                increment_csv_enriched_sync(_redis)
            return {"file": str(path), "status": "ok"}

    except IntegrityError:
        # File already ingested (race between scan querying known_paths and ingest)
        logger.info("Already ingested (duplicate): %s", path.name)
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "duplicate"}

    except Exception as exc:
        logger.error("Failed to ingest %s: %s", path, exc)
        # Don't retry on unrecoverable errors (corrupt files, missing headers, etc.)
        unrecoverable = isinstance(exc, (OSError, ValueError)) and (
            "SIMPLE card" in str(exc)
            or "not a valid FITS" in str(exc)
            or "No such file" in str(exc)
        )
        if unrecoverable or self.request.retries >= self.max_retries:
            increment_failed_sync(_redis, file_path=str(path), error=str(exc))
            return {"file": str(path), "status": "failed", "error": str(exc)}
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def regenerate_thumbnail(self, image_id: str, fits_path: str, thumb_path: str) -> dict:
    """Regenerate a single thumbnail using the current stretch algorithm."""
    path = Path(fits_path)
    output = Path(thumb_path)
    logger.info("Regenerating thumbnail: %s", path.name)

    try:
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
def detect_duplicate_targets():
    """Detect potential duplicate targets by comparing unresolved names against resolved targets."""
    from sqlalchemy import text as sa_text, select as sa_select, func as sa_func
    from app.models.target import Target
    from app.models.image import Image
    from app.models.merge_candidate import MergeCandidate

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

        if not unresolved:
            return {"candidates_found": 0}

        # Get existing pending/accepted candidates to avoid duplicates
        existing = db.execute(
            sa_select(MergeCandidate.source_name).where(
                MergeCandidate.status.in_(["pending", "accepted"])
            )
        )
        existing_names = {row[0] for row in existing.all()}

        candidates_found = 0

        for obj_name, img_count in unresolved:
            if not obj_name or obj_name in existing_names:
                continue

            # Trigram similarity search against all resolved target aliases
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
                ))
                candidates_found += 1

        db.commit()

    return {"candidates_found": candidates_found}


# In-memory cache of object names that SIMBAD couldn't resolve.
# Avoids repeated HTTP round-trips for the same unresolvable name
# (e.g., "FlatWizard", "Target", "Moon_fast" on every calibration frame).
_simbad_negative_cache: set[str] = set()


def _resolve_or_cache_target(object_name: str) -> str | None:
    """Check local DB for target, fall back to SIMBAD (with DB cache), create target."""
    normalized = normalize_object_name(object_name)

    # Check in-memory negative cache (fastest path, survives within worker lifetime)
    if normalized in _simbad_negative_cache:
        return None

    with Session(_sync_engine) as session:
        # Check local targets: search aliases array
        stmt = select(Target).where(Target.aliases.any(normalized))
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            return str(existing.id)

        # Also check by primary_name
        stmt = select(Target).where(Target.primary_name == object_name)
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            return str(existing.id)

    # Resolve via SIMBAD (uses persistent DB cache)
    with Session(_sync_engine) as session:
        result = resolve_target_name_cached(object_name, session)
        session.commit()  # Persist cache entry

    if result is None:
        _simbad_negative_cache.add(normalized)
        return None

    # Create target record
    with Session(_sync_engine) as session:
        aliases = result.get("aliases", [])
        if normalized not in [a.upper() for a in aliases]:
            aliases.append(normalized)

        target = Target(
            primary_name=result["primary_name"],
            catalog_id=result.get("catalog_id"),
            common_name=result.get("common_name"),
            aliases=aliases,
            ra=result.get("ra"),
            dec=result.get("dec"),
            object_type=result.get("object_type"),
        )
        try:
            session.add(target)
            session.commit()
            return str(target.id)
        except IntegrityError:
            session.rollback()
            # Another worker inserted this target — re-query
            stmt = select(Target).where(Target.primary_name == result["primary_name"])
            existing = session.execute(stmt).scalar_one_or_none()
            return str(existing.id) if existing else None


@celery_app.task(bind=True)
def rebuild_targets(self) -> dict:
    """Full target database rebuild: delete all targets, re-resolve from FITS headers.

    1. Clear resolved_target_id on all images
    2. Delete all targets and merge candidates
    3. Clear negative cache
    4. Get distinct OBJECT names from LIGHT frames
    5. Re-resolve each through SIMBAD (reusing _resolve_or_cache_target)
    6. Re-link images to new targets
    """
    import time

    logger.info("rebuild_targets: starting full rebuild")
    set_rebuild_running_sync(_redis, "full", "Clearing existing targets...")

    # Phase 1: Clear everything
    with Session(_sync_engine) as session:
        session.execute(text("UPDATE images SET resolved_target_id = NULL"))
        session.execute(text("DELETE FROM merge_candidates"))
        session.execute(text("DELETE FROM targets"))
        session.commit()
    logger.info("rebuild_targets: cleared all targets and links")

    _simbad_negative_cache.clear()

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
        target_id = _resolve_or_cache_target(obj_name)

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

    # Phase 4: Queue duplicate detection
    detect_duplicate_targets.apply_async(countdown=10)

    details = {"resolved": resolved, "failed": failed, "total": total}
    set_rebuild_complete_sync(
        _redis,
        f"Resolved {resolved} targets, {failed} failed out of {total} object names",
        details,
    )
    append_activity_sync(_redis, {
        "type": "rebuild_complete",
        "message": f"Full Rebuild: {resolved} resolved, {failed} failed out of {total} names",
        "details": {"resolved": resolved, "failed": failed, "total": total},
        "timestamp": __import__('time').time(),
    })
    logger.info("rebuild_targets: done — resolved=%d, failed=%d", resolved, failed)
    return {"status": "complete", **details}


@celery_app.task(bind=True)
def smart_rebuild_targets(self) -> dict:
    """Quick fix: repair target data using only local DB + SIMBAD cache.

    No SIMBAD network calls. Fixes:
    1. Images pointing to soft-deleted (merged) targets → redirect to winner
    2. Unresolved images that match existing target aliases → link them
    3. Missing FITS OBJECT names in aliases → add them
    4. primary_name inconsistent with catalog_id + common_name → rebuild
    5. Re-derive catalog_id/common_name from cached SIMBAD data if available
    6. Stale merge candidates → clean up
    """
    logger.info("smart_rebuild: starting")
    set_rebuild_running_sync(_redis, "smart", "Running quick fix...")
    stats = {}

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
        result = session.execute(text("""
            UPDATE images
            SET resolved_target_id = t.id
            FROM targets t
            WHERE images.resolved_target_id IS NULL
              AND images.image_type = 'LIGHT'
              AND images.raw_headers->>'OBJECT' IS NOT NULL
              AND t.merged_into_id IS NULL
              AND t.aliases @> ARRAY[UPPER(REGEXP_REPLACE(
                  TRIM(images.raw_headers->>'OBJECT'), '\\s+', ' ', 'g'
              ))]::varchar[]
        """))
        stats["linked_unresolved"] = result.rowcount
        logger.info("smart_rebuild: linked %d unresolved images via alias match", result.rowcount)

        # Phase 3: Ensure all FITS OBJECT names are in target aliases
        result = session.execute(text("""
            WITH target_fits AS (
                SELECT
                    img.resolved_target_id as tid,
                    array_agg(DISTINCT UPPER(REGEXP_REPLACE(
                        TRIM(img.raw_headers->>'OBJECT'), '\\s+', ' ', 'g'
                    ))) as fits_names
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
        from app.models.simbad_cache import SimbadCache
        targets = session.execute(
            select(Target).where(Target.merged_into_id.is_(None))
        ).scalars().all()

        rederived = 0
        for target in targets:
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

    # Queue duplicate detection
    detect_duplicate_targets.apply_async(countdown=5)

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
    append_activity_sync(_redis, {
        "type": "rebuild_complete",
        "message": f"Quick Fix: {stats['linked_unresolved']} linked, {stats['redirected_merged']} redirected, {stats['aliases_updated']} aliases updated",
        "details": stats,
        "timestamp": __import__('time').time(),
    })
    logger.info("smart_rebuild: done — %s", stats)
    return {"status": "complete", **stats}


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
