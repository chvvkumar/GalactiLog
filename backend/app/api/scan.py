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
from app.models import Image
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
import re as _re

from app.schemas.scan_filters import (
    ScanFiltersIn, ScanFiltersOut, TestPathIn, TestPathOut, BrowseEntry, ApplyNowOut,
    ValidateRegexIn, ValidateRegexOut,
)
from app.schemas.scan import (
    ScanQueueResponse,
    RegenerateThumbnailsResponse,
    ScanStateResponse,
    ScanStopResponse,
    ScanResetResponse,
    ScanAcceptResponse,
    RebuildStatusResponse,
    DbSummaryResponse,
    BackfillCsvResponse,
)
from app.services.scan_filters import ScanFilterConfig
from app.services.activity import emit as _emit_activity
from app.services.scan_state import (
    get_scan_state, get_failed_files, start_scanning, set_ingesting, set_idle, reset_scan,
    get_rebuild_state, request_cancel, mark_scan_dispatched,
)
from app.worker.tasks import regenerate_thumbnail, run_scan, rebuild_targets, smart_rebuild_targets, retry_unresolved, backfill_csv_metrics, generate_reference_thumbnails, purge_and_regenerate_thumbnails, regenerate_missing_thumbnails, backfill_catalog_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("", response_model=ScanQueueResponse)
async def trigger_scan(
    include_calibration: bool = Query(False, description="Include calibration frames (BIAS, DARK, FLAT)"),
    force_orphan_cleanup: bool = Query(False, description="Bypass the 50%-missing safety threshold and remove all orphaned records (one-time, for deliberate bulk deletions)"),
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

            # Mark a scan as dispatched *before* releasing the lock below, so a
            # second request that acquires the lock right after this one still
            # sees an active scan even though the queued run_scan task hasn't
            # been picked up by a worker yet and started_scanning_sync() hasn't
            # run (AUD-016).
            await mark_scan_dispatched(r)
            run_scan.delay(include_calibration=include_calibration, force_orphan_cleanup=force_orphan_cleanup)

            return {"status": "accepted", "message": "Scan queued - check /scan/status for progress"}
        finally:
            await r.delete("scan:lock")


@router.post("/regenerate-thumbnails", response_model=RegenerateThumbnailsResponse)
async def regenerate_thumbnails(
    purge: bool = False,
    missing_only: bool = False,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Queue images for thumbnail regeneration.

    When missing_only=True, only regenerate thumbnails whose files are
    missing from disk (fast: checks file existence then queues the gaps).
    When purge=True, delete all existing thumbnail files first, then
    regenerate everything.  Default: regenerate all without deleting first.
    """
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            return {"status": "already_running", **state.to_dict()}

        await start_scanning(r)

        if missing_only:
            task = regenerate_missing_thumbnails.delay()
            return {
                "status": "accepted",
                "message": "Queued: checking for missing thumbnails",
                "task_id": task.id,
            }

        if purge:
            task = purge_and_regenerate_thumbnails.delay()
            return {
                "status": "accepted",
                "message": "Queued: delete and regenerate all thumbnails",
                "task_id": task.id,
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


@router.get("/summary")
async def get_scan_summary(_user=Depends(get_current_user)):
    """Return the last scan summary from Redis, or null if not available."""
    import json as _json
    async with async_redis() as r:
        raw = await r.get("galactilog:scan_summary")
    if raw:
        return _json.loads(raw)
    return None


@router.get("/status", response_model=ScanStateResponse)
async def scan_status(user: User = Depends(get_current_user)):
    """Return current scan state from Redis."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        result = state.to_dict()
        if state.failed > 0:
            result["failed_files"] = await get_failed_files(r)
        return result


@router.post("/stop", response_model=ScanStopResponse)
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


@router.post("/reset", response_model=ScanResetResponse)
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


@router.post("/rebuild-targets", response_model=ScanAcceptResponse)
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

        task = rebuild_targets.delay()
        return {"status": "accepted", "message": "Target rebuild queued as background task", "task_id": task.id}


@router.post("/smart-rebuild-targets", response_model=ScanAcceptResponse)
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

        task = smart_rebuild_targets.delay(manual=True)
        return {"status": "accepted", "message": "Smart rebuild queued as background task", "task_id": task.id}


@router.post("/retry-unresolved", response_model=ScanAcceptResponse)
async def trigger_retry_unresolved(user: User = Depends(require_admin)):
    """Clear SIMBAD negative cache and SESAME cache, then re-resolve unresolved targets."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        task = retry_unresolved.delay()
        return {"status": "accepted", "message": "Retry unresolved queued as background task", "task_id": task.id}


@router.post("/backfill-catalog-identity", response_model=ScanAcceptResponse)
async def trigger_backfill_catalog_identity(user: User = Depends(require_admin)):
    """Repair corrupted SIMBAD cache and re-link catalog orphans by identity.

    Re-runs the shared catalog-identity matcher over unlinked light frames and
    attaches those that now resolve to an existing target. One-time after deploy,
    safely re-runnable. Runs as a background Celery task.
    """
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        task = backfill_catalog_identity.delay()
        return {"status": "accepted", "message": "Catalog-identity backfill queued as background task", "task_id": task.id}


@router.post("/generate-reference-thumbnails", response_model=ScanAcceptResponse)
async def trigger_reference_thumbnails(force: bool = False, user: User = Depends(require_admin)):
    """Fetch DSS reference thumbnails from SkyView for all targets with coordinates."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            raise HTTPException(
                status_code=409,
                detail="A scan is already running. Wait for it to complete first.",
            )

        task = generate_reference_thumbnails.delay(force=force)
        return {"status": "accepted", "message": "Reference thumbnail generation queued as background task", "task_id": task.id}


@router.post("/backfill-csv", response_model=BackfillCsvResponse)
async def backfill_csv_metrics_endpoint(user: User = Depends(require_admin)):
    """Backfill Image rows with metrics from N.I.N.A. CSV files."""
    async with async_redis() as r:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            return {"status": "already_running", "state": state.state}
        backfill_csv_metrics.delay()
        return {"status": "accepted"}


@router.get("/rebuild-status", response_model=RebuildStatusResponse)
async def rebuild_status(user: User = Depends(get_current_user)):
    """Return current rebuild task state from Redis."""
    async with async_redis() as r:
        state = await get_rebuild_state(r)
        return state.to_dict()


@router.get("/db-summary", response_model=DbSummaryResponse)
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
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'simbad') AS cached_simbad,
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'simbad' AND negative) AS cached_negative,
            (SELECT COUNT(*) FROM merge_candidates WHERE status = 'pending') AS pending_merges,
            (SELECT COUNT(*) FROM images WHERE detected_stars IS NOT NULL) AS csv_enriched,
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'vizier') AS cached_vizier,
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'vizier' AND negative) AS cached_vizier_negative,
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'sesame') AS cached_sesame,
            (SELECT COUNT(*) FROM catalog_cache WHERE source = 'sesame' AND negative) AS cached_sesame_negative
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

        await _emit_activity(
            session,
            category="scan",
            severity="info",
            event_type="scan_filters_applied",
            message=(
                f"Scan filters applied: {len(matched_ids)} image row"
                f"{'s' if len(matched_ids) != 1 else ''} removed "
                f"(by {user.username})"
            ),
            details={"removed": len(matched_ids), "by_user": user.username},
            actor=user.username,
        )
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
