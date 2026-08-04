import logging
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.config import settings, async_redis
from app.models import Target
from app.models.session_note import SessionNote
from app.models.user import User
from app.schemas.target import (
    TargetAggregationResponse, EquipmentResponse, SessionDetailResponse,
    TargetDetailResponse, TargetSearchResultFuzzy, ObjectTypeCount, NotesUpdate,
    TargetStatusResponse,
)
from app.schemas.export import ExportResponse
from app.services import target_aggregation
from app.services.target_aggregation import (
    parse_sexa_ra, parse_sexa_dec, categorize_object_type, SIMBAD_CATEGORY_MAP,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/targets", tags=["targets"])

_FITS_KEYS_CACHE_KEY = "galactilog:fits_keys"
_FITS_KEYS_CACHE_TTL = 3600  # 1 hour

# Backwards-compatible aliases: other modules import these helpers from here.
_parse_sexa_ra = parse_sexa_ra
_parse_sexa_dec = parse_sexa_dec
_categorize_object_type = categorize_object_type
_SIMBAD_CATEGORY_MAP = SIMBAD_CATEGORY_MAP


# --- 1. Search (must be FIRST) ---

@router.get("/search", response_model=list[TargetSearchResultFuzzy])
async def search_targets(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    include_unresolved: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Search targets by name or alias with fuzzy trigram matching.

    With include_unresolved=true, unlinked OBJECT-name groups matching the
    query are appended as pseudo entries (unresolved=true) so merge flows can
    offer them as merge sources.
    """
    return await target_aggregation.search_targets(
        q, limit, session, include_unresolved=include_unresolved,
    )


# --- 2. Equipment (SECOND - before path-parameter routes) ---

@router.get("/equipment", response_model=EquipmentResponse)
async def get_equipment(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return distinct camera and telescope values."""
    return await target_aggregation.get_equipment(session)


# --- 2b. FITS keys (before path-parameter routes) ---

@router.get("/fits-keys", response_model=list[str])
async def get_fits_keys(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return distinct FITS header keys found across all images."""
    import json
    # Check Redis cache first
    try:
        async with async_redis() as r:
            cached = await r.get(_FITS_KEYS_CACHE_KEY)
        if cached:
            return Response(content=cached, media_type="application/json")
    except Exception:
        logger.debug("Redis cache read failed for fits-keys, computing fresh")

    from app.services.fits_headers import get_distinct_fits_keys
    keys = await get_distinct_fits_keys(session)

    # Cache the result in Redis
    try:
        async with async_redis() as r:
            await r.setex(_FITS_KEYS_CACHE_KEY, _FITS_KEYS_CACHE_TTL, json.dumps(keys))
    except Exception:
        logger.debug("Redis cache write failed for fits-keys")

    return keys


# --- 2c. Object types (before path-parameter routes) ---

@router.get("/object-types", response_model=list[ObjectTypeCount])
async def get_object_types(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return human-readable object type categories with target counts."""
    return await target_aggregation.get_object_types(session)


# --- 2d. Reference thumbnail ---

@router.get("/{target_id}/reference-thumbnail")
async def get_reference_thumbnail(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Stream the DSS reference thumbnail for a target."""
    from pathlib import Path
    target = await session.get(Target, target_id)
    if not target or not target.reference_thumbnail_path:
        raise HTTPException(status_code=404, detail="Reference thumbnail not found")

    thumb_path = Path(settings.thumbnails_path) / "reference" / target.reference_thumbnail_path
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")
    return FileResponse(str(thumb_path), media_type="image/jpeg")


# --- 2e. Export (before path-parameter routes) ---

@router.get("/{target_id}/export", response_model=ExportResponse)
async def export_target(
    target_id: uuid.UUID,
    sessions: str | None = Query(None, description="Comma-separated dates to include"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    return await target_aggregation.export_target(target_id, sessions, session)


# --- 2e. Target detail (before path-parameter routes) ---

@router.get("/{target_id:path}/detail", response_model=TargetDetailResponse)
async def get_target_detail(
    target_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return target identity with cumulative stats and session overviews."""
    return await target_aggregation.get_target_detail(target_id, session)


# --- 3. Aggregation (THIRD - after fixed paths, before path params) ---

@router.get("", response_model=TargetAggregationResponse)
async def list_targets_aggregated(
    session: AsyncSession = Depends(get_session),
    search: str | None = Query(None),
    target_id: str | None = Query(None, description="Exact target UUID from search selection"),
    camera: str | None = Query(None),
    telescope: str | None = Query(None),
    filters: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    fits_key: list[str] | None = Query(None),
    fits_op: list[str] | None = Query(None),
    fits_val: list[str] | None = Query(None),
    object_type: str | None = Query(None),
    hfr_min: float | None = Query(None),
    hfr_max: float | None = Query(None),
    # Metric range filters
    fwhm_min: float | None = Query(None),
    fwhm_max: float | None = Query(None),
    eccentricity_min: float | None = Query(None),
    eccentricity_max: float | None = Query(None),
    stars_min: int | None = Query(None),
    stars_max: int | None = Query(None),
    guiding_rms_min: float | None = Query(None),
    guiding_rms_max: float | None = Query(None),
    adu_mean_min: float | None = Query(None),
    adu_mean_max: float | None = Query(None),
    focuser_temp_min: float | None = Query(None),
    focuser_temp_max: float | None = Query(None),
    ambient_temp_min: float | None = Query(None),
    ambient_temp_max: float | None = Query(None),
    humidity_min: float | None = Query(None),
    humidity_max: float | None = Query(None),
    airmass_min: float | None = Query(None),
    airmass_max: float | None = Query(None),
    catalog: str | None = Query(None, description="Filter to targets in a specific catalog (e.g. Messier, NGC)"),
    sort_by: str = Query("integration", pattern="^(integration|lastSession|name|equipment)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    include_custom: bool = Query(False),
    custom_filters: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    """Return targets with aggregated session data, filtered by query params."""
    return await target_aggregation.list_targets_aggregated(
        session=session,
        search=search,
        target_id=target_id,
        camera=camera,
        telescope=telescope,
        filters=filters,
        date_from=date_from,
        date_to=date_to,
        fits_key=fits_key,
        fits_op=fits_op,
        fits_val=fits_val,
        object_type=object_type,
        hfr_min=hfr_min,
        hfr_max=hfr_max,
        fwhm_min=fwhm_min,
        fwhm_max=fwhm_max,
        eccentricity_min=eccentricity_min,
        eccentricity_max=eccentricity_max,
        stars_min=stars_min,
        stars_max=stars_max,
        guiding_rms_min=guiding_rms_min,
        guiding_rms_max=guiding_rms_max,
        adu_mean_min=adu_mean_min,
        adu_mean_max=adu_mean_max,
        focuser_temp_min=focuser_temp_min,
        focuser_temp_max=focuser_temp_max,
        ambient_temp_min=ambient_temp_min,
        ambient_temp_max=ambient_temp_max,
        humidity_min=humidity_min,
        humidity_max=humidity_max,
        airmass_min=airmass_min,
        airmass_max=airmass_max,
        catalog=catalog,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        page_size=page_size,
        include_custom=include_custom,
        custom_filters=custom_filters,
    )


# --- 4. Session detail (LAST - has path parameters) ---

@router.get("/{target_id:path}/sessions/{date}", response_model=SessionDetailResponse)
async def get_session_detail(
    target_id: str,
    date: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return detailed session data for a target on a specific date.

    The date string is interpreted as a UTC calendar day to match the
    listing endpoint, which groups by `session_date`.
    """
    return await target_aggregation.get_session_detail(target_id, date, session)


# --- Notes endpoints ---
# update_session_notes is registered before update_target_notes: the target
# notes route uses a greedy `{target_id:path}` (to admit `obj:` pseudo-target
# ids), which would otherwise also match `/{id}/sessions/{date}/notes` PUT
# requests since that path also ends in "/notes".

@router.put("/{target_id}/sessions/{date}/notes", response_model=TargetStatusResponse)
async def update_session_notes(
    target_id: str,
    date: str,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    session_date = date_type.fromisoformat(date)

    # Resolve target_id (may be UUID or obj:name)
    resolved_id = None
    try:
        resolved_id = uuid.UUID(target_id)
    except ValueError:
        if target_id.startswith("obj:"):
            name = target_id[4:]
            tq = select(Target.id).where(Target.primary_name == name)
            row = (await session.execute(tq)).scalar_one_or_none()
            if row:
                resolved_id = row
    if not resolved_id:
        raise HTTPException(404, "Target not found")

    # Upsert note
    if not body.notes:
        # Delete if empty
        q = select(SessionNote).where(
            SessionNote.target_id == resolved_id,
            SessionNote.session_date == session_date,
        )
        note = (await session.execute(q)).scalar_one_or_none()
        if note:
            await session.delete(note)
            await session.commit()
    else:
        q = select(SessionNote).where(
            SessionNote.target_id == resolved_id,
            SessionNote.session_date == session_date,
        )
        note = (await session.execute(q)).scalar_one_or_none()
        if note:
            note.notes = body.notes
        else:
            note = SessionNote(
                target_id=resolved_id,
                session_date=session_date,
                notes=body.notes,
            )
            session.add(note)
        await session.commit()

    return {"status": "ok"}


@router.put("/{target_id:path}/notes", response_model=TargetStatusResponse)
async def update_target_notes(
    target_id: str,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    # Resolve target_id (may be UUID or obj:name)
    resolved_id = None
    try:
        resolved_id = uuid.UUID(target_id)
    except ValueError:
        if target_id.startswith("obj:"):
            name = target_id[4:]
            tq = select(Target.id).where(Target.primary_name == name)
            row = (await session.execute(tq)).scalar_one_or_none()
            if row:
                resolved_id = row
    if not resolved_id:
        raise HTTPException(404, "Target not found")

    target = await session.get(Target, resolved_id)
    if not target:
        raise HTTPException(404, "Target not found")
    target.notes = body.notes if body.notes else None
    await session.commit()
    return {"status": "ok"}
