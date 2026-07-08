"""Target rebuild pipeline: rebuild_targets (full), retry_unresolved,
smart_rebuild_targets (quick fix), and enrich_new_target_task."""
import logging
import time

from sqlalchemy import text, select
from sqlalchemy.orm import Session
from celery.exceptions import SoftTimeLimitExceeded

from app.models import Target
from app.services import catalog_cache as cc
from app.services.target_resolver import resolve_target, normalize_sql_expr
from app.services.simbad import (
    normalize_object_name, curate_simbad_result, get_cached_simbad,
)
from app.services.mosaic_detection import recompute_panel_membership_for_images_sync
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis, _activity_session, _invalidate_stats_cache
from app.worker.tasks_target_dedup import detect_duplicate_targets
from app.worker.tasks_mosaics import detect_mosaic_panels_task
from app.services.scan_state import (
    clear_cancel_sync, is_cancel_requested_sync,
    set_rebuild_running_sync, set_rebuild_progress_sync, set_rebuild_complete_sync,
    set_rebuild_cancelled_sync,
)
from app.services.activity import emit_sync as _emit_activity_sync

logger = logging.getLogger(__name__)

SMART_REBUILD_LOCK = "smart_rebuild:lock"
SMART_REBUILD_LOCK_TTL = 300  # 5 minutes


@celery_app.task(bind=True, name="app.worker.tasks.rebuild_targets")
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
    set_rebuild_running_sync(
        _redis, "full", "Clearing existing targets...",
        task="full", step=0, total_steps=0,
    )

    # Phase 1: Clear everything except user-defined custom targets, which SIMBAD
    # cannot recreate. Unlink only images NOT attached to a surviving custom
    # target so a custom "Jupiter" and its frames survive the rebuild.
    with Session(_sync_engine) as session:
        cleared_ids = session.execute(text("""
            UPDATE images SET resolved_target_id = NULL
            WHERE resolved_target_id IS NULL
               OR resolved_target_id NOT IN (
                   SELECT id FROM targets WHERE user_defined = TRUE
               )
            RETURNING id
        """)).scalars().all()
        # Cleared images no longer have a valid (target_id, panel_label) to
        # look up a panel under -- recompute (which clears panel_id when
        # target_id is NULL) before the owning targets are deleted below.
        recompute_panel_membership_for_images_sync(session, cleared_ids)
        session.execute(text("DELETE FROM merge_candidates"))
        session.execute(text("DELETE FROM targets WHERE user_defined = FALSE"))
        session.commit()
    logger.info("rebuild_targets: cleared all non-custom targets and links")

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
    set_rebuild_progress_sync(
        _redis, f"Resolving 0/{total} object names...",
        task="full", step=0, total_steps=total,
    )

    resolved = 0
    failed = 0
    processed = 0
    timed_out = False

    # Phase 3: Resolve each and link images. Each resolved name is committed on
    # its own (below), so partial progress already persists across a kill; the
    # SoftTimeLimitExceeded guard just makes sure REBUILD_KEY lands in a terminal
    # state instead of being stranded at "running" (AUD-003).
    try:
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

            try:
                with Session(_sync_engine) as session:
                    target_id = resolve_target(obj_name, session, redis=_redis)
            except cc.NonTransientError as exc:
                target_id = None
                logger.warning(
                    "rebuild_targets: non-transient resolve failure for '%s', skipping: %s",
                    obj_name, exc,
                )

            if target_id:
                with Session(_sync_engine) as session:
                    resolved_ids = session.execute(text("""
                        UPDATE images
                        SET resolved_target_id = :tid
                        WHERE resolved_target_id IS NULL
                          AND raw_headers->>'OBJECT' = :obj_name
                        RETURNING id
                    """), {"tid": target_id, "obj_name": obj_name}).scalars().all()
                    recompute_panel_membership_for_images_sync(session, resolved_ids)
                    session.commit()
                resolved += 1
                logger.info("rebuild_targets: %s -> %s (%d images)", obj_name, target_id, img_count)
            else:
                failed += 1
                logger.info("rebuild_targets: FAILED %s (%d images)", obj_name, img_count)

            processed = i + 1
            if (i + 1) % 5 == 0 or i + 1 == total:
                set_rebuild_progress_sync(
                    _redis, f"Resolving {i + 1}/{total} object names...",
                    task="full", step=i + 1, total_steps=total,
                )

            time.sleep(0.3)  # Rate limit SIMBAD
    except SoftTimeLimitExceeded:
        timed_out = True

    if timed_out:
        details = {"resolved": resolved, "failed": failed, "total": total, "processed": processed}
        set_rebuild_complete_sync(
            _redis,
            f"Full Rebuild paused at the time limit after {processed}/{total} names "
            f"({resolved} resolved, {failed} failed)",
            details,
            task="full", step=processed, total_steps=total,
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="rebuild", severity="warning",
                event_type="rebuild_complete",
                message=f"Full Rebuild paused at time limit after {processed}/{total} names",
                details=details, actor="system",
            )
        logger.warning("rebuild_targets: timed out after %d/%d names", processed, total)
        return {"status": "timeout", **details}

    # Phase 4: Queue post-rebuild tasks
    detect_duplicate_targets.apply_async(countdown=10)
    detect_mosaic_panels_task.apply_async(countdown=20)

    details = {"resolved": resolved, "failed": failed, "total": total}
    set_rebuild_complete_sync(
        _redis,
        f"Resolved {resolved} targets, {failed} failed out of {total} object names",
        details,
        task="full", step=total, total_steps=total,
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


@celery_app.task(bind=True, name="app.worker.tasks.retry_unresolved")
def retry_unresolved(self) -> dict:
    """Clear SIMBAD negative cache and SESAME cache, then re-resolve unresolved targets.

    Unlike Full Rebuild, this only touches unresolved images - existing targets are untouched.
    Useful after adding SESAME fallback or when upstream resolvers have new data.
    """
    logger.info("retry_unresolved: starting")
    clear_cancel_sync(_redis)
    set_rebuild_running_sync(
        _redis, "retry", "Clearing caches...",
        task="retry", step=0, total_steps=0,
    )

    # Phase 1: Clear negative caches so names get a fresh shot
    from app.services import catalog_cache as cc

    with Session(_sync_engine) as session:
        cc.clear_negative(session, "simbad")
        cc.invalidate(session, "sesame")
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
    set_rebuild_progress_sync(
        _redis, f"Retrying 0/{total} unresolved names...",
        task="retry", step=0, total_steps=total,
    )

    resolved = 0
    failed = 0
    processed = 0
    timed_out = False

    # Phase 3: Resolve each and link images. Only unresolved names are queried
    # and each success is committed immediately, so a killed run resumes
    # naturally (the next run re-selects whatever is still unresolved). The
    # SoftTimeLimitExceeded guard just ensures a terminal REBUILD_KEY state
    # instead of a stuck "running" (AUD-003).
    try:
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

            try:
                with Session(_sync_engine) as session:
                    target_id = resolve_target(obj_name, session, redis=_redis)
            except cc.NonTransientError as exc:
                target_id = None
                logger.warning(
                    "retry_unresolved: non-transient resolve failure for '%s', skipping: %s",
                    obj_name, exc,
                )

            if target_id:
                with Session(_sync_engine) as session:
                    resolved_ids = session.execute(text("""
                        UPDATE images
                        SET resolved_target_id = :tid
                        WHERE resolved_target_id IS NULL
                          AND raw_headers->>'OBJECT' = :obj_name
                        RETURNING id
                    """), {"tid": target_id, "obj_name": obj_name}).scalars().all()
                    recompute_panel_membership_for_images_sync(session, resolved_ids)
                    session.commit()
                resolved += 1
                logger.info("retry_unresolved: %s -> %s (%d images)", obj_name, target_id, img_count)
            else:
                failed += 1

            processed = i + 1
            if (i + 1) % 5 == 0 or i + 1 == total:
                set_rebuild_progress_sync(
                    _redis, f"Retrying {i + 1}/{total} unresolved names...",
                    task="retry", step=i + 1, total_steps=total,
                )

            time.sleep(0.3)  # Rate limit external services
    except SoftTimeLimitExceeded:
        timed_out = True

    if timed_out:
        details = {"resolved": resolved, "failed": failed, "total": total, "processed": processed}
        set_rebuild_complete_sync(
            _redis,
            f"Retry Unresolved paused at the time limit after {processed}/{total} names "
            f"({resolved} resolved, {failed} still unresolved)",
            details,
            task="retry", step=processed, total_steps=total,
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="rebuild", severity="warning",
                event_type="rebuild_complete",
                message=f"Retry Unresolved paused at time limit after {processed}/{total} names",
                details=details, actor="system",
            )
        logger.warning("retry_unresolved: timed out after %d/%d names", processed, total)
        return {"status": "timeout", **details}

    details = {"resolved": resolved, "failed": failed, "total": total}
    set_rebuild_complete_sync(
        _redis,
        f"Retry: {resolved} resolved, {failed} still unresolved out of {total} names",
        details,
        task="retry", step=total, total_steps=total,
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


@celery_app.task(bind=True, name="app.worker.tasks.smart_rebuild_targets")
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
    set_rebuild_running_sync(
        _redis, "smart", "Running quick fix...",
        task="smart", step=0, total_steps=1,
    )
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
        redirected_ids = session.execute(text("""
            UPDATE images
            SET resolved_target_id = t.merged_into_id
            FROM targets t
            WHERE images.resolved_target_id = t.id
              AND t.merged_into_id IS NOT NULL
            RETURNING images.id
        """)).scalars().all()
        recompute_panel_membership_for_images_sync(session, redirected_ids)
        stats["redirected_merged"] = len(redirected_ids)
        logger.info("smart_rebuild: redirected %d images from merged targets", len(redirected_ids))

        # Phase 2: Link unresolved images to existing targets via alias match
        norm_expr = normalize_sql_expr("images.raw_headers->>'OBJECT'")
        linked_ids = session.execute(text(f"""
            UPDATE images
            SET resolved_target_id = t.id
            FROM targets t
            WHERE images.resolved_target_id IS NULL
              AND images.image_type = 'LIGHT'
              AND images.raw_headers->>'OBJECT' IS NOT NULL
              AND t.merged_into_id IS NULL
              AND t.aliases @> ARRAY[{norm_expr}]::varchar[]
            RETURNING images.id
        """)).scalars().all()
        recompute_panel_membership_for_images_sync(session, linked_ids)
        stats["linked_unresolved"] = len(linked_ids)
        logger.info("smart_rebuild: linked %d unresolved images via alias match", len(linked_ids))

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
        targets = session.execute(
            select(Target).where(Target.merged_into_id.is_(None))
        ).scalars().all()

        rederived = 0
        for target in targets:
            if is_cancel_requested_sync(_redis):
                stats["rederived"] = rederived
                session.commit()
                return _emit_cancelled()
            if target.name_locked or target.user_defined:
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
              AND user_defined = FALSE
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

    set_rebuild_complete_sync(
        _redis, message, stats,
        task="smart", step=1, total_steps=1,
    )
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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="app.worker.tasks.enrich_new_target_task")
def enrich_new_target_task(self, target_id: str) -> dict:
    """Follow-up enrichment for a newly created target (AUD-006).

    Dispatched async from `_create_target` so ingest is never blocked on Gaia/
    HyperLEDA network latency. Runs the constellation fallback, per-target
    catalog membership matching, cluster-gated Gaia distance, and galaxy-gated
    HyperLEDA morphology/inclination. All steps are idempotent, so a retry is
    safe. Makes at most a few network calls for one target, so the global
    600s/660s Celery time limit is ample -- no task_annotations override needed.
    """
    import uuid as _uuid
    from app.services.target_enrichment import enrich_new_target

    try:
        with Session(_sync_engine) as session:
            target = session.get(Target, _uuid.UUID(str(target_id)))
            if target is None:
                logger.info("enrich_new_target_task: target %s not found", target_id)
                return {"status": "missing", "target_id": str(target_id)}
            result = enrich_new_target(session, target)
            session.commit()
        logger.info("enrich_new_target_task: enriched %s (%s)", target_id, result)
        return {"status": "ok", "target_id": str(target_id), **result}
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("enrich_new_target_task failed for %s: %s", target_id, exc)
        if self.request.retries >= self.max_retries:
            return {"status": "failed", "target_id": str(target_id), "error": str(exc)}
        raise self.retry(exc=exc)
