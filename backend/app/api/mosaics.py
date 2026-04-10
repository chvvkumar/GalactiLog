import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func, cast, Date, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Image, Target, User, UserSettings, SETTINGS_ROW_ID
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.mosaic import (
    AcceptSuggestionRequest,
    MosaicCreate, MosaicUpdate, MosaicPanelCreate, MosaicPanelUpdate,
    MosaicSummary, MosaicDetailResponse, PanelStats, MosaicSuggestionResponse,
)
from app.api.auth import get_current_user
from app.services.mosaic_composite import build_mosaic_composite

router = APIRouter(prefix="/mosaics", tags=["mosaics"])


def _parse_sexa_ra(s: str) -> float | None:
    """Parse sexagesimal RA 'HH MM SS' to degrees."""
    try:
        parts = s.strip().split()
        h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + sec / 3600) * 15
    except (ValueError, IndexError):
        return None


def _parse_sexa_dec(s: str) -> float | None:
    """Parse sexagesimal Dec '+DD MM SS' to degrees."""
    try:
        s = s.strip()
        sign = -1 if s.startswith("-") else 1
        parts = s.lstrip("+-").split()
        d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return sign * (d + m / 60 + sec / 3600)
    except (ValueError, IndexError):
        return None


async def _panel_stats(panel: MosaicPanel, session: AsyncSession) -> PanelStats:
    """Compute stats for a single panel."""
    target = panel.target

    # When an object_pattern is set, filter frames by OBJECT header
    # (needed when multiple panels share the same target after SIMBAD merge)
    base_filter = [
        Image.resolved_target_id == panel.target_id,
        Image.image_type == "LIGHT",
    ]
    if panel.object_pattern:
        base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(panel.object_pattern))

    q = (
        select(
            func.sum(Image.exposure_time).label("integration"),
            func.count(Image.id).label("frames"),
            func.max(cast(Image.capture_date, Date)).label("last_date"),
        )
        .where(*base_filter)
    )
    row = (await session.execute(q)).one()

    # Filter distribution
    fq = (
        select(Image.filter_used, func.sum(Image.exposure_time))
        .where(*base_filter)
        .where(Image.filter_used.is_not(None))
        .group_by(Image.filter_used)
    )
    filter_dist = {r[0]: r[1] or 0 for r in (await session.execute(fq)).all()}

    # Most recent thumbnail for this panel (also grab pier side for orientation)
    thumb_q = (
        select(
            Image.thumbnail_path,
            Image.raw_headers["PIERSIDE"].astext.label("pier_side"),
        )
        .where(*base_filter)
        .where(Image.thumbnail_path.is_not(None))
        .order_by(Image.capture_date.desc())
        .limit(1)
    )
    thumb_row = (await session.execute(thumb_q)).first()
    thumb_url = None
    thumb_pier_side = None
    if thumb_row and thumb_row.thumbnail_path:
        filename = thumb_row.thumbnail_path.split("/")[-1].split("\\")[-1]
        thumb_url = f"/thumbnails/{filename}"
        thumb_pier_side = thumb_row.pier_side

    # Compute per-panel center from frame FITS headers (median of OBJCTRA/OBJCTDEC).
    # This gives the actual pointing position for each panel, even when multiple
    # panels are merged into the same target by SIMBAD resolution.
    panel_ra = target.ra
    panel_dec = target.dec
    if panel.object_pattern:
        coord_q = (
            select(
                Image.raw_headers["OBJCTRA"].astext.label("ra_str"),
                Image.raw_headers["OBJCTDEC"].astext.label("dec_str"),
            )
            .where(*base_filter)
            .where(Image.raw_headers["OBJCTRA"].isnot(None))
            .where(Image.raw_headers["OBJCTDEC"].isnot(None))
            .limit(50)
        )
        coord_rows = (await session.execute(coord_q)).all()
        if coord_rows:
            ras = sorted(r for row in coord_rows if (r := _parse_sexa_ra(row.ra_str)) is not None)
            decs = sorted(r for row in coord_rows if (r := _parse_sexa_dec(row.dec_str)) is not None)
            if ras:
                panel_ra = ras[len(ras) // 2]
            if decs:
                panel_dec = decs[len(decs) // 2]

    return PanelStats(
        panel_id=str(panel.id),
        target_id=str(panel.target_id),
        target_name=target.primary_name,
        panel_label=panel.panel_label,
        sort_order=panel.sort_order,
        ra=panel_ra,
        dec=panel_dec,
        total_integration_seconds=row.integration or 0,
        total_frames=row.frames or 0,
        filter_distribution=filter_dist,
        last_session_date=str(row.last_date) if row.last_date else None,
        thumbnail_url=thumb_url,
        thumbnail_pier_side=thumb_pier_side,
        object_pattern=panel.object_pattern,
    )


@router.post("/detect")
async def trigger_detection(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
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
    rows = (await session.execute(q)).scalars().all()

    # Resolve target names in batch
    all_ids = {t for r in rows for t in r.target_ids}
    name_map: dict[str, str] = {}
    if all_ids:
        tq = select(Target.id, Target.primary_name).where(Target.id.in_(all_ids))
        for tid, tname in (await session.execute(tq)).all():
            name_map[str(tid)] = tname

    # Build all OBJECT ILIKE patterns across every suggestion+panel,
    # then fetch session summaries in a single query instead of N queries.
    # Each pattern maps back to (suggestion index, panel label).
    pattern_map: dict[str, list[tuple[int, str]]] = {}  # pattern -> [(row_idx, label)]
    for idx, r in enumerate(rows):
        for label in r.panel_labels:
            num = label.split()[-1] if label.startswith("Panel ") else label
            obj_pattern = f"%{r.suggested_name}%{num}%"
            pattern_map.setdefault(obj_pattern, []).append((idx, label))

    # Run one query with all patterns OR'd together
    all_patterns = list(pattern_map.keys())
    obj_col = Image.raw_headers["OBJECT"].astext
    session_rows_by_idx: dict[int, list[SuggestionPanelSession]] = defaultdict(list)

    if all_patterns:
        sq = (
            select(
                obj_col.label("obj"),
                cast(Image.capture_date, Date).label("night"),
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
            obj_lower = obj_val.lower()
            for pattern, mappings in pattern_map.items():
                # Convert SQL ILIKE pattern to simple substring check
                # Patterns are like %name%num% - check each segment between %
                segments = [s for s in pattern.lower().split("%") if s]
                if all(seg in obj_lower for seg in segments):
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
        results.append(MosaicSuggestionResponse(
            id=str(r.id),
            suggested_name=r.suggested_name,
            target_ids=[str(t) for t in r.target_ids],
            panel_labels=r.panel_labels,
            target_names={str(t): name_map.get(str(t), "Unknown") for t in set(r.target_ids)},
            sessions=session_rows_by_idx.get(idx, []),
            status=r.status,
        ))

    return results


@router.post("/suggestions/{suggestion_id}/accept", response_model=MosaicSummary)
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    body: AcceptSuggestionRequest = AcceptSuggestionRequest(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    suggestion = await session.get(MosaicSuggestion, suggestion_id)
    if not suggestion or suggestion.status != "pending":
        raise HTTPException(404, "Suggestion not found or already resolved")

    selected = set(body.selected_panels) if body.selected_panels is not None else None

    # Create the mosaic
    mosaic = Mosaic(name=suggestion.suggested_name)
    session.add(mosaic)
    await session.flush()

    # Create panels - multiple panels may share the same target_id
    # (SIMBAD often merges panel variants into one target)
    panel_num = 0
    created = 0
    for target_id, label in zip(suggestion.target_ids, suggestion.panel_labels):
        if selected is not None and label not in selected:
            continue
        # Build OBJECT header pattern for filtering frames per panel
        # e.g., base "Andromeda Galaxy" + "Panel 3" → "%Andromeda Galaxy%Panel%3%"
        num = label.split()[-1] if label.startswith("Panel ") else label
        obj_pattern = f"%{suggestion.suggested_name}%{num}%"
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=target_id,
            panel_label=label,
            sort_order=panel_num,
            object_pattern=obj_pattern,
        )
        session.add(panel)
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
    )


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    suggestion = await session.get(MosaicSuggestion, suggestion_id)
    if not suggestion or suggestion.status != "pending":
        raise HTTPException(404, "Suggestion not found or already resolved")
    suggestion.status = "rejected"
    await session.commit()
    return {"status": "ok"}


@router.get("", response_model=list[MosaicSummary])
async def list_mosaics(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(Mosaic).options(selectinload(Mosaic.panels)).order_by(Mosaic.name)
    mosaics = (await session.execute(q)).scalars().all()

    results = []
    for m in mosaics:
        total_int = 0
        total_frames = 0
        panel_integrations = []
        for p in m.panels:
            filters = [
                Image.resolved_target_id == p.target_id,
                Image.image_type == "LIGHT",
            ]
            if p.object_pattern:
                filters.append(Image.raw_headers["OBJECT"].astext.ilike(p.object_pattern))
            iq = select(func.sum(Image.exposure_time), func.count(Image.id)).where(*filters)
            row = (await session.execute(iq)).one()
            pi = row[0] or 0
            total_int += pi
            total_frames += row[1] or 0
            panel_integrations.append(pi)

        max_panel = max(panel_integrations) if panel_integrations else 0
        if max_panel > 0 and len(panel_integrations) > 0:
            completion = sum(min(p / max_panel, 1.0) for p in panel_integrations) / len(panel_integrations) * 100
        else:
            completion = 0

        results.append(MosaicSummary(
            id=str(m.id),
            name=m.name,
            notes=m.notes,
            panel_count=len(m.panels),
            total_integration_seconds=total_int,
            total_frames=total_frames,
            completion_pct=round(completion, 1),
        ))
    return results


@router.post("", response_model=MosaicSummary)
async def create_mosaic(
    body: MosaicCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = Mosaic(name=body.name, notes=body.notes)
    session.add(mosaic)
    await session.flush()

    for p in body.panels:
        obj_pattern = p.object_pattern
        if obj_pattern is None:
            num = p.panel_label.split()[-1] if p.panel_label.startswith("Panel ") else p.panel_label
            obj_pattern = f"%{mosaic.name}%{num}%"
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

    panels = []
    total_int = 0
    total_frames = 0
    for p in sorted(mosaic.panels, key=lambda x: x.sort_order):
        ps = await _panel_stats(p, session)
        total_int += ps.total_integration_seconds
        total_frames += ps.total_frames
        panels.append(ps)

    return MosaicDetailResponse(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        total_integration_seconds=total_int,
        total_frames=total_frames,
        panels=panels,
    )


@router.get("/{mosaic_id}/composite")
async def get_mosaic_composite(
    mosaic_id: str,
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

    try:
        jpeg_bytes = await build_mosaic_composite(
            mosaic_id=str(mosaic.id),
            panels=panels,
            session=session,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

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
                tile_img, nw = generate_panel_thumbnail(fits_path, max_width=800)
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


@router.put("/{mosaic_id}")
async def update_mosaic(
    mosaic_id: uuid.UUID,
    body: MosaicUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")
    if body.name is not None:
        mosaic.name = body.name
    if body.notes is not None:
        mosaic.notes = body.notes
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}")
async def delete_mosaic(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")
    await session.delete(mosaic)
    await session.commit()
    return {"status": "ok"}


@router.post("/{mosaic_id}/panels")
async def add_panel(
    mosaic_id: uuid.UUID,
    body: MosaicPanelCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
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
        obj_pattern = f"%{mosaic.name}%{num}%"

    panel = MosaicPanel(
        mosaic_id=mosaic_id,
        target_id=body.target_id,
        panel_label=body.panel_label,
        object_pattern=obj_pattern,
    )
    session.add(panel)
    await session.commit()
    return {"status": "ok", "panel_id": str(panel.id)}


@router.put("/{mosaic_id}/panels/{panel_id}")
async def update_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    body: MosaicPanelUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
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
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}/panels/{panel_id}")
async def remove_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    panel = await session.get(MosaicPanel, panel_id)
    if not panel or panel.mosaic_id != mosaic_id:
        raise HTTPException(404, "Panel not found")
    await session.delete(panel)
    await session.commit()
    return {"status": "ok"}
