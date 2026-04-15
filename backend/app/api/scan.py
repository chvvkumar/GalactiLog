import asyncio
import logging
import os
from pathlib import Path as FsPath

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import async_redis, settings as app_settings
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models import Image, Target
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
import re as _re

from app.schemas.scan_filters import (
    ScanFiltersIn, ScanFiltersOut, TestPathIn, TestPathOut, BrowseEntry, ApplyNowOut,
    ValidateRegexIn, ValidateRegexOut,
)
from app.services.scan_filters import ScanFilterConfig
from app.services.scan_state import (
    get_scan_state, get_failed_files, start_scanning, set_ingesting, set_idle, reset_scan,
    get_rebuild_state, request_cancel,
    append_activity,
)
from app.services.simbad import resolve_target_name, normalize_object_name
from app.worker.tasks import regenerate_thumbnail, run_scan, rebuild_targets, smart_rebuild_targets, retry_unresolved, backfill_csv_metrics, generate_reference_thumbnails, run_xmatch_enrichment, purge_and_regenerate_thumbnails

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
    returns immediately - no nginx timeout issues on large data sets.
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

            return {"status": "accepted", "message": "Scan queued - check /scan/status for progress"}
        finally:
            await r.delete("scan:lock")


@router.post("/regenerate-thumbnails")
async def regenerate_thumbnails(
    purge: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Queue all existing images for thumbnail regeneration.

    When purge=True, delete all existing thumbnail files first, logging
    progress to the activity log, before queueing regeneration.
    """
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            return {"status": "already_running", **state.to_dict()}

        await start_scanning(r)

        if purge:
            # Defer DB work and file deletions to Celery so the HTTP call
            # returns immediately and progress is reported via activity log.
            purge_and_regenerate_thumbnails.delay()
            return {
                "status": "accepted",
                "message": "Queued: delete and regenerate all thumbnails",
            }

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
    """Request cancellation of the current scan or rebuild-family task."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        rebuild = await get_rebuild_state(r)
        scan_active = state.state in ("scanning", "ingesting")
        rebuild_active = rebuild.state == "running"
        if not scan_active and not rebuild_active:
            return {"status": "not_running", "state": state.state}
        await request_cancel(r)
        return {"status": "stopping", "message": "Cancel requested - task will stop shortly"}


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
    Uses persistent SIMBAD cache - fast on repeat runs.
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


@router.post("/generate-reference-thumbnails")
async def trigger_reference_thumbnails(force: bool = False, user: User = Depends(require_admin)):
    """Fetch DSS reference thumbnails from SkyView for all targets with coordinates."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        generate_reference_thumbnails.delay(force=force)
        return {"status": "accepted", "message": "Reference thumbnail generation queued as background task"}


@router.post("/xmatch-enrichment")
async def trigger_xmatch_enrichment(user: User = Depends(require_admin)):
    """Run CDS xMatch bulk cross-matching for all targets."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        run_xmatch_enrichment.delay()
        return {"status": "accepted", "message": "xMatch enrichment queued as background task"}


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
    """Return current auto-scan settings (deprecated - use /settings/general)."""
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
    """Update auto-scan settings (deprecated - use /settings/general)."""
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


@router.get("/filters", response_model=ScanFiltersOut)
async def get_scan_filters(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    general = (row.general if row else {}) or {}
    sf = general.get("scan_filters") or {
        "include_paths": [], "exclude_paths": [], "name_rules": [],
    }
    return ScanFiltersOut(
        configured=bool(general.get("scan_filters_configured")),
        filters=ScanFiltersIn(**sf),
        fits_root=str(FsPath(app_settings.fits_data_path).resolve()),
    )


@router.put("/filters", response_model=ScanFiltersOut)
async def put_scan_filters(
    payload: ScanFiltersIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    fits_root = FsPath(app_settings.fits_data_path)
    # Validate by constructing the config
    try:
        ScanFilterConfig.from_settings(
            {"scan_filters": payload.model_dump()}, fits_root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=SETTINGS_ROW_ID)
        session.add(row)
    row.general = {
        **(row.general or {}),
        "scan_filters": payload.model_dump(),
        "scan_filters_configured": True,
    }
    await session.commit()
    return ScanFiltersOut(
        configured=True,
        filters=payload,
        fits_root=str(fits_root.resolve()),
    )


@router.post("/filters/test", response_model=TestPathOut)
async def test_scan_filter_path(
    payload: TestPathIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    fits_root = FsPath(app_settings.fits_data_path)
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    general = (row.general if row else {}) or {}
    try:
        cfg = ScanFilterConfig.from_settings(general, fits_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    test_result = cfg.test_path(
        FsPath(payload.path), fits_root, target_kind=payload.target_kind,
    )
    return TestPathOut(
        verdict=test_result.verdict,
        matched_rule_ids=test_result.matched_rule_ids,
    )


@router.post("/filters/validate-regex", response_model=ValidateRegexOut)
async def validate_scan_filter_regex(
    payload: ValidateRegexIn,
    user: User = Depends(get_current_user),
):
    """Validate a regex pattern against Python's `re` engine.

    The scanner evaluates name rules with `re.compile(...).search(...)`, so
    this is the single source of truth for pattern validity. The frontend
    calls this instead of `new RegExp(...)` to avoid JS/Python dialect
    mismatches (e.g. `(?i)` inline flags, `(?P<name>)` named groups).
    """
    try:
        _re.compile(payload.pattern)
    except _re.error as exc:
        return ValidateRegexOut(ok=False, error=str(exc))
    return ValidateRegexOut(ok=True)


@router.post("/filters/apply-now", response_model=ApplyNowOut)
async def apply_filters_now(
    dry_run: bool = Query(True),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    fits_root = FsPath(app_settings.fits_data_path)
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    general = (row.general if row else {}) or {}
    try:
        cfg = ScanFilterConfig.from_settings(general, fits_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Pull file paths and evaluate in Python (keeps rule logic in one place)
    paths_result = await session.execute(select(Image.id, Image.file_path))
    matched_ids: list = []
    sample_paths: list[str] = []
    _SAMPLE_LIMIT = 20
    for image_id, file_path in paths_result.all():
        if not file_path:
            continue
        if not cfg.should_include_file(FsPath(file_path), fits_root):
            matched_ids.append(image_id)
            if len(sample_paths) < _SAMPLE_LIMIT:
                sample_paths.append(file_path)

    if not dry_run and matched_ids:
        await session.execute(
            text("DELETE FROM images WHERE id = ANY(:ids)"),
            {"ids": matched_ids},
        )
        await session.commit()

        import time as _time
        async with async_redis() as r:
            await append_activity(r, {
                "type": "scan_filters_applied",
                "message": (
                    f"Scan filters applied: {len(matched_ids)} image row"
                    f"{'s' if len(matched_ids) != 1 else ''} removed "
                    f"(by {user.username})"
                ),
                "details": {
                    "removed": len(matched_ids),
                    "by_user": user.username,
                },
                "timestamp": _time.time(),
            })
        logger.info(
            "scan_filters_applied: removed %d image rows by user %s",
            len(matched_ids), user.username,
        )

    return ApplyNowOut(
        dry_run=dry_run,
        matched=len(matched_ids),
        sample_paths=sample_paths,
    )


@router.get("/browse", response_model=list[BrowseEntry])
async def browse_folders(
    path: str | None = Query(None),
    user: User = Depends(require_admin),
):
    fits_root = FsPath(app_settings.fits_data_path).resolve()

    # Reject relative paths so we never resolve against the process CWD.
    if path is not None:
        candidate = FsPath(path)
        if not candidate.is_absolute():
            raise HTTPException(status_code=400, detail="path must be absolute")
        target = candidate.resolve()
    else:
        target = fits_root

    try:
        target.relative_to(fits_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside configured data path")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")

    entries: list[BrowseEntry] = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    # Do NOT follow symlinks: a symlink inside fits_root
                    # could otherwise point outside and enumerate host dirs.
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    # Defence in depth: re-check containment on the resolved
                    # child so a TOCTOU race or mount change cannot escape.
                    resolved_child = FsPath(entry.path).resolve()
                    try:
                        resolved_child.relative_to(fits_root)
                    except ValueError:
                        continue
                    has_children = False
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub in sub_it:
                                if sub.is_dir(follow_symlinks=False):
                                    has_children = True
                                    break
                    except OSError:
                        pass
                    entries.append(BrowseEntry(
                        name=entry.name,
                        path=str(resolved_child),
                        has_children=has_children,
                    ))
                except OSError:
                    continue
    except OSError as exc:
        logger.warning("browse_folders: cannot read %s: %s", target, exc)
        raise HTTPException(status_code=500, detail="cannot read directory")
    entries.sort(key=lambda e: e.name.lower())
    return entries
