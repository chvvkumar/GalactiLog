import asyncio
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Image, Target, User, UserSettings, SETTINGS_ROW_ID
from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.mosaic import (
    AcceptSuggestionRequest,
    AvailablePanelLabel,
    MosaicCreate, MosaicUpdate, MosaicPanelCreate,
    MosaicPanelBatchItem, MosaicPanelBatchRequest,
    MosaicSummary, MosaicDetailResponse, PanelStats, MosaicSuggestionResponse,
    PanelThumbnail,
    PanelSessionsResponse, PanelSessionInfo, SessionStatusUpdate,
    MosaicStatusResponse, OkResponse, PanelCreateResponse,
    DetectionStartedResponse, DetectionStatusResponse,
)
from app.api.deps import get_current_user, require_admin
from app.services.mosaic_composite import build_mosaic_composite, find_default_filter
from app.services.mosaic_detection import (
    load_mosaic_keywords,
    retro_link_panel_images as _retro_link_panel_images,
)
from app.services.mosaic_stats import (
    get_panel_included_dates as _get_panel_included_dates,
    panel_stats as _panel_stats,
    batch_panel_stats as _batch_panel_stats,
    list_mosaic_summaries,
)
from app.services.mosaic_suggestions import (
    strip_year_suffix,
    object_pattern_for_label,
    list_pending_suggestions,
    accept_suggestion_panels,
    _ilike_pattern_matches,
)

router = APIRouter(prefix="/mosaics", tags=["mosaics"])


@router.post("/detect", response_model=DetectionStartedResponse, status_code=202)
async def trigger_detection(
    user: User = Depends(require_admin),
):
    """Dispatch mosaic panel detection to Celery and return immediately.

    Detection loads the LIGHT-frame headers of the whole catalog and does
    CPU-bound grouping, so running it inline blocked the event loop and could
    race the scan-triggered detection task (both delete and re-insert pending
    suggestions). It now runs in the worker under MOSAIC_DETECT_LOCK, which
    serializes it against the scan-triggered run. The caller polls
    ``GET /mosaics/detect/status`` with the returned task id.
    """
    from app.worker.tasks import detect_mosaic_panels_task

    task = detect_mosaic_panels_task.delay()
    return {"status": "started", "task_id": task.id}


@router.get("/detect/status", response_model=DetectionStatusResponse)
async def detection_status(
    task_id: str,
    user: User = Depends(get_current_user),
):
    """Report the state of a dispatched detection task.

    Returns the Celery task state; once SUCCESS, ``new_suggestions`` carries the
    count the task found so the UI can refresh its suggestion list.
    """
    from app.worker.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    state = result.state
    new_suggestions: int | None = None
    if state == "SUCCESS":
        payload = result.result
        if isinstance(payload, dict):
            new_suggestions = payload.get("new_suggestions")
    return {"state": state, "new_suggestions": new_suggestions}


# NOTE: This endpoint MUST be defined BEFORE the /{mosaic_id} routes
# to avoid FastAPI interpreting "suggestions" as a UUID path parameter.
@router.get("/suggestions", response_model=list[MosaicSuggestionResponse])
async def get_suggestions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await list_pending_suggestions(session)


@router.post("/suggestions/{suggestion_id}/accept", response_model=MosaicSummary)
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    body: AcceptSuggestionRequest = AcceptSuggestionRequest(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    suggestion = await session.get(MosaicSuggestion, suggestion_id)
    if not suggestion or suggestion.status != "pending":
        raise HTTPException(404, "Suggestion not found or already resolved")

    selected = set(body.selected_panels) if body.selected_panels is not None else None
    keywords = await load_mosaic_keywords(session)

    # Guard against a duplicate mosaic name BEFORE inserting. A stale bulk
    # "accept all" can have a sibling suggestion that already created this
    # mosaic; without this pre-check the flush raises a UniqueViolationError on
    # mosaics_name_key and surfaces as an unhandled 500. Pre-checking keeps the
    # session usable (no failed flush to roll back). Case-insensitive to mirror
    # the existing-mosaic-name handling in get_suggestions.
    existing = (await session.execute(
        select(Mosaic).where(func.upper(Mosaic.name) == suggestion.suggested_name.upper())
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A mosaic named '{suggestion.suggested_name}' already exists",
        )

    mosaic, created = await accept_suggestion_panels(session, suggestion, selected, keywords)

    suggestion.status = "accepted"
    await session.commit()

    return MosaicSummary(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        panel_count=created,
        total_integration_seconds=0,
        total_frames=0,
        completion_pct=0,
        needs_review=False,
    )


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=MosaicStatusResponse)
async def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    suggestion = await session.get(MosaicSuggestion, suggestion_id)
    if not suggestion or suggestion.status != "pending":
        raise HTTPException(404, "Suggestion not found or already resolved")
    suggestion.status = "rejected"
    await session.commit()
    return {"status": "ok"}


@router.post("/clear-reviews", response_model=OkResponse)
async def clear_all_reviews(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    from sqlalchemy import update
    await session.execute(
        update(Mosaic).where(Mosaic.needs_review == True).values(needs_review=False)
    )
    await session.commit()
    return {"ok": True}


@router.get("", response_model=list[MosaicSummary])
async def list_mosaics(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await list_mosaic_summaries(session)


@router.post("", response_model=MosaicSummary)
async def create_mosaic(
    body: MosaicCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    mosaic = Mosaic(name=body.name, notes=body.notes)
    session.add(mosaic)
    await session.flush()

    for p in body.panels:
        obj_pattern = p.object_pattern
        if obj_pattern is None:
            base = strip_year_suffix(mosaic.name)
            obj_pattern = object_pattern_for_label(p.panel_label, base)
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=p.target_id,
            panel_label=p.panel_label,
            object_pattern=obj_pattern,
        )
        session.add(panel)
        await session.flush()
        await _retro_link_panel_images(session, panel.id, p.target_id, p.panel_label)

    await session.commit()
    return MosaicSummary(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        panel_count=len(body.panels),
        total_integration_seconds=0,
        total_frames=0,
        completion_pct=0,
    )


@router.get("/{mosaic_id}", response_model=MosaicDetailResponse)
async def get_mosaic_detail(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(Mosaic).options(
        selectinload(Mosaic.panels).selectinload(MosaicPanel.target)
    ).where(Mosaic.id == mosaic_id)
    mosaic = (await session.execute(q)).scalar_one_or_none()
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    sorted_panels = sorted(mosaic.panels, key=lambda x: x.sort_order)

    # Separate simple panels (no object_pattern) for batch query
    simple = [p for p in sorted_panels if not p.object_pattern]
    batch_stats = await _batch_panel_stats(simple, session) if simple else {}

    panels = []
    total_int = 0
    total_frames = 0
    for p in sorted_panels:
        if str(p.id) in batch_stats:
            ps = batch_stats[str(p.id)]
        else:
            ps = await _panel_stats(p, session)
        total_int += ps.total_integration_seconds
        total_frames += ps.total_frames
        panels.append(ps)

    # Gather included session dates per panel for filter scoping
    panel_included_dates = await _get_panel_included_dates(sorted_panels, session)

    default_filter, available_filters = await find_default_filter(
        sorted_panels, session, panel_included_dates=panel_included_dates,
    )

    # Load custom column values for this mosaic
    cv_q = (
        select(CustomColumnValue.mosaic_id, CustomColumn.slug, CustomColumnValue.value)
        .join(CustomColumn)
        .where(
            CustomColumnValue.mosaic_id == mosaic.id,
            CustomColumn.applies_to == AppliesTo.mosaic,
        )
    )
    cv_rows = (await session.execute(cv_q)).all()
    custom_values = {slug: val for _, slug, val in cv_rows} if cv_rows else None

    # Panel labels parsed at ingest for this mosaic's targets that have no
    # backing MosaicPanel row yet. This is the "accepted mosaics frozen" fix:
    # the offline detection job skips targets already in a MosaicPanel, but
    # ingest-time parsing (Task 1/2) still stamps Image.panel_label on every
    # new frame, leaving Image.panel_id NULL when no MosaicPanel matches.
    # Surfacing only; each entry carries its target_id so a client can
    # promote the label to a real panel via POST /{mosaic_id}/panels.
    target_ids = {p.target_id for p in sorted_panels}
    existing_labels_by_target: dict[uuid.UUID, set[str]] = defaultdict(set)
    for p in sorted_panels:
        existing_labels_by_target[p.target_id].add(p.panel_label)

    available_panel_labels: list[AvailablePanelLabel] = []
    if target_ids:
        avail_q = (
            select(Image.resolved_target_id, Image.panel_label)
            .where(
                Image.resolved_target_id.in_(target_ids),
                Image.panel_id.is_(None),
                Image.panel_label.isnot(None),
            )
            .distinct()
        )
        avail_rows = (await session.execute(avail_q)).all()
        pairs = set()
        for target_id, panel_label in avail_rows:
            # Defensive guard: panel_id IS NULL should already imply no
            # MosaicPanel matched this (target_id, panel_label), but skip any
            # exact duplicate of an existing panel's label rather than
            # double-counting it as "available".
            if panel_label in existing_labels_by_target.get(target_id, ()):
                continue
            pairs.add((panel_label, str(target_id)))
        available_panel_labels = [
            AvailablePanelLabel(label=label, target_id=target_id)
            for label, target_id in sorted(pairs)
        ]

    return MosaicDetailResponse(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        rotation_angle=mosaic.rotation_angle,
        pixel_coords=mosaic.pixel_coords,
        total_integration_seconds=total_int,
        total_frames=total_frames,
        panels=panels,
        available_filters=available_filters,
        default_filter=default_filter,
        needs_review=mosaic.needs_review,
        custom_values=custom_values,
        available_panel_labels=available_panel_labels,
    )


@router.get("/{mosaic_id}/composite")
async def get_mosaic_composite(
    mosaic_id: str,
    filter: str | None = None,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Generate and return a composite mosaic image as JPEG."""
    mosaic = (
        await session.execute(
            select(Mosaic)
            .where(Mosaic.id == mosaic_id)
            .options(selectinload(Mosaic.panels).selectinload(MosaicPanel.target))
        )
    ).scalars().first()

    if not mosaic:
        raise HTTPException(status_code=404, detail="Mosaic not found")

    panels = sorted(mosaic.panels, key=lambda p: p.sort_order)
    panel_included_dates = await _get_panel_included_dates(panels, session)

    try:
        jpeg_bytes = await build_mosaic_composite(
            mosaic_id=str(mosaic.id),
            panels=panels,
            session=session,
            filter_name=filter,
            panel_included_dates=panel_included_dates,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.get("/{mosaic_id}/panels/thumbnails", response_model=list[PanelThumbnail])
async def get_panel_thumbnails(
    mosaic_id: uuid.UUID,
    filter: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Generate per-panel thumbnails for a specific filter using quality scoring."""
    from pathlib import Path
    from app.services.mosaic_composite import (
        select_best_frame_for_filter,
        generate_panel_thumbnail,
        _get_cached_thumbnail,
        _set_cached_thumbnail,
    )
    import io

    q = select(Mosaic).options(
        selectinload(Mosaic.panels).selectinload(MosaicPanel.target)
    ).where(Mosaic.id == mosaic_id)
    mosaic = (await session.execute(q)).scalar_one_or_none()
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    sorted_panels = sorted(mosaic.panels, key=lambda p: p.sort_order)
    panel_included_dates = await _get_panel_included_dates(sorted_panels, session)

    results = []
    for panel in sorted_panels:
        pid = str(panel.id)
        included_dates = panel_included_dates.get(pid)
        result = await select_best_frame_for_filter(
            panel.target_id, panel.object_pattern, filter, session,
            included_dates=included_dates, panel_label=panel.panel_label,
        )
        if not result:
            results.append({
                "panel_id": str(panel.id),
                "thumbnail_url": None,
                "frame_id": None,
                "score": None,
                "filter_used": filter,
            })
            continue

        frame, frame_score = result
        if not frame.file_path:
            results.append({
                "panel_id": str(panel.id),
                "thumbnail_url": None,
                "frame_id": None,
                "score": None,
                "filter_used": filter,
            })
            continue

        pid = str(panel.id)
        results.append({
            "panel_id": pid,
            "thumbnail_url": f"/api/mosaics/{mosaic_id}/panels/{pid}/thumbnail?filter={filter}",
            "frame_id": str(frame.id),
            "score": round(frame_score, 4),
            "filter_used": filter,
        })

    return results


@router.get("/{mosaic_id}/panels/{panel_id}/thumbnail")
async def get_panel_thumbnail_image(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    filter: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Serve a single panel thumbnail JPEG for a specific filter."""
    from pathlib import Path
    from app.services.mosaic_composite import (
        select_best_frame_for_filter,
        generate_panel_thumbnail,
        _get_cached_thumbnail,
        _set_cached_thumbnail,
    )
    import io

    panel = (await session.execute(
        select(MosaicPanel).where(
            MosaicPanel.id == panel_id,
            MosaicPanel.mosaic_id == mosaic_id,
        )
    )).scalar_one_or_none()
    if not panel:
        raise HTTPException(404, "Panel not found")

    pid = str(panel.id)
    cached = _get_cached_thumbnail(pid, filter)
    if cached:
        return Response(content=cached, media_type="image/jpeg")

    panel_included_dates = await _get_panel_included_dates([panel], session)
    included_dates = panel_included_dates.get(pid)

    result = await select_best_frame_for_filter(
        panel.target_id, panel.object_pattern, filter, session,
        included_dates=included_dates, panel_label=panel.panel_label,
    )
    if not result or not result[0].file_path:
        raise HTTPException(404, f"No frames for filter '{filter}' in this panel")
    frame = result[0]

    fits_path = Path(frame.file_path)
    if not fits_path.exists():
        raise HTTPException(404, "FITS file not found")

    try:
        img, _ = await asyncio.to_thread(generate_panel_thumbnail, fits_path, 800)
    except Exception as e:
        raise HTTPException(422, f"Thumbnail generation failed: {e}")

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    jpeg_bytes = buf.getvalue()

    _set_cached_thumbnail(pid, filter, jpeg_bytes)
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.put("/{mosaic_id}", response_model=MosaicStatusResponse)
async def update_mosaic(
    mosaic_id: uuid.UUID,
    body: MosaicUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")
    if body.name is not None:
        mosaic.name = body.name
    if body.notes is not None:
        mosaic.notes = body.notes
    if body.rotation_angle is not None:
        mosaic.rotation_angle = body.rotation_angle
    if body.pixel_coords is not None:
        mosaic.pixel_coords = body.pixel_coords
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}", response_model=MosaicStatusResponse)
async def delete_mosaic(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    # Clean up accepted suggestions matching this mosaic name so detection
    # can re-suggest them. Strip year suffix for base_name matching too.
    base = strip_year_suffix(mosaic.name)
    stale_q = select(MosaicSuggestion).where(
        MosaicSuggestion.status == "accepted",
        or_(
            MosaicSuggestion.suggested_name == mosaic.name,
            MosaicSuggestion.base_name == base,
        ),
    )
    stale_suggestions = (await session.execute(stale_q)).scalars().all()
    for s in stale_suggestions:
        await session.delete(s)

    await session.delete(mosaic)
    await session.commit()
    return {"status": "ok"}


@router.post("/{mosaic_id}/panels", response_model=PanelCreateResponse)
async def add_panel(
    mosaic_id: uuid.UUID,
    body: MosaicPanelCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    # Check this exact target+label combo doesn't already exist in this mosaic
    existing = (await session.execute(
        select(MosaicPanel).where(
            MosaicPanel.mosaic_id == mosaic_id,
            MosaicPanel.target_id == body.target_id,
            MosaicPanel.panel_label == body.panel_label,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "This panel already exists in the mosaic")

    # Derive object_pattern to filter frames by FITS OBJECT header,
    # matching the logic used in accept_suggestion.
    obj_pattern = body.object_pattern
    if obj_pattern is None:
        # Strip year suffix from mosaic name for pattern matching
        base = strip_year_suffix(mosaic.name)
        obj_pattern = object_pattern_for_label(body.panel_label, base)

    panel = MosaicPanel(
        mosaic_id=mosaic_id,
        target_id=body.target_id,
        panel_label=body.panel_label,
        object_pattern=obj_pattern,
    )
    session.add(panel)
    await session.flush()
    # Claim frames ingested before this panel existed so its stats are
    # populated immediately (same transaction as the panel insert).
    await _retro_link_panel_images(session, panel.id, body.target_id, body.panel_label)
    await session.commit()
    return {"status": "ok", "panel_id": str(panel.id)}


@router.put("/{mosaic_id}/panels/batch", response_model=list[PanelStats])
async def batch_update_panels(
    mosaic_id: uuid.UUID,
    body: MosaicPanelBatchRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update multiple panels in a single transaction (positions, rotation, flip)."""
    q = (
        select(Mosaic)
        .options(selectinload(Mosaic.panels).selectinload(MosaicPanel.target))
        .where(Mosaic.id == mosaic_id)
    )
    mosaic = (await session.execute(q)).scalar_one_or_none()
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    # Persist mosaic-level rotation_angle if provided
    if body.rotation_angle is not None:
        mosaic.rotation_angle = body.rotation_angle

    panel_map = {p.id: p for p in mosaic.panels}

    # Validate all panel_ids belong to this mosaic
    for item in body.panels:
        if item.panel_id not in panel_map:
            raise HTTPException(404, f"Panel {item.panel_id} not found in mosaic")

    # Apply partial updates
    for item in body.panels:
        panel = panel_map[item.panel_id]
        if item.grid_row is not None:
            panel.grid_row = item.grid_row
        if item.grid_col is not None:
            panel.grid_col = item.grid_col
        if item.rotation is not None:
            if item.rotation not in (0, 90, 180, 270):
                raise HTTPException(400, "rotation must be 0, 90, 180, or 270")
            panel.rotation = item.rotation
        if item.flip_h is not None:
            panel.flip_h = item.flip_h

    await session.flush()

    # Build response with panel stats
    sorted_panels = sorted(mosaic.panels, key=lambda x: x.sort_order)
    simple = [p for p in sorted_panels if not p.object_pattern]
    batch_stats = await _batch_panel_stats(simple, session) if simple else {}

    result = []
    for p in sorted_panels:
        if str(p.id) in batch_stats:
            ps = batch_stats[str(p.id)]
        else:
            ps = await _panel_stats(p, session)
        result.append(ps)

    await session.commit()
    return result


@router.delete("/{mosaic_id}/panels/{panel_id}", response_model=MosaicStatusResponse)
async def remove_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    panel = await session.get(MosaicPanel, panel_id)
    if not panel or panel.mosaic_id != mosaic_id:
        raise HTTPException(404, "Panel not found")
    await session.delete(panel)
    await session.commit()
    return {"status": "ok"}


@router.get("/{mosaic_id}/panels/{panel_id}/sessions", response_model=PanelSessionsResponse)
async def get_panel_sessions(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List all sessions (included + available) for a panel with stats.

    Pattern panels (object_pattern set) are scoped by the exact
    `Image.panel_id == panel.id` join (Phase 5 Task 3) instead of an
    ILIKE-against-OBJECT prefilter plus a Python object_matches_panel recheck
    (AUD-008) -- Image.panel_id is assigned at ingest time / by the 0018
    backfill from the same tokenizer that built object_pattern, so the join
    is exact by construction. No resolved_target_id leg for pattern panels:
    panel_id is the authoritative membership column, and requiring target
    agreement would zero the panel's sessions when an unmerge moves images
    back to an original target while the panel still points at the merged
    one. Simple panels (no object_pattern) are unchanged: they still count
    every LIGHT frame of the target via resolved_target_id alone (that IS
    their membership mechanism), preserving existing behavior.
    """
    panel_q = (
        select(MosaicPanel)
        .where(MosaicPanel.id == panel_id, MosaicPanel.mosaic_id == mosaic_id)
    )
    panel = (await session.execute(panel_q)).scalar_one_or_none()
    if not panel:
        raise HTTPException(404, "Panel not found")

    # Get existing membership records
    existing_q = select(MosaicPanelSession).where(MosaicPanelSession.panel_id == panel_id)
    existing = {
        str(r.session_date): r.status
        for r in (await session.execute(existing_q)).scalars().all()
    }

    # Get all session dates from images
    if panel.object_pattern:
        base_filter = [
            Image.panel_id == panel.id,
            Image.image_type == "LIGHT",
        ]
    else:
        base_filter = [
            Image.resolved_target_id == panel.target_id,
            Image.image_type == "LIGHT",
        ]

    img_q = (
        select(
            Image.session_date,
            Image.filter_used,
            func.count(Image.id).label("frames"),
            func.sum(Image.exposure_time).label("integration"),
        )
        .where(*base_filter)
        .where(Image.session_date.isnot(None))
        .group_by(Image.session_date, Image.filter_used)
    )
    rows = (await session.execute(img_q)).all()

    # Aggregate by session_date
    date_data: dict[str, dict] = {}
    for row in rows:
        ds = str(row.session_date)
        if ds not in date_data:
            date_data[ds] = {"frames": 0, "integration": 0.0, "filters": {}}
        date_data[ds]["frames"] += row.frames
        date_data[ds]["integration"] += row.integration or 0
        if row.filter_used:
            date_data[ds]["filters"][row.filter_used] = {
                "frames": row.frames,
                "integration": row.integration or 0,
            }

    sessions_list = []
    for ds in sorted(date_data.keys(), reverse=True):
        status = existing.get(ds, "available")
        d = date_data[ds]
        sessions_list.append(PanelSessionInfo(
            session_date=ds,
            status=status,
            total_frames=d["frames"],
            total_integration_seconds=d["integration"],
            filters=d["filters"],
        ))

    return PanelSessionsResponse(
        panel_id=str(panel_id),
        panel_label=panel.panel_label,
        sessions=sessions_list,
    )


@router.put("/{mosaic_id}/panels/{panel_id}/sessions", response_model=MosaicStatusResponse)
async def update_panel_sessions(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    body: SessionStatusUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Bulk include/exclude sessions for a panel."""
    from datetime import date as date_type

    panel_q = (
        select(MosaicPanel)
        .where(MosaicPanel.id == panel_id, MosaicPanel.mosaic_id == mosaic_id)
    )
    panel = (await session.execute(panel_q)).scalar_one_or_none()
    if not panel:
        raise HTTPException(404, "Panel not found")

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Bulk upsert included sessions
    if body.include:
        include_values = [
            {"panel_id": panel_id, "session_date": date_type.fromisoformat(ds), "status": "included"}
            for ds in body.include
        ]
        include_stmt = pg_insert(MosaicPanelSession).values(include_values)
        include_stmt = include_stmt.on_conflict_do_update(
            constraint="uq_mosaic_panel_sessions_panel_date",
            set_={"status": "included"},
        )
        await session.execute(include_stmt)

    # Bulk upsert excluded (available) sessions -- only update existing rows
    if body.exclude:
        from sqlalchemy import update
        exclude_dates = [date_type.fromisoformat(ds) for ds in body.exclude]
        await session.execute(
            update(MosaicPanelSession)
            .where(
                MosaicPanelSession.panel_id == panel_id,
                MosaicPanelSession.session_date.in_(exclude_dates),
            )
            .values(status="available")
        )

    mosaic = await session.get(Mosaic, mosaic_id)
    if mosaic and mosaic.needs_review:
        mosaic.needs_review = False

    await session.commit()
    return {"status": "ok"}
