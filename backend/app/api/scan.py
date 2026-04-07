import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import async_redis
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models import Image, Target
from app.services.scan_state import (
    get_scan_state, get_failed_files, start_scanning, set_ingesting, set_idle, reset_scan,
    get_rebuild_state, request_cancel,
    get_activity, clear_activity,
)
from app.services.simbad import resolve_target_name, normalize_object_name
from app.worker.tasks import regenerate_thumbnail, run_scan, rebuild_targets, smart_rebuild_targets, retry_unresolved, backfill_csv_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("")
async def trigger_scan(
    include_calibration: bool = Query(False, description="Include calibration frames (BIAS, DARK, FLAT)"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Walk the FITS directory, queue new files for ingestion.

    The heavy directory scan runs inside a Celery task so this endpoint
    returns immediately — no nginx timeout issues on large data sets.
    """
    # Persist the frame filter choice for next visit
    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=SETTINGS_ROW_ID)
        session.add(row)
    row.general = {**(row.general or {}), "include_calibration": include_calibration}
    await session.commit()

    async with async_redis() as r:
        # Use SET NX as a lock to prevent race between check and dispatch
        acquired = await r.set("scan:lock", "1", nx=True, ex=10)
        if not acquired:
            return {"status": "already_running", "message": "Scan start in progress"}

        try:
            state = await get_scan_state(r)
            if state.state in ("scanning", "ingesting"):
                return {"status": "already_running", **state.to_dict()}

            run_scan.delay(include_calibration=include_calibration)

            return {"status": "accepted", "message": "Scan queued — check /scan/status for progress"}
        finally:
            await r.delete("scan:lock")


@router.post("/regenerate-thumbnails")
async def regenerate_thumbnails(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Queue all existing images for thumbnail regeneration."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            return {"status": "already_running", **state.to_dict()}

        await start_scanning(r)

        result = await session.execute(
            select(Image.id, Image.file_path, Image.thumbnail_path)
        )
        rows = result.all()

        if not rows:
            await set_idle(r)
            return {"status": "complete", "queued": 0}

        await set_ingesting(r, total=len(rows))

        for image_id, file_path, thumb_path in rows:
            if file_path and thumb_path:
                regenerate_thumbnail.delay(str(image_id), file_path, thumb_path)

        return {
            "status": "ingesting",
            "queued": len(rows),
            "message": "Regenerating all thumbnails with MTF stretch",
        }


@router.get("/status")
async def scan_status(user: User = Depends(get_current_user)):
    """Return current scan state from Redis."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        result = state.to_dict()
        if state.failed > 0:
            result["failed_files"] = await get_failed_files(r)
        return result


@router.post("/stop")
async def stop_scan(user: User = Depends(require_admin)):
    """Request cancellation of the current scan."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state not in ("scanning", "ingesting"):
            return {"status": "not_running", "state": state.state}
        await request_cancel(r)
        return {"status": "stopping", "message": "Cancel requested — scan will stop shortly"}


@router.get("/activity")
async def get_activity_log(user: User = Depends(get_current_user)):
    """Return persistent activity log (newest first)."""
    async with async_redis() as r:
        return await get_activity(r)


@router.delete("/activity")
async def clear_activity_log(user: User = Depends(require_admin)):
    """Clear the activity log."""
    async with async_redis() as r:
        await clear_activity(r)
        return {"status": "cleared"}


@router.post("/reset")
async def reset_scan_state(user: User = Depends(require_admin)):
    """Force-clear a stalled scan back to idle."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        await reset_scan(r)
        return {
            "status": "reset",
            "previous_state": state.state,
            "completed": state.completed,
            "failed": state.failed,
            "total": state.total,
        }


@router.post("/backfill-targets")
async def backfill_targets(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Resolve targets for already-ingested images that have NULL resolved_target_id.

    Only queries SIMBAD once per unique object name with a 0.5s delay between
    requests to respect rate limits. Then bulk-updates all matching images.
    """
    # Step 1: Get distinct unresolved object names
    result = await session.execute(
        text("""
            SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
            FROM images
            WHERE resolved_target_id IS NULL
              AND raw_headers->>'OBJECT' IS NOT NULL
              AND raw_headers->>'OBJECT' != ''
            GROUP BY raw_headers->>'OBJECT'
            ORDER BY cnt DESC
            LIMIT 500
        """)
    )
    unresolved = result.all()

    if not unresolved:
        return {"status": "complete", "resolved": 0, "failed": 0, "images_updated": 0}

    resolved_count = 0
    failed_names = []
    total_images_updated = 0

    for object_name, image_count in unresolved:
        normalized = normalize_object_name(object_name)

        # Check if target already exists (from ongoing scan or previous backfill)
        existing = await session.execute(
            select(Target).where(Target.aliases.any(normalized))
        )
        target = existing.scalar_one_or_none()

        if not target:
            existing = await session.execute(
                select(Target).where(Target.primary_name == object_name)
            )
            target = existing.scalar_one_or_none()

        if not target:
            # Query SIMBAD
            simbad_result = await resolve_target_name(object_name)

            if simbad_result:
                # Check if SIMBAD primary_name already exists as a target
                existing = await session.execute(
                    select(Target).where(Target.primary_name == simbad_result["primary_name"])
                )
                target = existing.scalar_one_or_none()

                if not target:
                    aliases = [normalize_object_name(a) for a in simbad_result.get("aliases", [])]
                    if normalized not in aliases:
                        aliases.append(normalized)
                    target = Target(
                        primary_name=simbad_result["primary_name"],
                        aliases=aliases,
                        ra=simbad_result.get("ra"),
                        dec=simbad_result.get("dec"),
                        object_type=simbad_result.get("object_type"),
                    )
                    session.add(target)
                    await session.flush()  # get target.id
                else:
                    # Add this name as alias if not already present
                    if normalized not in target.aliases:
                        target.aliases = [*target.aliases, normalized]
                        await session.flush()

                # Rate limit: 0.5s between SIMBAD queries
                await asyncio.sleep(0.5)
            else:
                failed_names.append(object_name)
                logger.info("Backfill: SIMBAD found no match for '%s' (%d images)", object_name, image_count)
                await asyncio.sleep(0.5)
                continue

        # Bulk-update all images with this object name
        update_result = await session.execute(
            text("""
                UPDATE images
                SET resolved_target_id = :target_id
                WHERE resolved_target_id IS NULL
                  AND raw_headers->>'OBJECT' = :obj_name
            """),
            {"target_id": target.id, "obj_name": object_name},
        )
        updated = update_result.rowcount
        total_images_updated += updated
        resolved_count += 1
        logger.info(
            "Backfill: '%s' -> '%s' (%d images updated)",
            object_name, target.primary_name, updated,
        )

    await session.commit()

    return {
        "status": "complete",
        "unique_names_processed": len(unresolved),
        "resolved": resolved_count,
        "failed": len(failed_names),
        "failed_names": failed_names,
        "images_updated": total_images_updated,
    }


@router.post("/rebuild-targets")
async def trigger_rebuild_targets(user: User = Depends(require_admin)):
    """Delete all targets and re-resolve from FITS headers via SIMBAD.

    This is a destructive operation that clears all targets, merge history,
    and re-resolves everything from scratch. Runs as a background Celery task.
    Uses persistent SIMBAD cache — fast on repeat runs.
    """
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        rebuild_targets.delay()
        return {"status": "accepted", "message": "Target rebuild queued as background task"}


@router.post("/smart-rebuild-targets")
async def trigger_smart_rebuild(user: User = Depends(require_admin)):
    """Quick fix: repair target data using local DB + SIMBAD cache only.

    No SIMBAD network calls. Fixes orphaned images, missing aliases,
    inconsistent names, and stale merge candidates.
    """
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        smart_rebuild_targets.delay(manual=True)
        return {"status": "accepted", "message": "Smart rebuild queued as background task"}


@router.post("/retry-unresolved")
async def trigger_retry_unresolved(user: User = Depends(require_admin)):
    """Clear SIMBAD negative cache and SESAME cache, then re-resolve unresolved targets."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        retry_unresolved.delay()
        return {"status": "accepted", "message": "Retry unresolved queued as background task"}


@router.post("/backfill-csv")
async def backfill_csv_metrics_endpoint(user: User = Depends(require_admin)):
    """Backfill Image rows with metrics from N.I.N.A. CSV files."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state != "idle":
            return {"status": "already_running", "state": state.state}
        backfill_csv_metrics.delay()
        return {"status": "accepted"}


@router.get("/rebuild-status")
async def rebuild_status(user: User = Depends(get_current_user)):
    """Return current rebuild task state from Redis."""
    async with async_redis() as r:
        state = await get_rebuild_state(r)
        return state.to_dict()


@router.get("/db-summary")
async def db_summary(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Lightweight database summary for the Scan & Ingest page."""
    result = await session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM images) AS total_images,
            (SELECT COUNT(*) FROM images WHERE image_type = 'LIGHT') AS light_frames,
            (SELECT COUNT(*) FROM targets WHERE merged_into_id IS NULL) AS resolved_targets,
            (SELECT COUNT(*) FROM images
             WHERE resolved_target_id IS NULL AND image_type = 'LIGHT'
               AND raw_headers->>'OBJECT' IS NOT NULL
               AND raw_headers->>'OBJECT' != '') AS unresolved_images,
            (SELECT COUNT(*) FROM simbad_cache) AS cached_simbad,
            (SELECT COUNT(*) FROM simbad_cache WHERE main_id IS NULL) AS cached_negative,
            (SELECT COUNT(*) FROM merge_candidates WHERE status = 'pending') AS pending_merges,
            (SELECT COUNT(*) FROM images WHERE detected_stars IS NOT NULL) AS csv_enriched,
            (SELECT COUNT(*) FROM vizier_cache) AS cached_vizier,
            (SELECT COUNT(*) FROM vizier_cache WHERE size_major IS NULL AND size_minor IS NULL) AS cached_vizier_negative,
            (SELECT COUNT(*) FROM sesame_cache) AS cached_sesame,
            (SELECT COUNT(*) FROM sesame_cache WHERE main_id IS NULL) AS cached_sesame_negative
    """))
    row = result.one()
    return {
        "total_images": row[0],
        "light_frames": row[1],
        "resolved_targets": row[2],
        "unresolved_images": row[3],
        "cached_simbad": row[4],
        "cached_negative": row[5],
        "pending_merges": row[6],
        "csv_enriched": row[7],
        "cached_vizier": row[8],
        "cached_vizier_negative": row[9],
        "cached_sesame": row[10],
        "cached_sesame_negative": row[11],
    }


VALID_INTERVALS = {60, 120, 240, 480, 720, 1440}


@router.get("/autoscan")
async def get_autoscan(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return current auto-scan settings (deprecated — use /settings/general)."""
    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    general = row.general if row else {}
    return {
        "enabled": general.get("auto_scan_enabled", True),
        "interval_minutes": general.get("auto_scan_interval", 240),
    }


@router.put("/autoscan")
async def set_autoscan(
    enabled: bool = Query(...),
    interval_minutes: int = Query(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update auto-scan settings (deprecated — use /settings/general)."""
    if interval_minutes not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Must be one of: {sorted(VALID_INTERVALS)}")

    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=SETTINGS_ROW_ID)
        session.add(row)

    row.general = {
        **(row.general or {}),
        "auto_scan_enabled": enabled,
        "auto_scan_interval": interval_minutes,
    }
    await session.commit()
    return {
        "enabled": enabled,
        "interval_minutes": interval_minutes,
    }
