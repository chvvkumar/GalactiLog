import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Image, Target, User
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.mosaic import (
    MosaicCreate, MosaicUpdate, MosaicPanelCreate, MosaicPanelUpdate,
    MosaicSummary, MosaicDetailResponse, PanelStats, MosaicSuggestionResponse,
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/mosaics", tags=["mosaics"])


async def _panel_stats(panel: MosaicPanel, session: AsyncSession) -> PanelStats:
    """Compute stats for a single panel."""
    target = panel.target

    q = (
        select(
            func.sum(Image.exposure_time).label("integration"),
            func.count(Image.id).label("frames"),
            func.max(cast(Image.capture_date, Date)).label("last_date"),
        )
        .where(Image.resolved_target_id == panel.target_id)
        .where(Image.image_type == "LIGHT")
    )
    row = (await session.execute(q)).one()

    # Filter distribution
    fq = (
        select(Image.filter_used, func.sum(Image.exposure_time))
        .where(Image.resolved_target_id == panel.target_id)
        .where(Image.image_type == "LIGHT")
        .where(Image.filter_used.is_not(None))
        .group_by(Image.filter_used)
    )
    filter_dist = {r[0]: r[1] or 0 for r in (await session.execute(fq)).all()}

    return PanelStats(
        panel_id=str(panel.id),
        target_id=str(panel.target_id),
        target_name=target.primary_name,
        panel_label=panel.panel_label,
        sort_order=panel.sort_order,
        ra=target.ra,
        dec=target.dec,
        total_integration_seconds=row.integration or 0,
        total_frames=row.frames or 0,
        filter_distribution=filter_dist,
        last_session_date=str(row.last_date) if row.last_date else None,
    )


# NOTE: This endpoint MUST be defined BEFORE the /{mosaic_id} routes
# to avoid FastAPI interpreting "suggestions" as a UUID path parameter.
@router.get("/suggestions", response_model=list[MosaicSuggestionResponse])
async def get_suggestions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(MosaicSuggestion).where(MosaicSuggestion.status == "pending")
    rows = (await session.execute(q)).scalars().all()
    return [
        MosaicSuggestionResponse(
            id=str(r.id),
            suggested_name=r.suggested_name,
            target_ids=[str(t) for t in r.target_ids],
            panel_labels=r.panel_labels,
            status=r.status,
        )
        for r in rows
    ]


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
            iq = (
                select(func.sum(Image.exposure_time), func.count(Image.id))
                .where(Image.resolved_target_id == p.target_id)
                .where(Image.image_type == "LIGHT")
            )
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
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=p.target_id,
            panel_label=p.panel_label,
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

    # Check target not already in a mosaic
    existing = (await session.execute(
        select(MosaicPanel).where(MosaicPanel.target_id == body.target_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Target already belongs to a mosaic")

    panel = MosaicPanel(
        mosaic_id=mosaic_id,
        target_id=body.target_id,
        panel_label=body.panel_label,
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
