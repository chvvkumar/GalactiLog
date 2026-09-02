"""Public read/act API, version 1.

Every handler here is a thin projection over an existing service or internal
handler: the aggregation, detail, export, stats, guiding and mosaic logic is
reused unchanged and reshaped into the slim models in app/schemas/v1.py. The
projection is the point - it is what keeps filesystem paths, raw FITS
headers, merge bookkeeping, custom columns, insights and baselines off the
public surface even as the internal schemas grow.

Auth is structural: require_read_key is attached to the router below, so
every route is key-authed by default and write routes add require_write_key.
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.v1.deps import require_read_key, require_write_key
from app.config import async_redis, settings as app_settings
from app.database import get_session
from app.models import Image, Target, UserSettings, SETTINGS_ROW_ID
from app.schemas.common import StatusResponse
from app.schemas.integration import IntegrationResponse
from app.schemas.stats_guiding import GuidingStatsResponse
from app.schemas.target import NotesUpdate
from app.schemas import v1 as s
from app.services import target_aggregation
from app.services.mosaic_stats import list_mosaic_summaries
from app.services.path_safety import resolve_relative_under

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["v1"],
    dependencies=[Depends(require_read_key)],
)

# list_targets_aggregated takes every dashboard filter as a required keyword.
# The public listing applies none of them; spelled out rather than derived
# from the signature so a new filter is a visible edit here, not a silent one.
_NO_FILTERS = dict(
    search=None, target_id=None, camera=None, telescope=None, filters=None,
    date_from=None, date_to=None, fits_key=None, fits_op=None, fits_val=None,
    object_type=None, hfr_min=None, hfr_max=None, fwhm_min=None, fwhm_max=None,
    eccentricity_min=None, eccentricity_max=None, stars_min=None, stars_max=None,
    guiding_rms_min=None, guiding_rms_max=None, adu_mean_min=None, adu_mean_max=None,
    focuser_temp_min=None, focuser_temp_max=None, ambient_temp_min=None,
    ambient_temp_max=None, humidity_min=None, humidity_max=None,
    airmass_min=None, airmass_max=None, catalog=None,
    include_custom=False, custom_filters=None,
    # Unresolved OBJECT-name groups carry an "obj:<name>" id that no other v1
    # route accepts, so they are excluded at the query, not after paging:
    # dropping them from a page would leave `total` counting rows a client
    # can never fetch, and short-change the page it did ask for.
    resolved_only=True,
)


async def _general_settings(session: AsyncSession) -> dict:
    row = await session.get(UserSettings, SETTINGS_ROW_ID)
    return (row.general if row else None) or {}


async def _filter_totals(session: AsyncSession, target_id: uuid.UUID) -> dict[str, float]:
    """Integration seconds per filter for one target.

    Same semantics as the list route's filter_totals, which gets these from
    the aggregation: LIGHT frames only, exposure_time summed, filter names
    run through the alias map so "Ha" and "H-alpha" land in one bucket.
    """
    from collections import defaultdict

    from app.services.normalization import load_alias_maps, normalize_filter

    filter_map, _, _ = await load_alias_maps(session)
    rows = (await session.execute(
        select(Image.filter_used, func.sum(Image.exposure_time))
        .where(Image.resolved_target_id == target_id, Image.image_type == "LIGHT")
        .group_by(Image.filter_used)
    )).all()

    totals: dict[str, float] = defaultdict(float)
    for raw_filter, seconds in rows:
        name = normalize_filter(raw_filter, filter_map)
        if name:
            totals[name] += float(seconds or 0)
    return dict(totals)


async def _require_target(session: AsyncSession, target_id: uuid.UUID) -> Target:
    target = await session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


# --- Targets ---------------------------------------------------------------

@router.get("/targets", response_model=s.TargetPage)
async def list_targets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("integration", pattern="^(integration|lastSession|name|equipment)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    session: AsyncSession = Depends(get_session),
):
    """Targets with cumulative totals. No per-session arrays - see
    GET /targets/{id}/sessions for those."""
    agg = await target_aggregation.list_targets_aggregated(
        session=session, sort_by=sort_by, sort_dir=sort_dir,
        page=page, page_size=page_size, **_NO_FILTERS,
    )

    rows = agg.targets
    ids = [uuid.UUID(t.target_id) for t in rows]
    identity = {}
    if ids:
        result = await session.execute(
            # aliases comes from the target row, not from the aggregation:
            # TargetAggregation.aliases is the set of distinct FITS OBJECT
            # strings the frames were shot under, which is a different thing
            # from the catalog aliases /targets/{id} and /search return under
            # this same name.
            select(
                Target.id, Target.catalog_id, Target.common_name,
                Target.ra, Target.dec, Target.object_type, Target.aliases,
            ).where(Target.id.in_(ids))
        )
        identity = {str(r.id): r for r in result.all()}

    items = []
    for t in rows:
        ident = identity.get(t.target_id)
        nights = sorted(x.session_date for x in t.sessions)
        items.append(s.TargetSummary(
            id=t.target_id,
            name=t.primary_name,
            other_names=(ident.aliases or []) if ident else [],
            catalog_id=ident.catalog_id if ident else None,
            common_name=ident.common_name if ident else None,
            position=s.Position(
                ra=ident.ra if ident else None,
                dec=ident.dec if ident else None,
            ),
            object_type=ident.object_type if ident else None,
            total_integration_seconds=t.total_integration_seconds,
            total_frames=t.total_frames,
            filter_totals=t.filter_distribution,
            equipment=t.equipment,
            first_night=nights[0] if nights else None,
            last_night=nights[-1] if nights else None,
        ))

    return s.TargetPage(
        items=items, page=agg.page, page_size=agg.page_size, total=agg.total_count,
    )


@router.get("/targets/{target_id}", response_model=s.TargetDetail)
async def get_target(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    d = await target_aggregation.get_target_detail(str(target_id), session)
    ident = await _require_target(session, target_id)
    nights = sorted(x.session_date for x in d.sessions)
    filter_totals = await _filter_totals(session, target_id)
    return s.TargetDetail(
        id=d.target_id,
        name=d.primary_name,
        other_names=d.aliases,
        catalog_id=ident.catalog_id,
        common_name=ident.common_name,
        position=s.Position(ra=d.ra, dec=d.dec),
        object_type=d.object_type,
        total_integration_seconds=d.total_integration_seconds,
        total_frames=d.total_frames,
        filter_totals=filter_totals,
        equipment=d.equipment,
        first_night=nights[0] if nights else None,
        last_night=nights[-1] if nights else None,
        constellation=d.constellation,
        v_mag=d.v_mag,
        surface_brightness=d.surface_brightness,
        distance_pc=d.distance_pc,
        size_major=d.size_major,
        size_minor=d.size_minor,
        position_angle=d.position_angle,
        session_count=d.session_count,
        filters_used=d.filters_used,
        avg_hfr=d.avg_hfr,
        avg_hfr_arcsec=d.avg_hfr_arcsec,
        avg_fwhm_arcsec=d.avg_fwhm,
        avg_eccentricity=d.avg_eccentricity,
        avg_guiding_rms_arcsec=d.avg_guiding_rms_arcsec,
        avg_detected_stars=d.avg_detected_stars,
        catalog_description=d.sac_description,
        catalog_notes=d.sac_notes,
        notes=d.notes,
    )


@router.get("/targets/{target_id}/sessions", response_model=list[s.V1SessionSummary])
async def list_target_sessions(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    d = await target_aggregation.get_target_detail(str(target_id), session)
    return [
        s.V1SessionSummary(
            date=o.session_date,
            frames=o.frame_count,
            integration_seconds=o.integration_seconds,
            filters=o.filters_used,
            equipment=[e for e in (o.telescope, o.camera) if e],
        )
        for o in d.sessions
    ]


@router.get("/targets/{target_id}/sessions/{date}", response_model=s.SessionDetail)
async def get_target_session(
    target_id: uuid.UUID,
    date: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        d = await target_aggregation.get_session_detail(str(target_id), date, session)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    return s.SessionDetail(
        target_name=d.target_name,
        date=d.session_date,
        frames=d.frame_count,
        integration_seconds=d.integration_seconds,
        equipment=d.equipment,
        filters=[
            s.SessionFilter(
                filter=f.filter_name,
                frames=f.frame_count,
                integration_seconds=f.integration_seconds,
                exposure_seconds=f.exposure_time,
                median_hfr=f.median_hfr,
                median_eccentricity=f.median_eccentricity,
            )
            for f in d.filter_details
        ],
        gain=d.gain,
        offset=d.offset,
        sensor_temp=d.sensor_temp,
        exposure_seconds=d.exposure_times,
        first_frame_time=d.first_frame_time,
        last_frame_time=d.last_frame_time,
        median_hfr=d.median_hfr,
        hfr_arcsec=d.hfr_arcsec,
        fwhm_arcsec=d.fwhm_arcsec,
        median_eccentricity=d.median_eccentricity,
        median_detected_stars=d.median_detected_stars,
        median_guiding_rms_arcsec=d.median_guiding_rms,
        median_airmass=d.median_airmass,
        median_ambient_temp=d.median_ambient_temp,
        median_humidity=d.median_humidity,
        median_cloud_cover=d.median_cloud_cover,
        notes=d.notes,
    )


_FRAME_COLS = (
    Image.id, Image.capture_date, Image.session_date, Image.filter_used,
    Image.exposure_time, Image.telescope, Image.camera, Image.median_hfr,
    Image.hfr_stdev, Image.fwhm, Image.eccentricity, Image.eccentricity_source,
    Image.detected_stars, Image.guiding_rms_arcsec, Image.guiding_rms_ra_arcsec,
    Image.guiding_rms_dec_arcsec, Image.guiding_rms_source, Image.adu_mean,
    Image.adu_median, Image.adu_stdev, Image.sky_quality, Image.camera_gain,
    Image.sensor_temp, Image.focuser_position, Image.focuser_temp,
    Image.altitude_deg, Image.airmass, Image.ambient_temp, Image.humidity,
    Image.cloud_cover,
)


@router.get("/targets/{target_id}/frames", response_model=s.FramePage)
async def list_target_frames(
    target_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    """Every LIGHT frame for the target in capture order.

    Columns are projected explicitly (never `select(Image)`) so the raw_headers
    JSONB and file_path never leave the database for this route.
    """
    await _require_target(session, target_id)
    where = (Image.resolved_target_id == target_id, Image.image_type == "LIGHT")

    total = await session.scalar(
        select(func.count(Image.id)).where(*where)
    )
    rows = (await session.execute(
        select(*_FRAME_COLS)
        .where(*where)
        .order_by(Image.capture_date.asc().nullslast(), Image.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    return s.FramePage(
        page=page, page_size=page_size, total=total or 0,
        items=[
            s.Frame(
                id=str(r.id),
                capture_time=r.capture_date.isoformat() if r.capture_date else None,
                session_date=str(r.session_date) if r.session_date else None,
                filter=r.filter_used,
                exposure_seconds=r.exposure_time,
                telescope=r.telescope,
                camera=r.camera,
                hfr=r.median_hfr,
                hfr_stdev=r.hfr_stdev,
                fwhm_arcsec=r.fwhm,
                eccentricity=r.eccentricity,
                eccentricity_source=r.eccentricity_source,
                star_count=r.detected_stars,
                guiding_rms_arcsec=r.guiding_rms_arcsec,
                guiding_rms_ra_arcsec=r.guiding_rms_ra_arcsec,
                guiding_rms_dec_arcsec=r.guiding_rms_dec_arcsec,
                guiding_rms_source=r.guiding_rms_source,
                adu_mean=r.adu_mean,
                adu_median=r.adu_median,
                adu_stdev=r.adu_stdev,
                sky_quality=r.sky_quality,
                gain=r.camera_gain,
                sensor_temp=r.sensor_temp,
                focuser_position=r.focuser_position,
                focuser_temp=r.focuser_temp,
                altitude_deg=r.altitude_deg,
                airmass=r.airmass,
                ambient_temp=r.ambient_temp,
                humidity=r.humidity,
                cloud_cover=r.cloud_cover,
            )
            for r in rows
        ],
    )


@router.get("/targets/{target_id}/export", response_model=s.V1Export)
async def export_target(
    target_id: uuid.UUID,
    sessions: str | None = Query(None, description="Comma-separated dates to include"),
    session: AsyncSession = Depends(get_session),
):
    e = await target_aggregation.export_target(target_id, sessions, session)
    return s.V1Export(
        target_name=e.target_name,
        catalog_id=e.catalog_id,
        equipment=[
            s.V1ExportEquipment(telescope=q.telescope, camera=q.camera)
            for q in e.equipment
        ],
        dates=e.dates,
        rows=[
            s.V1ExportRow(
                date=r.date,
                filter=r.filter_name,
                astrobin_filter_id=r.astrobin_filter_id,
                frames=r.frames,
                exposure_seconds=r.exposure,
                total_seconds=r.total_seconds,
                gain=r.gain,
                sensor_temp=r.sensor_temp,
                fwhm_arcsec=r.fwhm,
                sky_quality=r.sky_quality,
                ambient_temp=r.ambient_temp,
            )
            for r in e.rows
        ],
        calibration=s.V1ExportCalibration(
            darks=e.calibration.darks,
            flats=e.calibration.flats,
            bias=e.calibration.bias,
        ),
        total_integration_seconds=e.total_integration_seconds,
        bortle=e.bortle,
    )


@router.get("/targets/{target_id}/thumbnail", response_class=FileResponse)
async def get_target_thumbnail(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """The target's most recent frame thumbnail, falling back to the survey
    reference image. Addressed by target id: no path reaches the client."""
    target = await _require_target(session, target_id)
    root = Path(app_settings.thumbnails_path).resolve()

    latest = await session.scalar(
        select(Image.thumbnail_path)
        .where(
            Image.resolved_target_id == target_id,
            Image.image_type == "LIGHT",
            Image.thumbnail_path.isnot(None),
        )
        .order_by(Image.capture_date.desc().nullslast())
        .limit(1)
    )

    candidates = []
    if latest:
        candidates.append(Path(latest).name)
    if target.reference_thumbnail_path:
        candidates.append(f"reference/{target.reference_thumbnail_path}")

    for rel in candidates:
        try:
            full = resolve_relative_under(root, rel)
        except ValueError:
            continue
        if full.is_file():
            return FileResponse(str(full), media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="Thumbnail not found")


# --- Search ----------------------------------------------------------------

@router.get("/search", response_model=list[s.SearchHit])
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    hits = await target_aggregation.search_targets(q, limit, session)
    return [
        s.SearchHit(
            id=str(h.id),
            name=h.primary_name,
            other_names=h.aliases,
            match=h.match_source,
            score=h.similarity_score,
        )
        # Unresolved OBJECT-name pseudo-rows carry an "obj:<name>" id that no
        # other v1 route accepts, so they are not offered here.
        for h in hits
        if not h.unresolved and not str(h.id).startswith("obj:")
    ]


# --- Nights ----------------------------------------------------------------

@router.get("/nights", response_model=list[s.Night])
async def list_nights(
    year: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    from app.api.stats import get_calendar

    entries = await get_calendar(year=year, session=session, user=None)
    return [
        s.Night(
            date=e.date,
            integration_seconds=e.integration_seconds,
            targets=e.target_count,
            frames=e.frame_count,
        )
        for e in entries
    ]


# --- Stats -----------------------------------------------------------------

@router.get("/stats", response_model=s.StatsOverview)
async def stats(session: AsyncSession = Depends(get_session)):
    """Slim library overview. No storage or ingest-history sections."""
    import json

    from app.api.stats import get_stats

    raw = await get_stats(session=session, user=None)
    # get_stats returns a raw JSON Response on a cache hit, a model otherwise.
    data = json.loads(raw.body) if isinstance(raw, Response) else raw.model_dump(mode="json")

    nights = await session.scalar(
        select(func.count(distinct(Image.session_date))).where(
            Image.image_type == "LIGHT", Image.session_date.isnot(None)
        )
    )

    overview = data["overview"]
    coords = data.get("site_coords") or {}
    general = await _general_settings(session)
    site = s.StatsSite(
        latitude=coords.get("latitude"),
        longitude=coords.get("longitude"),
        bortle=general.get("astrobin_bortle"),
    )

    def _equipment(items):
        return [
            s.EquipmentCount(
                name=i["name"],
                frame_count=i["frame_count"],
                integration_seconds=i.get("integration_seconds") or 0,
            )
            for i in items
        ]

    return s.StatsOverview(
        totals=s.StatsTotals(
            targets=overview["target_count"],
            frames=overview["total_frames"],
            integration_seconds=overview["total_integration_seconds"],
            nights=nights or 0,
        ),
        top_targets=[s.V1TopTarget(**t) for t in data["top_targets"]],
        filter_usage=data["filter_usage"],
        cameras=_equipment(data["equipment"]["cameras"]),
        telescopes=_equipment(data["equipment"]["telescopes"]),
        site=site if (site.latitude is not None or site.bortle is not None) else None,
    )


@router.get("/guiding", response_model=s.V1Guiding)
async def guiding(session: AsyncSession = Depends(get_session)):
    from app.api.stats_guiding import get_guiding_stats

    # get_guiding_stats returns the cached dict, so validate back into the
    # internal model before projecting: a shape change upstream then fails
    # here loudly instead of reshaping the public response.
    g = GuidingStatsResponse.model_validate(
        await get_guiding_stats(session=session, user=None)
    )
    return s.V1Guiding(
        unmapped_session_count=g.unmapped_session_count,
        rigs=[
            s.V1GuidingRig(
                telescope=r.telescope,
                session_count=r.session_count,
                gated_session_count=r.gated_session_count,
                guided_hours=r.guided_hours,
                rms_total_arcsec=r.rms_total_arcsec,
                rms_ra_arcsec=r.rms_ra_arcsec,
                rms_dec_arcsec=r.rms_dec_arcsec,
                rms_total_filtered_arcsec=r.rms_total_filtered_arcsec,
                ra_dec_ratio=r.ra_dec_ratio,
                settle_median_s=r.settle_median_s,
                exposure_ms_values=r.exposure_ms_values,
            )
            for r in g.rigs
        ],
        altitude_bands=[
            s.V1GuidingAltitudeBand(
                telescope=b.telescope,
                band=b.band,
                session_count=b.session_count,
                rms_total_arcsec=b.rms_total_arcsec,
                rms_ra_arcsec=b.rms_ra_arcsec,
                rms_dec_arcsec=b.rms_dec_arcsec,
            )
            for b in g.altitude_bands
        ],
    )


# --- Mosaics ---------------------------------------------------------------

@router.get("/mosaics", response_model=list[s.V1MosaicSummary])
async def list_mosaics(session: AsyncSession = Depends(get_session)):
    return [
        s.V1MosaicSummary(
            id=m.id, name=m.name, notes=m.notes, panel_count=m.panel_count,
            total_integration_seconds=m.total_integration_seconds,
            total_frames=m.total_frames, completion_pct=m.completion_pct,
            first_session=m.first_session, last_session=m.last_session,
        )
        for m in await list_mosaic_summaries(session)
    ]


@router.get("/mosaics/{mosaic_id}", response_model=s.MosaicDetail)
async def get_mosaic(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    from app.api.mosaics import get_mosaic_detail

    d = await get_mosaic_detail(mosaic_id=mosaic_id, session=session, user=None)
    return s.MosaicDetail(
        id=d.id,
        name=d.name,
        notes=d.notes,
        total_integration_seconds=d.total_integration_seconds,
        total_frames=d.total_frames,
        available_filters=d.available_filters,
        panels=[
            s.MosaicPanel(
                panel_id=p.panel_id,
                target_id=p.target_id,
                target_name=p.target_name,
                panel_label=p.panel_label,
                sort_order=p.sort_order,
                position=s.Position(ra=p.ra, dec=p.dec),
                total_integration_seconds=p.total_integration_seconds,
                total_frames=p.total_frames,
                filter_totals=p.filter_distribution,
                last_session_date=p.last_session_date,
            )
            for p in d.panels
        ],
    )


# --- Scan ------------------------------------------------------------------

@router.get("/scan/status", response_model=s.ScanStatus)
async def scan_status():
    from app.services.scan_state import get_scan_state

    async with async_redis() as r:
        snap = await get_scan_state(r)
    return s.ScanStatus(
        state=snap.state,
        running=snap.state in ("scanning", "ingesting", "stalled"),
        pending_rescan=snap.pending_rescan,
        started_at=snap.started_at,
        completed_at=snap.completed_at,
        discovered=snap.discovered,
        total=snap.total,
        completed=snap.completed,
        failed=snap.failed,
        percent=snap.percent,
        message=snap.message,
    )


@router.post(
    "/scan",
    response_model=s.ScanAccepted,
    status_code=202,
    dependencies=[Depends(require_write_key)],
)
async def start_scan():
    """Start a scan, or record a rescan to run after the one in flight."""
    from app.services.scan_state import request_scan

    return s.ScanAccepted(status=await request_scan())


# --- Act: point a telescope / planetarium ----------------------------------

class PointRequest(BaseModel):
    # Which configured instance to drive. Defaults to the first enabled one.
    instance: str | None = None


async def _instance_url(session: AsyncSession, kind: str, name: str | None) -> str:
    general = await _general_settings(session)
    instances = [
        i for i in general.get(f"{kind}_instances", [])
        if i.get("enabled") and i.get("url")
    ]
    if name:
        instances = [i for i in instances if i.get("name") == name]
    if not instances:
        raise HTTPException(
            status_code=404,
            detail=f"No enabled {kind} instance named {name!r}" if name
            else f"No enabled {kind} instance configured",
        )
    return instances[0]["url"]


async def _pointable(session: AsyncSession, target_id: uuid.UUID) -> Target:
    target = await _require_target(session, target_id)
    if target.ra is None or target.dec is None:
        raise HTTPException(status_code=409, detail="Target has no coordinates")
    return target


@router.post(
    "/targets/{target_id}/point/nina",
    response_model=IntegrationResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(require_write_key)],
)
async def point_nina(
    target_id: uuid.UUID,
    body: PointRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    from app.api.integrations import NinaRequest, send_to_nina

    target = await _pointable(session, target_id)
    url = await _instance_url(session, "nina", (body or PointRequest()).instance)
    return await send_to_nina(
        NinaRequest(
            url=url, ra=target.ra, dec=target.dec,
            position_angle=target.position_angle,
        ),
        current_user=None,
    )


@router.post(
    "/targets/{target_id}/point/stellarium",
    response_model=IntegrationResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(require_write_key)],
)
async def point_stellarium(
    target_id: uuid.UUID,
    body: PointRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    from app.api.integrations import StellariumRequest, send_to_stellarium

    target = await _pointable(session, target_id)
    url = await _instance_url(session, "stellarium", (body or PointRequest()).instance)
    return await send_to_stellarium(
        StellariumRequest(
            url=url, ra=target.ra, dec=target.dec,
            target_name=target.primary_name,
        ),
        current_user=None,
    )


# --- Act: notes ------------------------------------------------------------

@router.put(
    "/targets/{target_id}/notes",
    response_model=StatusResponse,
    dependencies=[Depends(require_write_key)],
)
async def put_target_notes(
    target_id: uuid.UUID,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
):
    from app.api.targets import update_target_notes

    await _require_target(session, target_id)
    return await update_target_notes(
        target_id=str(target_id), body=body, session=session, user=None,
    )


@router.put(
    "/targets/{target_id}/sessions/{date}/notes",
    response_model=StatusResponse,
    dependencies=[Depends(require_write_key)],
)
async def put_session_notes(
    target_id: uuid.UUID,
    date: str,
    body: NotesUpdate,
    session: AsyncSession = Depends(get_session),
):
    from app.api.targets import update_session_notes

    await _require_target(session, target_id)
    try:
        return await update_session_notes(
            target_id=str(target_id), date=date, body=body,
            session=session, user=None,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
