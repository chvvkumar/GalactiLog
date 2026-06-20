import asyncio
import re
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func, or_, text
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
    MosaicCreate, MosaicUpdate, MosaicPanelCreate, MosaicPanelUpdate,
    MosaicPanelBatchItem, MosaicPanelBatchRequest,
    MosaicSummary, MosaicDetailResponse, PanelStats, MosaicSuggestionResponse,
    SuggestionPreviewPanel,
    PanelThumbnail,
    PanelSessionsResponse, PanelSessionInfo, SessionStatusUpdate,
    StatusResponse, OkResponse, DetectionResponse, PanelCreateResponse,
)
from app.api.deps import get_current_user, require_admin
from app.services.mosaic_composite import build_mosaic_composite, find_default_filter
from app.services.mosaic_stats import (
    get_panel_included_dates as _get_panel_included_dates,
    panel_stats as _panel_stats,
    batch_panel_stats as _batch_panel_stats,
    list_mosaic_summaries,
)

router = APIRouter(prefix="/mosaics", tags=["mosaics"])


def _ilike_pattern_matches(pattern: str, value: str) -> bool:
    """Match an SQL ILIKE pattern against a value with the SAME semantics SQL
    uses: '%' is an ordered, possibly-empty gap and '_' a single char. Literal
    segments must appear in order and contiguously (no reordering).

    A naive "split on % and check each segment is a substring" test is wrong:
    for "%Sh2 119%1%" the segments are ["sh2 119", "1"], and "Sh2 119 Panel 2"
    contains both ("1" lives inside "119"), so it would falsely match Panel 1.
    Translating to an anchored regex preserves order and avoids that.
    """
    if value is None:
        return False
    regex_parts = []
    for ch in pattern:
        if ch == "%":
            regex_parts.append(".*")
        elif ch == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(ch))
    regex = "^" + "".join(regex_parts) + "$"
    return re.match(regex, value, re.IGNORECASE | re.DOTALL) is not None


@router.post("/detect", response_model=DetectionResponse)
async def trigger_detection(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    from app.services.mosaic_detection import detect_mosaic_panels

    settings = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings.general if settings else {}
    gap_days = general.get("mosaic_campaign_gap_days", 0)

    count = await detect_mosaic_panels(session, gap_days=gap_days)
    return {"status": "ok", "new_suggestions": count}


# NOTE: This endpoint MUST be defined BEFORE the /{mosaic_id} routes
# to avoid FastAPI interpreting "suggestions" as a UUID path parameter.
@router.get("/suggestions", response_model=list[MosaicSuggestionResponse])
async def get_suggestions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from app.schemas.mosaic import SuggestionPanelSession

    q = select(MosaicSuggestion).where(MosaicSuggestion.status == "pending")
    all_pending = (await session.execute(q)).scalars().all()

    # Filter out suggestions whose name already matches an existing mosaic
    existing_mosaic_names_q = select(Mosaic.name)
    existing_mosaic_names = {
        r[0].upper() for r in (await session.execute(existing_mosaic_names_q)).all()
    }
    rows = [r for r in all_pending if r.suggested_name.upper() not in existing_mosaic_names]

    # Resolve target names in batch
    all_ids = {t for r in rows for t in r.target_ids}
    name_map: dict[str, str] = {}
    if all_ids:
        tq = select(Target.id, Target.primary_name).where(Target.id.in_(all_ids))
        for tid, tname in (await session.execute(tq)).all():
            name_map[str(tid)] = tname

    def _thumb_url(thumbnail_path: str | None) -> str | None:
        if not thumbnail_path:
            return None
        filename = thumbnail_path.split("/")[-1].split("\\")[-1]
        return f"/thumbnails/{filename}"

    # Per-target fallback thumbnail in one query (avoid N+1). Reuses the panel
    # stats scheme: the most recent LIGHT frame with a thumbnail_path becomes
    # /thumbnails/{filename}. DISTINCT ON keeps one row per target. Used when a
    # panel has no object_pattern or no pattern-matching frame.
    thumb_map: dict[str, str] = {}
    if all_ids:
        thumb_q = (
            select(
                Image.resolved_target_id,
                Image.thumbnail_path,
            )
            .where(
                Image.resolved_target_id.in_(all_ids),
                Image.image_type == "LIGHT",
                Image.thumbnail_path.is_not(None),
            )
            .distinct(Image.resolved_target_id)
            .order_by(Image.resolved_target_id, Image.capture_date.desc())
        )
        for tid, thumb_path in (await session.execute(thumb_q)).all():
            url = _thumb_url(thumb_path)
            if url:
                thumb_map[str(tid)] = url

    # Per-(target, object_pattern) thumbnail resolution. Two panels can share one
    # target_id (SIMBAD merges "Veil Nebula Panel 1"/"Panel 2" into NGC 6960);
    # the per-target fallback would give both the same image. Resolve each panel
    # by the same (resolved_target_id + OBJECT ILIKE pattern) frame selection
    # that mosaic_stats/mosaic_composite use for accepted panels. Collect the
    # distinct pairs first so each is queried once (LIMIT 1, bounded by panel
    # count across pending suggestions).
    def _pattern_for_label(r, label: str) -> str | None:
        """Object pattern for a panel label, mirroring accept_suggestion."""
        if r.panel_patterns and label in r.panel_labels:
            idx = r.panel_labels.index(label)
            if idx < len(r.panel_patterns):
                return r.panel_patterns[idx]
        base = r.base_name or r.suggested_name
        num = label.split()[-1] if label.startswith("Panel ") else label
        return f"%{base}%Panel%{num}%"

    pattern_thumb_pairs: set[tuple[str, str]] = set()
    for r in rows:
        geometry = r.geometry or {}
        for gp in geometry.get("panels", []):
            tid = gp.get("target_id")
            if tid is None:
                continue
            pattern = _pattern_for_label(r, gp.get("label") or "")
            if pattern:
                pattern_thumb_pairs.add((str(tid), pattern))

    pattern_thumb_map: dict[tuple[str, str], str] = {}
    obj_col_thumb = Image.raw_headers["OBJECT"].astext
    for tid_str, pattern in pattern_thumb_pairs:
        pq = (
            select(Image.thumbnail_path)
            .where(
                Image.resolved_target_id == tid_str,
                Image.image_type == "LIGHT",
                Image.thumbnail_path.is_not(None),
                obj_col_thumb.ilike(pattern),
            )
            .order_by(Image.capture_date.desc())
            .limit(1)
        )
        thumb_path = (await session.execute(pq)).scalars().first()
        url = _thumb_url(thumb_path)
        if url:
            pattern_thumb_map[(tid_str, pattern)] = url

    # Build all OBJECT ILIKE patterns across every suggestion+panel,
    # then fetch session summaries in a single query instead of N queries.
    # Each pattern maps back to (suggestion index, panel label).
    pattern_map: dict[str, list[tuple[int, str]]] = {}  # pattern -> [(row_idx, label)]
    for idx, r in enumerate(rows):
        if r.panel_patterns:
            # Use pre-computed patterns stored at detection time
            for label, pattern in zip(r.panel_labels, r.panel_patterns):
                pattern_map.setdefault(pattern, []).append((idx, label))
        else:
            # Fallback for legacy suggestions without panel_patterns
            base = r.base_name or r.suggested_name
            for label in r.panel_labels:
                num = label.split()[-1] if label.startswith("Panel ") else label
                obj_pattern = f"%{base}%Panel%{num}%"
                pattern_map.setdefault(obj_pattern, []).append((idx, label))

    # Run one query with all patterns OR'd together
    all_patterns = list(pattern_map.keys())
    obj_col = Image.raw_headers["OBJECT"].astext
    session_rows_by_idx: dict[int, list[SuggestionPanelSession]] = defaultdict(list)

    if all_patterns:
        sq = (
            select(
                obj_col.label("obj"),
                Image.session_date.label("night"),
                Image.filter_used,
                func.count(Image.id).label("frames"),
                func.sum(Image.exposure_time).label("integration"),
            )
            .where(
                Image.image_type == "LIGHT",
                or_(*(obj_col.ilike(p) for p in all_patterns)),
            )
            .group_by("obj", "night", Image.filter_used)
            .order_by("obj", "night")
        )
        all_session_rows = (await session.execute(sq)).all()

        # Distribute each result row back to the suggestions whose pattern matches
        for row in all_session_rows:
            obj_val = row.obj or ""
            for pattern, mappings in pattern_map.items():
                # Match the ILIKE pattern with ordered, contiguous semantics so
                # "%Sh2 119%1%" hits "Sh2 119 Panel 1" but NOT "...Panel 2".
                if _ilike_pattern_matches(pattern, obj_val):
                    for row_idx, label in mappings:
                        session_rows_by_idx[row_idx].append(SuggestionPanelSession(
                            panel_label=label,
                            object_name=obj_val,
                            date=str(row.night) if row.night else "",
                            frames=row.frames,
                            integration_seconds=row.integration or 0,
                            filter_used=row.filter_used,
                        ))

    results = []
    for idx, r in enumerate(rows):
        all_sessions = session_rows_by_idx.get(idx, [])
        filtered_sessions = all_sessions
        other_count = 0

        if r.session_dates:
            campaign_dates = set()
            for dates in r.session_dates.values():
                campaign_dates.update(dates)
            filtered_sessions = [s for s in all_sessions if s.date in campaign_dates]
            other_count = len(all_sessions) - len(filtered_sessions)

        # Build preview panels from stored geometry. The frontend arranger
        # auto-arranges tiles, so grid_row/grid_col are left null here; only
        # thumbnail_url is resolved (batched above, no per-panel compute).
        preview_panels: list[SuggestionPreviewPanel] = []
        geometry = r.geometry or {}
        for gp in geometry.get("panels", []):
            tid = gp.get("target_id")
            if tid is None:
                continue
            tid_str = str(tid)
            label = gp.get("label") or ""
            pattern = _pattern_for_label(r, label)
            # Prefer the per-(target, pattern) frame so merged-target panels get
            # distinct thumbnails; fall back to the per-target latest thumbnail.
            thumb = None
            if pattern is not None:
                thumb = pattern_thumb_map.get((tid_str, pattern))
            if thumb is None:
                thumb = thumb_map.get(tid_str)
            preview_panels.append(SuggestionPreviewPanel(
                target_id=tid_str,
                panel_label=label,
                ra=gp.get("ra"),
                dec=gp.get("dec"),
                thumbnail_url=thumb,
                grid_row=None,
                grid_col=None,
            ))

        results.append(MosaicSuggestionResponse(
            id=str(r.id),
            suggested_name=r.suggested_name,
            base_name=r.base_name,
            target_ids=[str(t) for t in r.target_ids],
            panel_labels=r.panel_labels,
            panel_patterns=r.panel_patterns,
            target_names={str(t): name_map.get(str(t), "Unknown") for t in set(r.target_ids)},
            sessions=filtered_sessions,
            session_dates=r.session_dates,
            other_session_count=other_count,
            status=r.status,
            confidence=r.confidence,
            discovery_source=r.discovery_source,
            flags=list(r.flags) if r.flags else [],
            preview_panels=preview_panels,
        ))

    return results


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

    # Create the mosaic
    mosaic = Mosaic(name=suggestion.suggested_name)
    session.add(mosaic)
    await session.flush()

    from datetime import date as date_type

    # Create panels - multiple panels may share the same target_id
    # (SIMBAD often merges panel variants into one target)
    panel_num = 0
    created = 0
    for target_id, label in zip(suggestion.target_ids, suggestion.panel_labels):
        if selected is not None and label not in selected:
            continue
        # Use pre-computed pattern if available, else derive from base_name
        panel_idx = None
        for pi, pl in enumerate(suggestion.panel_labels):
            if pl == label:
                panel_idx = pi
                break
        if suggestion.panel_patterns and panel_idx is not None and panel_idx < len(suggestion.panel_patterns):
            obj_pattern = suggestion.panel_patterns[panel_idx]
        else:
            base = suggestion.base_name or suggestion.suggested_name
            num = label.split()[-1] if label.startswith("Panel ") else label
            obj_pattern = f"%{base}%Panel%{num}%"
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=target_id,
            panel_label=label,
            sort_order=panel_num,
            object_pattern=obj_pattern,
        )
        session.add(panel)
        await session.flush()  # get panel.id

        # Seed session membership from suggestion's session_dates
        campaign_dates = set()
        if suggestion.session_dates and label in suggestion.session_dates:
            for ds in suggestion.session_dates[label]:
                d = date_type.fromisoformat(ds)
                campaign_dates.add(d)
                session.add(MosaicPanelSession(
                    panel_id=panel.id,
                    session_date=d,
                    status="included",
                ))

        # Find additional sessions outside the campaign
        base_filter = [
            Image.resolved_target_id == target_id,
            Image.image_type == "LIGHT",
            Image.session_date.isnot(None),
        ]
        if obj_pattern:
            base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(obj_pattern))
        all_dates_q = select(func.distinct(Image.session_date)).where(*base_filter)
        all_dates = {r[0] for r in (await session.execute(all_dates_q)).all()}

        for d in all_dates:
            if d not in campaign_dates:
                session.add(MosaicPanelSession(
                    panel_id=panel.id,
                    session_date=d,
                    status="available",
                ))

        panel_num += 1
        created += 1

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


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=StatusResponse)
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
            num = p.panel_label.split()[-1] if p.panel_label.startswith("Panel ") else p.panel_label
            base = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*$', '', mosaic.name)
            obj_pattern = f"%{base}%Panel%{num}%"
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=p.target_id,
            panel_label=p.panel_label,
            object_pattern=obj_pattern,
        )
        session.add(panel)

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
            included_dates=included_dates,
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
        included_dates=included_dates,
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


@router.get("/{mosaic_id}/composite/debug")
async def get_mosaic_composite_debug(
    mosaic_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Debug endpoint: return layout data as JSON instead of image."""
    from app.services.mosaic_composite import (
        select_best_frame, _parse_ra, _parse_coord,
        PanelInfo, compute_panel_layout, generate_panel_thumbnail,
    )
    from pathlib import Path

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
    debug_panels = []
    panel_infos = []
    native_width = 800
    tile_w, tile_h = 800, 800

    for panel in panels:
        frame = await select_best_frame(panel.target_id, panel.object_pattern, session)
        if not frame or not frame.file_path:
            debug_panels.append({
                "label": panel.panel_label,
                "error": "no frame found",
            })
            continue

        headers = frame.raw_headers or {}
        ra_raw = headers.get("RA") or headers.get("OBJCTRA")
        dec_raw = headers.get("DEC") or headers.get("OBJCTDEC")
        ra = _parse_ra(ra_raw)
        dec = _parse_coord(dec_raw)

        fits_path = Path(frame.file_path)
        exists = fits_path.exists()
        if exists:
            try:
                tile_img, nw = await asyncio.to_thread(generate_panel_thumbnail, fits_path, 400)
                native_width = nw
                tile_w, tile_h = tile_img.size
            except Exception as e:
                exists = False

        info = {
            "label": panel.panel_label,
            "object_pattern": panel.object_pattern,
            "target_name": panel.target.primary_name if panel.target else None,
            "frame_id": str(frame.id),
            "file_path": frame.file_path,
            "file_exists": exists,
            "ra_raw": ra_raw,
            "dec_raw": dec_raw,
            "ra_deg": ra,
            "dec_deg": dec,
            "objctrot": headers.get("OBJCTROT"),
            "pierside": headers.get("PIERSIDE"),
            "focallen": headers.get("FOCALLEN"),
            "xpixsz": headers.get("XPIXSZ"),
            "median_hfr": frame.median_hfr,
        }
        debug_panels.append(info)

        if ra is not None and dec is not None and exists:
            panel_infos.append(PanelInfo(
                panel_id=panel.panel_label,
                ra=ra,
                dec=dec,
                objctrot=float(headers.get("OBJCTROT", 0)),
                pierside=str(headers.get("PIERSIDE", "West")),
                fits_path=frame.file_path,
                focallen=float(headers.get("FOCALLEN", 448)),
                xpixsz=float(headers.get("XPIXSZ", 3.76)),
            ))

    scale = tile_w / native_width if native_width > 0 else 1.0
    layout = compute_panel_layout(panel_infos, tile_w, tile_h, scale=scale)

    layout_debug = [
        {
            "panel_id": pos.panel_id,
            "x": round(pos.x, 1),
            "y": round(pos.y, 1),
            "rotation": round(pos.rotation, 2),
        }
        for pos in layout
    ]

    return {
        "mosaic_name": mosaic.name,
        "native_width": native_width,
        "tile_size": [tile_w, tile_h],
        "scale": round(scale, 4),
        "panels": debug_panels,
        "layout": layout_debug,
    }


@router.put("/{mosaic_id}", response_model=StatusResponse)
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


@router.delete("/{mosaic_id}", response_model=StatusResponse)
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
    base = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*$', '', mosaic.name)
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
        num = body.panel_label.split()[-1] if body.panel_label.startswith("Panel ") else body.panel_label
        # Strip year suffix from mosaic name for pattern matching
        base = re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*$', '', mosaic.name)
        obj_pattern = f"%{base}%Panel%{num}%"

    panel = MosaicPanel(
        mosaic_id=mosaic_id,
        target_id=body.target_id,
        panel_label=body.panel_label,
        object_pattern=obj_pattern,
    )
    session.add(panel)
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


@router.put("/{mosaic_id}/panels/{panel_id}", response_model=StatusResponse)
async def update_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    body: MosaicPanelUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    panel = await session.get(MosaicPanel, panel_id)
    if not panel or panel.mosaic_id != mosaic_id:
        raise HTTPException(404, "Panel not found")
    if body.panel_label is not None:
        panel.panel_label = body.panel_label
    if body.sort_order is not None:
        panel.sort_order = body.sort_order
    if body.object_pattern is not None:
        panel.object_pattern = body.object_pattern
    if body.grid_row is not None:
        panel.grid_row = body.grid_row
    if body.grid_col is not None:
        panel.grid_col = body.grid_col
    if body.rotation is not None:
        if body.rotation not in (0, 90, 180, 270):
            raise HTTPException(400, "rotation must be 0, 90, 180, or 270")
        panel.rotation = body.rotation
    if body.flip_h is not None:
        panel.flip_h = body.flip_h
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}/panels/{panel_id}", response_model=StatusResponse)
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
    """List all sessions (included + available) for a panel with stats."""
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
    base_filter = [
        Image.resolved_target_id == panel.target_id,
        Image.image_type == "LIGHT",
    ]
    if panel.object_pattern:
        base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(panel.object_pattern))

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


@router.put("/{mosaic_id}/panels/{panel_id}/sessions", response_model=StatusResponse)
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
