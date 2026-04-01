import re
import uuid
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
import sqlalchemy as sa
from sqlalchemy import select, or_, and_, func, cast, Float, Date, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.models import Target, Image
from app.models.user import User
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment, expand_canonical
from app.schemas.target import (
    TargetAggregationResponse, TargetAggregation, SessionSummary,
    AggregateStats, EquipmentResponse, SessionDetailResponse,
    TargetDetailResponse, SessionOverview, FilterDetail, FilterMedian, SessionInsight, FrameRecord,
    TargetSearchResultFuzzy, ObjectTypeCount,
)

router = APIRouter(prefix="/targets", tags=["targets"])

# ---------------------------------------------------------------------------
# SIMBAD object type → human-readable category mapping
# The first code in the comma-separated SIMBAD type string is the primary.
# ---------------------------------------------------------------------------
_SIMBAD_CATEGORY_MAP: dict[str, str] = {
    "HII": "Emission Nebula",
    "sh": "Emission Nebula",
    "GNe": "Reflection Nebula",
    "RNe": "Reflection Nebula",
    "DNe": "Dark Nebula",
    "Cld": "Dark Nebula",
    "MoC": "Dark Nebula",
    "PN": "Planetary Nebula",
    "SNR": "Supernova Remnant",
    "G": "Galaxy",
    "H2G": "Galaxy",
    "GiG": "Galaxy",
    "GiC": "Galaxy",
    "GiP": "Galaxy",
    "rG": "Galaxy",
    "AGN": "Galaxy",
    "Sy2": "Galaxy",
    "LIN": "Galaxy",
    "QSO": "Galaxy",
    "PoG": "Galaxy",
    "IG": "Galaxy",
    "OpC": "Open Cluster",
    "Cl*": "Open Cluster",
    "GlC": "Globular Cluster",
    "*": "Star",
    "**": "Star",
    "Ae*": "Star",
}


def _categorize_object_type(raw: str | None) -> str:
    """Map a raw SIMBAD object type string to a human-readable category."""
    if not raw:
        return "Other"
    primary = raw.split(",")[0].strip()
    return _SIMBAD_CATEGORY_MAP.get(primary, "Other")


# --- 1. Search (must be FIRST) ---

@router.get("/search", response_model=list[TargetSearchResultFuzzy])
async def search_targets(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Search targets by name or alias with fuzzy trigram matching."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"

    # Tier 1: Exact substring matches — exclude soft-deleted
    aliases_str = func.array_to_string(Target.aliases, ' ')
    exact_query = (
        select(Target)
        .where(
            Target.merged_into_id.is_(None),
            or_(
                Target.primary_name.ilike(pattern),
                Target.catalog_id.ilike(pattern),
                Target.common_name.ilike(pattern),
                aliases_str.ilike(pattern),
            ),
        )
        .limit(limit)
    )
    exact_result = await session.execute(exact_query)
    exact_targets = exact_result.scalars().all()

    exact_ids = {t.id for t in exact_targets}
    results = []
    for t in exact_targets:
        match_source = None
        if q.upper() not in t.primary_name.upper():
            for alias in (t.aliases or []):
                if q.upper() in alias.upper():
                    match_source = alias
                    break
        results.append(TargetSearchResultFuzzy(
            id=t.id,
            primary_name=t.primary_name,
            object_type=t.object_type,
            aliases=t.aliases or [],
            match_source=match_source,
            similarity_score=1.0,
        ))

    # Tier 2: Fuzzy trigram matches if we need more
    if len(results) < limit:
        remaining = limit - len(results)
        searchable_text = func.concat(
            func.coalesce(Target.catalog_id, ''), ' ',
            func.coalesce(Target.common_name, ''), ' ',
            func.array_to_string(Target.aliases, ' '),
        )
        fuzzy_score = func.similarity(searchable_text, q)
        fuzzy_query = (
            select(Target, fuzzy_score.label("score"))
            .where(
                Target.merged_into_id.is_(None),
                Target.id.notin_(exact_ids) if exact_ids else True,
                fuzzy_score > 0.3,
            )
            .order_by(fuzzy_score.desc())
            .limit(remaining)
        )
        fuzzy_result = await session.execute(fuzzy_query)
        for target, score in fuzzy_result.all():
            best_alias = None
            for alias in (target.aliases or []):
                if q.upper() in alias.upper():
                    best_alias = alias
                    break
            results.append(TargetSearchResultFuzzy(
                id=target.id,
                primary_name=target.primary_name,
                object_type=target.object_type,
                aliases=target.aliases or [],
                match_source=best_alias,
                similarity_score=float(score),
            ))

    return results


# --- 2. Equipment (SECOND — before path-parameter routes) ---

@router.get("/equipment", response_model=EquipmentResponse)
async def get_equipment(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return distinct camera and telescope values."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)
    cam_result = await session.execute(
        select(Image.camera).where(Image.camera.isnot(None)).distinct().order_by(Image.camera)
    )
    tel_result = await session.execute(
        select(Image.telescope).where(Image.telescope.isnot(None)).distinct().order_by(Image.telescope)
    )
    raw_cameras = [r[0] for r in cam_result.all() if r[0]]
    raw_telescopes = [r[0] for r in tel_result.all() if r[0]]

    # Track which canonical names have multiple raw names (grouped)
    cam_canonical: dict[str, set[str]] = {}
    for c in raw_cameras:
        canonical = normalize_equipment(c, cam_map) or c
        cam_canonical.setdefault(canonical, set()).add(c)
    tel_canonical: dict[str, set[str]] = {}
    for t in raw_telescopes:
        canonical = normalize_equipment(t, tel_map) or t
        tel_canonical.setdefault(canonical, set()).add(t)

    from app.schemas.target import EquipmentOption
    cameras = [EquipmentOption(name=name, grouped=len(raw) > 1) for name, raw in sorted(cam_canonical.items())]
    telescopes = [EquipmentOption(name=name, grouped=len(raw) > 1) for name, raw in sorted(tel_canonical.items())]
    return EquipmentResponse(
        cameras=cameras,
        telescopes=telescopes,
    )


# --- 2b. FITS keys (before path-parameter routes) ---

@router.get("/fits-keys", response_model=list[str])
async def get_fits_keys(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return distinct FITS header keys found across all images."""
    result = await session.execute(
        text("SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers) AS key ORDER BY key")
    )
    return [row[0] for row in result.all()]


# --- 2c. Object types (before path-parameter routes) ---

@router.get("/object-types", response_model=list[ObjectTypeCount])
async def get_object_types(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return human-readable object type categories with target counts."""
    query = (
        select(Target.object_type, func.count(Target.id).label("count"))
        .where(
            Target.object_type.isnot(None),
            Target.merged_into_id.is_(None),
        )
        .group_by(Target.object_type)
    )
    result = await session.execute(query)

    # Aggregate raw SIMBAD types into human-readable categories
    category_counts: dict[str, int] = defaultdict(int)
    for raw_type, count in result.all():
        category = _categorize_object_type(raw_type)
        category_counts[category] += count

    return sorted(
        [ObjectTypeCount(object_type=cat, count=cnt) for cat, cnt in category_counts.items()],
        key=lambda x: x.count,
        reverse=True,
    )


# --- 2d. Target detail (before path-parameter routes) ---

@router.get("/{target_id:path}/detail", response_model=TargetDetailResponse)
async def get_target_detail(
    target_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return target identity with cumulative stats and session overviews."""
    if target_id == "obj:__uncategorized__":
        target_name = "Uncategorized"
        target_obj = None
        # Images with no resolved target AND no OBJECT header
        query = (
            select(Image)
            .where(
                Image.resolved_target_id.is_(None),
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
            )
            .order_by(Image.capture_date)
        )
    elif target_id.startswith("obj:"):
        object_name = target_id[4:]
        target_name = object_name
        target_obj = None
        query = (
            select(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == object_name,
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )
    else:
        try:
            tid = uuid.UUID(target_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid target ID")
        target_obj = await session.get(Target, tid)
        if not target_obj:
            raise HTTPException(status_code=404, detail="Target not found")
        if target_obj.merged_into_id is not None:
            raise HTTPException(404, "Target has been merged")
        target_name = target_obj.primary_name
        query = (
            select(Image)
            .where(
                Image.resolved_target_id == tid,
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )

    result = await session.execute(query)
    images = result.scalars().all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found for this target")

    filter_map, cam_map, tel_map = await load_alias_maps(session)

    sessions_map: dict[str, list] = defaultdict(list)
    all_hfr = []
    all_ecc = []
    all_fwhm = []
    all_guiding_rms = []
    all_detected_stars = []
    equipment_set: set[str] = set()
    filters_set: set[str] = set()
    total_exp = 0.0

    for img in images:
        date_key = img.capture_date.strftime("%Y-%m-%d") if img.capture_date else "unknown"
        sessions_map[date_key].append(img)
        total_exp += img.exposure_time or 0
        if img.median_hfr is not None:
            all_hfr.append(img.median_hfr)
        if img.eccentricity is not None:
            all_ecc.append(img.eccentricity)
        if img.fwhm is not None:
            all_fwhm.append(img.fwhm)
        if img.guiding_rms_arcsec is not None:
            all_guiding_rms.append(img.guiding_rms_arcsec)
        if img.detected_stars is not None:
            all_detected_stars.append(img.detected_stars)
        cam = normalize_equipment(img.camera, cam_map)
        tel = normalize_equipment(img.telescope, tel_map)
        f = normalize_filter(img.filter_used, filter_map)
        if cam:
            equipment_set.add(cam)
        if tel:
            equipment_set.add(tel)
        if f:
            filters_set.add(f)

    session_overviews = []
    for date_key in sorted(sessions_map.keys(), reverse=True):
        sess_images = sessions_map[date_key]
        sess_hfr = [i.median_hfr for i in sess_images if i.median_hfr is not None]
        sess_ecc = [i.eccentricity for i in sess_images if i.eccentricity is not None]
        sess_fwhm = [i.fwhm for i in sess_images if i.fwhm is not None]
        sess_detected_stars = [i.detected_stars for i in sess_images if i.detected_stars is not None]
        sess_guiding_rms = [i.guiding_rms_arcsec for i in sess_images if i.guiding_rms_arcsec is not None]
        sess_filters = sorted({normalize_filter(i.filter_used, filter_map) for i in sess_images if i.filter_used})
        sess_exp = sum(i.exposure_time or 0 for i in sess_images)

        # Per-filter medians for chart overlay
        filter_groups_sess: dict[str, list] = defaultdict(list)
        for img in sess_images:
            f = normalize_filter(img.filter_used, filter_map)
            if f:
                filter_groups_sess[f].append(img)

        sess_filter_medians = []
        for fname, fimages in sorted(filter_groups_sess.items()):
            f_hfr = [i.median_hfr for i in fimages if i.median_hfr is not None]
            f_ecc = [i.eccentricity for i in fimages if i.eccentricity is not None]
            f_fwhm = [i.fwhm for i in fimages if i.fwhm is not None]
            f_guiding = [i.guiding_rms_arcsec for i in fimages if i.guiding_rms_arcsec is not None]
            f_stars = [i.detected_stars for i in fimages if i.detected_stars is not None]
            sess_filter_medians.append(FilterMedian(
                filter_name=fname,
                median_hfr=statistics.median(f_hfr) if f_hfr else None,
                median_eccentricity=statistics.median(f_ecc) if f_ecc else None,
                median_fwhm=statistics.median(f_fwhm) if f_fwhm else None,
                median_guiding_rms=statistics.median(f_guiding) if f_guiding else None,
                median_detected_stars=statistics.median(f_stars) if f_stars else None,
            ))

        session_overviews.append(SessionOverview(
            session_date=date_key,
            integration_seconds=sess_exp,
            frame_count=len(sess_images),
            median_hfr=statistics.median(sess_hfr) if sess_hfr else None,
            median_eccentricity=statistics.median(sess_ecc) if sess_ecc else None,
            filters_used=sess_filters,
            camera=normalize_equipment(sess_images[0].camera, cam_map),
            telescope=normalize_equipment(sess_images[0].telescope, tel_map),
            median_fwhm=statistics.median(sess_fwhm) if sess_fwhm else None,
            median_detected_stars=statistics.median(sess_detected_stars) if sess_detected_stars else None,
            median_guiding_rms_arcsec=statistics.median(sess_guiding_rms) if sess_guiding_rms else None,
            filter_medians=sess_filter_medians,
        ))

    sorted_dates = sorted(sessions_map.keys())

    return TargetDetailResponse(
        target_id=target_id,
        primary_name=target_name,
        aliases=target_obj.aliases if target_obj else [],
        object_type=target_obj.object_type if target_obj else None,
        ra=target_obj.ra if target_obj else None,
        dec=target_obj.dec if target_obj else None,
        total_integration_seconds=total_exp,
        total_frames=len(images),
        avg_hfr=statistics.mean(all_hfr) if all_hfr else None,
        avg_eccentricity=statistics.mean(all_ecc) if all_ecc else None,
        filters_used=sorted(filters_set),
        equipment=sorted(equipment_set),
        first_session_date=sorted_dates[0] if sorted_dates else "",
        last_session_date=sorted_dates[-1] if sorted_dates else "",
        session_count=len(sessions_map),
        sessions=session_overviews,
        avg_fwhm=statistics.mean(all_fwhm) if all_fwhm else None,
        avg_guiding_rms_arcsec=statistics.mean(all_guiding_rms) if all_guiding_rms else None,
        avg_detected_stars=statistics.mean(all_detected_stars) if all_detected_stars else None,
    )


# --- 3. Aggregation (THIRD — after fixed paths, before path params) ---

@router.get("", response_model=TargetAggregationResponse)
async def list_targets_aggregated(
    session: AsyncSession = Depends(get_session),
    search: str | None = Query(None),
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    user: User = Depends(get_current_user),
):
    """Return targets with aggregated session data, filtered by query params."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # Base query: only LIGHT frames that have a known object name
    base_filter = [Image.image_type == "LIGHT"]

    # Exclude soft-deleted (merged) targets
    base_filter.append(
        or_(
            Image.resolved_target_id.is_(None),
            Target.merged_into_id.is_(None),
        )
    )

    if camera:
        cam_variants = expand_canonical(camera, cam_map)
        base_filter.append(Image.camera.in_(cam_variants))
    if telescope:
        tel_variants = expand_canonical(telescope, tel_map)
        base_filter.append(Image.telescope.in_(tel_variants))
    if filters:
        filter_list = [f.strip() for f in filters.split(",")]
        all_filter_variants = []
        for f in filter_list:
            all_filter_variants.extend(expand_canonical(f, filter_map))
        base_filter.append(Image.filter_used.in_(all_filter_variants))
    if date_from:
        base_filter.append(Image.capture_date >= date_from)
    if date_to:
        base_filter.append(Image.capture_date <= date_to)
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        aliases_str = func.array_to_string(Target.aliases, ' ')
        searchable_text = func.concat(
            func.coalesce(Target.catalog_id, ''), ' ',
            func.coalesce(Target.common_name, ''), ' ',
            aliases_str,
        )
        # Search in target name, aliases, OR OBJECT header for unresolved images
        base_filter.append(
            or_(
                Target.primary_name.ilike(pattern),
                Target.catalog_id.ilike(pattern),
                Target.common_name.ilike(pattern),
                aliases_str.ilike(pattern),
                func.similarity(searchable_text, search) > 0.3,
                Image.raw_headers["OBJECT"].astext.ilike(pattern),
            )
        )

    if object_type:
        type_list = [t.strip() for t in object_type.split(",")]
        has_unresolved = "Unresolved" in type_list
        categories = [t for t in type_list if t != "Unresolved"]

        if categories:
            # Reverse-map human categories to SIMBAD primary codes
            matching_codes = set()
            for code, category in _SIMBAD_CATEGORY_MAP.items():
                if category in categories:
                    matching_codes.add(code)

            # Build SQL: match targets whose primary code (before first comma) is in the set
            # Use a startswith check for each matching code
            type_conditions = [
                Target.object_type.like(f"{code},%") | (Target.object_type == code)
                for code in matching_codes
            ]
            # Also match "Other" category — types not in the map
            if "Other" in categories:
                mapped_prefixes = list(_SIMBAD_CATEGORY_MAP.keys())
                other_conditions = [
                    ~Target.object_type.like(f"{code},%") & (Target.object_type != code)
                    for code in mapped_prefixes
                ]
                type_conditions.append(and_(*other_conditions))

            if has_unresolved:
                type_conditions.append(Image.resolved_target_id.is_(None))
            base_filter.append(or_(*type_conditions))
        elif has_unresolved:
            base_filter.append(Image.resolved_target_id.is_(None))

    # FITS header queries (AND logic between rows)
    if fits_key and fits_op and fits_val:
        for key, op_str, val in zip(fits_key, fits_op, fits_val):
            if not re.match(r'^[A-Za-z0-9_-]{1,20}$', key):
                continue
            json_field = Image.raw_headers[key].astext
            if op_str == "eq":
                base_filter.append(json_field == val)
            elif op_str == "neq":
                base_filter.append(json_field != val)
            elif op_str == "gt":
                try:
                    base_filter.append(cast(json_field, Float) > float(val))
                except ValueError:
                    continue
            elif op_str == "lt":
                try:
                    base_filter.append(cast(json_field, Float) < float(val))
                except ValueError:
                    continue
            elif op_str == "gte":
                try:
                    base_filter.append(cast(json_field, Float) >= float(val))
                except ValueError:
                    continue
            elif op_str == "lte":
                try:
                    base_filter.append(cast(json_field, Float) <= float(val))
                except ValueError:
                    continue
            elif op_str == "contains":
                escaped_val = val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                base_filter.append(json_field.ilike(f"%{escaped_val}%"))

    # ---------------------------------------------------------------
    # Phase 1: SQL GROUP BY to get paginated target keys with totals
    # ---------------------------------------------------------------
    # Composite grouping key: resolved target UUID or 'obj:<OBJECT header>'
    group_key = func.coalesce(
        cast(Image.resolved_target_id, sa.String),
        func.concat(sa.literal("obj:"), func.coalesce(Image.raw_headers["OBJECT"].astext, "__uncategorized__")),
    )

    # Build the grouped query with aggregates
    grouped = (
        select(
            group_key.label("target_key"),
            func.coalesce(Target.primary_name, Image.raw_headers["OBJECT"].astext, sa.literal("Uncategorized")).label("primary_name"),
            func.sum(func.coalesce(Image.exposure_time, 0)).label("total_integration"),
            func.count(Image.id).label("total_frames"),
            func.count(func.distinct(cast(Image.capture_date, Date))).label("session_count"),
            func.avg(Image.median_hfr).label("avg_hfr"),
            func.avg(Image.fwhm).label("avg_fwhm"),
            func.avg(Image.eccentricity).label("avg_eccentricity"),
            func.avg(cast(Image.detected_stars, Float)).label("avg_stars"),
            func.avg(Image.guiding_rms_arcsec).label("avg_guiding_rms"),
            func.avg(Image.adu_mean).label("avg_adu_mean"),
            func.avg(Image.focuser_temp).label("avg_focuser_temp"),
            func.avg(Image.ambient_temp).label("avg_ambient_temp"),
            func.avg(Image.humidity).label("avg_humidity"),
            func.avg(Image.airmass).label("avg_airmass"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter)
        .group_by(group_key, Target.primary_name, Image.raw_headers["OBJECT"].astext)
    )

    # HAVING clauses for metric range filters (use AVG instead of MEDIAN)
    having_clauses = []
    if hfr_min is not None:
        having_clauses.append(func.avg(Image.median_hfr) >= hfr_min)
    if hfr_max is not None:
        having_clauses.append(func.avg(Image.median_hfr) <= hfr_max)
    if fwhm_min is not None:
        having_clauses.append(func.avg(Image.fwhm) >= fwhm_min)
    if fwhm_max is not None:
        having_clauses.append(func.avg(Image.fwhm) <= fwhm_max)
    if eccentricity_min is not None:
        having_clauses.append(func.avg(Image.eccentricity) >= eccentricity_min)
    if eccentricity_max is not None:
        having_clauses.append(func.avg(Image.eccentricity) <= eccentricity_max)
    if stars_min is not None:
        having_clauses.append(func.avg(cast(Image.detected_stars, Float)) >= stars_min)
    if stars_max is not None:
        having_clauses.append(func.avg(cast(Image.detected_stars, Float)) <= stars_max)
    if guiding_rms_min is not None:
        having_clauses.append(func.avg(Image.guiding_rms_arcsec) >= guiding_rms_min)
    if guiding_rms_max is not None:
        having_clauses.append(func.avg(Image.guiding_rms_arcsec) <= guiding_rms_max)
    if adu_mean_min is not None:
        having_clauses.append(func.avg(Image.adu_mean) >= adu_mean_min)
    if adu_mean_max is not None:
        having_clauses.append(func.avg(Image.adu_mean) <= adu_mean_max)
    if focuser_temp_min is not None:
        having_clauses.append(func.avg(Image.focuser_temp) >= focuser_temp_min)
    if focuser_temp_max is not None:
        having_clauses.append(func.avg(Image.focuser_temp) <= focuser_temp_max)
    if ambient_temp_min is not None:
        having_clauses.append(func.avg(Image.ambient_temp) >= ambient_temp_min)
    if ambient_temp_max is not None:
        having_clauses.append(func.avg(Image.ambient_temp) <= ambient_temp_max)
    if humidity_min is not None:
        having_clauses.append(func.avg(Image.humidity) >= humidity_min)
    if humidity_max is not None:
        having_clauses.append(func.avg(Image.humidity) <= humidity_max)
    if airmass_min is not None:
        having_clauses.append(func.avg(Image.airmass) >= airmass_min)
    if airmass_max is not None:
        having_clauses.append(func.avg(Image.airmass) <= airmass_max)

    if having_clauses:
        grouped = grouped.having(and_(*having_clauses))

    has_metric_filters = bool(having_clauses)

    # ---------------------------------------------------------------
    # Phase 2: Sidebar aggregates (lightweight — counts across ALL
    # matching targets, not just the page)
    # ---------------------------------------------------------------
    count_sub = grouped.subquery()
    agg_query = select(
        func.count().label("target_count"),
        func.sum(count_sub.c.total_integration).label("total_integration"),
        func.sum(count_sub.c.total_frames).label("total_frames"),
        func.min(count_sub.c.primary_name).label("_unused"),  # force evaluation
    ).select_from(count_sub)
    agg_result = await session.execute(agg_query)
    agg_row = agg_result.one()
    total_count = agg_row.target_count or 0

    # Date range from filtered images (quick separate query)
    date_range_query = (
        select(
            func.min(cast(Image.capture_date, Date)).label("oldest"),
            func.max(cast(Image.capture_date, Date)).label("newest"),
        )
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(*base_filter)
    )
    date_range_result = await session.execute(date_range_query)
    date_row = date_range_result.one()
    oldest_date = str(date_row.oldest) if date_row.oldest else None
    newest_date = str(date_row.newest) if date_row.newest else None

    aggregates = AggregateStats(
        total_integration_seconds=float(agg_row.total_integration or 0),
        target_count=total_count,
        total_frames=int(agg_row.total_frames or 0),
        disk_usage_bytes=0,
        oldest_date=oldest_date,
        newest_date=newest_date,
    )

    if total_count == 0:
        return TargetAggregationResponse(
            targets=[],
            aggregates=aggregates,
            total_count=0,
            page=page,
            page_size=page_size,
        )

    # ---------------------------------------------------------------
    # Phase 3: Paginated target keys, ordered by total integration
    # ---------------------------------------------------------------
    offset = (page - 1) * page_size
    page_query = (
        grouped
        .order_by(func.sum(func.coalesce(Image.exposure_time, 0)).desc())
        .limit(page_size)
        .offset(offset)
    )
    page_result = await session.execute(page_query)
    page_rows = page_result.all()

    if not page_rows:
        return TargetAggregationResponse(
            targets=[],
            aggregates=aggregates,
            total_count=total_count,
            page=page,
            page_size=page_size,
        )

    # Collect target keys and basic aggregates from the page
    page_keys: list[str] = []
    page_basics: dict[str, dict] = {}
    for row in page_rows:
        tk = row.target_key
        page_keys.append(tk)
        page_basics[tk] = {
            "target_key": tk,
            "primary_name": row.primary_name,
            "total_integration": float(row.total_integration),
            "total_frames": int(row.total_frames),
            "session_count": int(row.session_count),
        }

    # ---------------------------------------------------------------
    # Phase 4: Detail queries for the current page's targets only
    # ---------------------------------------------------------------
    # Build a WHERE clause to match only the current page's images
    page_key_conditions = []
    page_uuids = []
    page_obj_names = []
    has_uncategorized = False
    for tk in page_keys:
        if tk == "obj:__uncategorized__":
            has_uncategorized = True
        elif tk.startswith("obj:"):
            page_obj_names.append(tk[4:])
        else:
            try:
                page_uuids.append(uuid.UUID(tk))
            except ValueError:
                pass

    if page_uuids:
        page_key_conditions.append(Image.resolved_target_id.in_(page_uuids))
    if page_obj_names:
        page_key_conditions.append(
            and_(
                Image.resolved_target_id.is_(None),
                Image.raw_headers["OBJECT"].astext.in_(page_obj_names),
            )
        )
    if has_uncategorized:
        page_key_conditions.append(
            and_(
                Image.resolved_target_id.is_(None),
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
            )
        )

    # Fetch detail images for just this page's targets
    detail_query = (
        select(Image, Target)
        .outerjoin(Target, Image.resolved_target_id == Target.id)
        .where(
            Image.image_type == "LIGHT",
            or_(*page_key_conditions) if page_key_conditions else sa.literal(False),
        )
    )
    # Re-apply the same base WHERE filters (camera, telescope, filters, dates, etc.)
    # We already have them in base_filter but they include the merged-target check
    # which requires the join. Re-apply them all for correctness.
    detail_query = detail_query.where(*base_filter)

    detail_result = await session.execute(detail_query)
    detail_rows = detail_result.all()

    # Build per-target detail maps
    filter_dist: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    equipment_map: dict[str, set] = defaultdict(set)
    sessions_detail: dict[str, dict[str, dict]] = defaultdict(dict)
    aliases_map: dict[str, set] = defaultdict(set)

    for image, target in detail_rows:
        if target:
            tk = str(target.id)
        else:
            obj_name = (image.raw_headers or {}).get("OBJECT")
            if not obj_name:
                tk = "obj:__uncategorized__"
            else:
                tk = f"obj:{obj_name}"

        if tk not in page_basics:
            continue  # not on this page

        exp = image.exposure_time or 0
        f = normalize_filter(image.filter_used, filter_map)
        cam = normalize_equipment(image.camera, cam_map)
        tel = normalize_equipment(image.telescope, tel_map)

        if f:
            filter_dist[tk][f] += exp
        if cam:
            equipment_map[tk].add(cam)
        if tel:
            equipment_map[tk].add(tel)

        # Collect FITS OBJECT as alias
        fits_object = (image.raw_headers or {}).get("OBJECT")
        if fits_object:
            aliases_map[tk].add(fits_object)

        # Session detail
        date_key = image.capture_date.strftime("%Y-%m-%d") if image.capture_date else "unknown"
        if date_key not in sessions_detail[tk]:
            sessions_detail[tk][date_key] = {
                "session_date": date_key,
                "integration_seconds": 0,
                "frame_count": 0,
                "filters_set": set(),
            }
        s = sessions_detail[tk][date_key]
        s["integration_seconds"] += exp
        s["frame_count"] += 1
        if f:
            s["filters_set"].add(f)

    # ---------------------------------------------------------------
    # Phase 5: Assemble the response
    # ---------------------------------------------------------------
    target_list = []
    for tk in page_keys:
        basics = page_basics[tk]
        sessions_list = sorted(
            sessions_detail.get(tk, {}).values(),
            key=lambda x: x["session_date"],
            reverse=True,
        )
        total_session_count = basics["session_count"]
        matched_session_count = len(sessions_list) if has_metric_filters else None

        sessions = [
            SessionSummary(
                session_date=s["session_date"],
                integration_seconds=s["integration_seconds"],
                frame_count=s["frame_count"],
                filters_used=sorted(s["filters_set"]),
            )
            for s in sessions_list
        ]

        target_list.append(TargetAggregation(
            target_id=basics["target_key"],
            primary_name=basics["primary_name"],
            aliases=sorted(aliases_map.get(tk, set())),
            total_integration_seconds=basics["total_integration"],
            total_frames=basics["total_frames"],
            filter_distribution=dict(filter_dist.get(tk, {})),
            equipment=sorted(equipment_map.get(tk, set())),
            sessions=sessions,
            matched_sessions=matched_session_count,
            total_sessions=total_session_count if matched_session_count is not None else None,
        ))

    return TargetAggregationResponse(
        targets=target_list,
        aggregates=aggregates,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


# --- 4. Session detail (LAST — has path parameters) ---


def _compute_insights(
    *,
    median_hfr: float | None,
    median_ecc: float | None,
    hfr_values: list[float],
    ecc_values: list[float],
    temp_values: list[float],
    target_avg_hfr: float | None,
    is_best_hfr: bool,
    first_frame,
    last_frame,
) -> list[SessionInsight]:
    insights = []

    if first_frame.capture_date and last_frame.capture_date:
        duration = last_frame.capture_date - first_frame.capture_date
        hours = duration.total_seconds() / 3600
        minutes = (duration.total_seconds() % 3600) / 60
        insights.append(SessionInsight(
            level="info",
            message=f"Session duration: {int(hours)}h {int(minutes)}m ({first_frame.capture_date.strftime('%H:%M')} \u2192 {last_frame.capture_date.strftime('%H:%M')})",
        ))

    if median_hfr is not None and target_avg_hfr is not None:
        if is_best_hfr:
            insights.append(SessionInsight(
                level="good",
                message=f"Best HFR session for this target (median {median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
            ))
        elif median_hfr > target_avg_hfr * 1.3:
            insights.append(SessionInsight(
                level="warning",
                message=f"Poor HFR session (median {median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
            ))

    if temp_values:
        temp_range = max(temp_values) - min(temp_values)
        if temp_range < 1.0:
            insights.append(SessionInsight(
                level="good",
                message=f"Stable sensor temperature ({min(temp_values):.0f}\u00b0C \u00b1 {temp_range:.1f}\u00b0C)",
            ))
        elif temp_range >= 3.0:
            insights.append(SessionInsight(
                level="warning",
                message=f"Unstable sensor temperature (range: {min(temp_values):.0f}\u00b0C to {max(temp_values):.0f}\u00b0C)",
            ))

    if median_hfr is not None and len(hfr_values) > 2:
        threshold = median_hfr * 1.5
        outlier_count = sum(1 for v in hfr_values if v > threshold)
        if outlier_count > 0:
            insights.append(SessionInsight(
                level="warning",
                message=f"{outlier_count} frame{'s' if outlier_count > 1 else ''} with HFR outlier{'s' if outlier_count > 1 else ''} (> {threshold:.1f})",
            ))

    if median_ecc is not None and len(ecc_values) > 2:
        threshold = median_ecc * 1.5
        outlier_count = sum(1 for v in ecc_values if v > threshold)
        if outlier_count > 0:
            insights.append(SessionInsight(
                level="warning",
                message=f"{outlier_count} frame{'s' if outlier_count > 1 else ''} with eccentricity outlier{'s' if outlier_count > 1 else ''} (> {threshold:.2f})",
            ))

    return insights


@router.get("/{target_id:path}/sessions/{date}", response_model=SessionDetailResponse)
async def get_session_detail(
    target_id: str,
    date: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return detailed session data for a target on a specific date."""
    if target_id == "obj:__uncategorized__":
        target_name = "Uncategorized"
        target_obj = None
        _no_object = or_(
            ~Image.raw_headers.has_key("OBJECT"),
            Image.raw_headers["OBJECT"].astext == "",
            Image.raw_headers["OBJECT"].is_(None),
        )
        query = (
            select(Image)
            .where(
                Image.resolved_target_id.is_(None),
                _no_object,
                Image.capture_date >= datetime.fromisoformat(date),
                Image.capture_date < datetime.fromisoformat(date) + timedelta(days=1),
            )
            .order_by(Image.capture_date)
        )
        all_images_query = (
            select(Image)
            .where(
                Image.resolved_target_id.is_(None),
                _no_object,
            )
        )
    elif target_id.startswith("obj:"):
        object_name = target_id[4:]
        target_name = object_name
        target_obj = None
        query = (
            select(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == object_name,
                Image.capture_date >= datetime.fromisoformat(date),
                Image.capture_date < datetime.fromisoformat(date) + timedelta(days=1),
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )
        all_images_query = (
            select(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == object_name,
                Image.image_type == "LIGHT",
            )
        )
    else:
        try:
            tid = uuid.UUID(target_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid target ID")
        target_obj = await session.get(Target, tid)
        if not target_obj:
            raise HTTPException(status_code=404, detail="Target not found")
        target_name = target_obj.primary_name
        query = (
            select(Image)
            .where(
                Image.resolved_target_id == tid,
                Image.capture_date >= datetime.fromisoformat(date),
                Image.capture_date < datetime.fromisoformat(date) + timedelta(days=1),
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )
        all_images_query = (
            select(Image)
            .where(
                Image.resolved_target_id == tid,
                Image.image_type == "LIGHT",
            )
        )

    result = await session.execute(query)
    images = result.scalars().all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found for this session")

    all_result = await session.execute(all_images_query)
    all_images = all_result.scalars().all()
    all_hfr_values = [i.median_hfr for i in all_images if i.median_hfr is not None]
    target_avg_hfr = statistics.mean(all_hfr_values) if all_hfr_values else None

    filter_map, cam_map, tel_map = await load_alias_maps(session)

    total_exp = sum(img.exposure_time or 0 for img in images)
    filters_used: dict[str, int] = {}
    hfr_values = []
    ecc_values = []
    temp_values = []
    fwhm_values = []
    guiding_rms_values = []
    detected_stars_values = []
    airmass_values = []
    ambient_temp_values = []
    humidity_values = []
    cloud_cover_values = []

    for img in images:
        f = normalize_filter(img.filter_used, filter_map)
        if f:
            filters_used[f] = filters_used.get(f, 0) + 1
        if img.median_hfr is not None:
            hfr_values.append(img.median_hfr)
        if img.eccentricity is not None:
            ecc_values.append(img.eccentricity)
        if img.sensor_temp is not None:
            temp_values.append(img.sensor_temp)
        if img.fwhm is not None:
            fwhm_values.append(img.fwhm)
        if img.guiding_rms_arcsec is not None:
            guiding_rms_values.append(img.guiding_rms_arcsec)
        if img.detected_stars is not None:
            detected_stars_values.append(img.detected_stars)
        if img.airmass is not None:
            airmass_values.append(img.airmass)
        if img.ambient_temp is not None:
            ambient_temp_values.append(img.ambient_temp)
        if img.humidity is not None:
            humidity_values.append(img.humidity)
        if img.cloud_cover is not None:
            cloud_cover_values.append(img.cloud_cover)

    ref_image = images[0]
    thumb_url = None
    if ref_image.thumbnail_path:
        filename = ref_image.thumbnail_path.split("/")[-1].split("\\")[-1]
        thumb_url = f"/thumbnails/{filename}"

    median_hfr = statistics.median(hfr_values) if hfr_values else None
    median_ecc = statistics.median(ecc_values) if ecc_values else None

    filter_groups: dict[str, list] = defaultdict(list)
    for img in images:
        f = normalize_filter(img.filter_used, filter_map)
        if f:
            filter_groups[f].append(img)

    filter_details = []
    for fname, fimages in sorted(filter_groups.items()):
        f_hfr = [i.median_hfr for i in fimages if i.median_hfr is not None]
        f_ecc = [i.eccentricity for i in fimages if i.eccentricity is not None]
        f_exp = sum(i.exposure_time or 0 for i in fimages)
        filter_details.append(FilterDetail(
            filter_name=fname,
            frame_count=len(fimages),
            integration_seconds=f_exp,
            median_hfr=statistics.median(f_hfr) if f_hfr else None,
            median_eccentricity=statistics.median(f_ecc) if f_ecc else None,
            exposure_time=fimages[0].exposure_time,
        ))

    frames = []
    for img in images:
        frames.append(FrameRecord(
            timestamp=img.capture_date.isoformat() if img.capture_date else "",
            filter_used=normalize_filter(img.filter_used, filter_map),
            exposure_time=img.exposure_time,
            median_hfr=img.median_hfr,
            eccentricity=img.eccentricity,
            sensor_temp=img.sensor_temp,
            gain=img.camera_gain,
            file_name=img.file_name,
            hfr_stdev=img.hfr_stdev,
            fwhm=img.fwhm,
            detected_stars=img.detected_stars,
            guiding_rms_arcsec=img.guiding_rms_arcsec,
            guiding_rms_ra_arcsec=img.guiding_rms_ra_arcsec,
            guiding_rms_dec_arcsec=img.guiding_rms_dec_arcsec,
            adu_stdev=img.adu_stdev,
            adu_mean=img.adu_mean,
            adu_median=img.adu_median,
            adu_min=img.adu_min,
            adu_max=img.adu_max,
            focuser_position=img.focuser_position,
            focuser_temp=img.focuser_temp,
            rotator_position=img.rotator_position,
            pier_side=img.pier_side,
            airmass=img.airmass,
            ambient_temp=img.ambient_temp,
            dew_point=img.dew_point,
            humidity=img.humidity,
            pressure=img.pressure,
            wind_speed=img.wind_speed,
            wind_direction=img.wind_direction,
            wind_gust=img.wind_gust,
            cloud_cover=img.cloud_cover,
            sky_quality=img.sky_quality,
        ))

    is_best_hfr = False
    if median_hfr is not None:
        all_session_dates: dict[str, list[float]] = defaultdict(list)
        for img in all_images:
            if img.median_hfr is not None and img.capture_date:
                dk = img.capture_date.strftime("%Y-%m-%d")
                all_session_dates[dk].append(img.median_hfr)
        all_session_medians = [statistics.median(v) for v in all_session_dates.values() if v]
        if all_session_medians:
            is_best_hfr = median_hfr <= min(all_session_medians)

    insights = _compute_insights(
        median_hfr=median_hfr,
        median_ecc=median_ecc,
        hfr_values=hfr_values,
        ecc_values=ecc_values,
        temp_values=temp_values,
        target_avg_hfr=target_avg_hfr,
        is_best_hfr=is_best_hfr,
        first_frame=images[0],
        last_frame=images[-1],
    )

    return SessionDetailResponse(
        target_name=target_name,
        session_date=date,
        thumbnail_url=thumb_url,
        frame_count=len(images),
        integration_seconds=total_exp,
        median_hfr=median_hfr,
        median_eccentricity=median_ecc,
        filters_used=filters_used,
        equipment={
            "camera": normalize_equipment(ref_image.camera, cam_map),
            "telescope": normalize_equipment(ref_image.telescope, tel_map),
        },
        raw_reference_header=ref_image.raw_headers,
        min_hfr=min(hfr_values) if hfr_values else None,
        max_hfr=max(hfr_values) if hfr_values else None,
        min_eccentricity=min(ecc_values) if ecc_values else None,
        max_eccentricity=max(ecc_values) if ecc_values else None,
        sensor_temp=statistics.median(temp_values) if temp_values else None,
        sensor_temp_min=min(temp_values) if temp_values else None,
        sensor_temp_max=max(temp_values) if temp_values else None,
        gain=ref_image.camera_gain,
        offset=next((int(img.raw_headers.get("OFFSET", 0)) for img in images if img.raw_headers and img.raw_headers.get("OFFSET") is not None), None),
        exposure_times=sorted(set(img.exposure_time for img in images if img.exposure_time is not None)),
        first_frame_time=images[0].capture_date.isoformat() if images[0].capture_date else None,
        last_frame_time=images[-1].capture_date.isoformat() if images[-1].capture_date else None,
        filter_details=filter_details,
        insights=insights,
        frames=frames,
        median_fwhm=statistics.median(fwhm_values) if fwhm_values else None,
        min_fwhm=min(fwhm_values) if fwhm_values else None,
        max_fwhm=max(fwhm_values) if fwhm_values else None,
        median_guiding_rms=statistics.median(guiding_rms_values) if guiding_rms_values else None,
        min_guiding_rms=min(guiding_rms_values) if guiding_rms_values else None,
        max_guiding_rms=max(guiding_rms_values) if guiding_rms_values else None,
        median_detected_stars=statistics.median(detected_stars_values) if detected_stars_values else None,
        median_airmass=statistics.median(airmass_values) if airmass_values else None,
        median_ambient_temp=statistics.median(ambient_temp_values) if ambient_temp_values else None,
        median_humidity=statistics.median(humidity_values) if humidity_values else None,
        median_cloud_cover=statistics.median(cloud_cover_values) if cloud_cover_values else None,
    )
