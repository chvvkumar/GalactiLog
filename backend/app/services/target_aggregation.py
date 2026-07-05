"""Target search, detail, export, aggregation and session-detail logic.

Pure extraction of the business/DB logic that used to live inline in
app/api/targets.py. Behavior (query shapes, response models, status codes via
HTTPException) is preserved exactly; the API handlers are thin wrappers around
these functions.
"""

import json
import logging
import re
import uuid
import statistics
from collections import defaultdict
from datetime import date as date_type, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, or_, func, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target, Image
from app.models.catalog_membership import TargetCatalogMembership
from app.models.session_note import SessionNote
from app.services.simbad import COMMON_NAME_MAP
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment, expand_canonical
from app.schemas.target import (
    TargetAggregationResponse, TargetAggregation, SessionSummary,
    AggregateStats, EquipmentResponse, SessionDetailResponse,
    TargetDetailResponse, SessionOverview, FilterDetail, FilterMedian, SessionInsight, FrameRecord,
    TargetSearchResultFuzzy, ObjectTypeCount, RigDetail,
)
from app.schemas.export import ExportResponse, ExportFilterRow, ExportEquipment, ExportCalibration
from app.services import frame_quality

logger = logging.getLogger(__name__)


def parse_sexa_ra(s: str) -> float | None:
    try:
        parts = s.strip().split()
        h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + sec / 3600) * 15
    except (ValueError, IndexError):
        return None


def parse_sexa_dec(s: str) -> float | None:
    try:
        s = s.strip()
        sign = -1 if s.startswith("-") else 1
        parts = s.lstrip("+-").split()
        d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return sign * (d + m / 60 + sec / 3600)
    except (ValueError, IndexError):
        return None


def build_rig_details(
    images: list,
    filter_map: dict,
    cam_map: dict,
    tel_map: dict,
) -> list:
    """Group images by normalized (telescope, camera) and return per-rig stats."""
    rig_buckets: dict[tuple[str | None, str | None], list] = defaultdict(list)
    for img in images:
        tel = normalize_equipment(img.telescope, tel_map)
        cam = normalize_equipment(img.camera, cam_map)
        rig_buckets[(tel, cam)].append(img)

    rig_details = []
    for (tel, cam), rig_images in sorted(rig_buckets.items(), key=lambda x: (x[0][0] or "", x[0][1] or "")):
        rig_label = f"{tel or 'Unknown'} / {cam or 'Unknown'}"
        rig_exp = sum(i.exposure_time or 0 for i in rig_images)
        rig_hfr = [i.median_hfr for i in rig_images if i.median_hfr is not None]
        rig_ecc = [i.eccentricity for i in rig_images if i.eccentricity is not None]
        rig_fwhm = [i.fwhm for i in rig_images if i.fwhm is not None]
        rig_guiding = [i.guiding_rms_arcsec for i in rig_images if i.guiding_rms_arcsec is not None]
        rig_stars = [i.detected_stars for i in rig_images if i.detected_stars is not None]

        # Per-filter breakdown within this rig (group by filter + exposure)
        rig_filter_groups: dict[tuple[str, float | None], list] = defaultdict(list)
        for img in rig_images:
            f = normalize_filter(img.filter_used, filter_map)
            if f:
                rig_filter_groups[(f, img.exposure_time)].append(img)

        rig_filter_details = []
        for (fname, exp), fimages in sorted(rig_filter_groups.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
            f_hfr = [i.median_hfr for i in fimages if i.median_hfr is not None]
            f_ecc = [i.eccentricity for i in fimages if i.eccentricity is not None]
            f_exp = sum(i.exposure_time or 0 for i in fimages)
            rig_filter_details.append(FilterDetail(
                filter_name=fname,
                frame_count=len(fimages),
                integration_seconds=f_exp,
                median_hfr=statistics.median(f_hfr) if f_hfr else None,
                median_eccentricity=statistics.median(f_ecc) if f_ecc else None,
                exposure_time=exp,
            ))

        # Build frame records for this rig
        rig_frames = []
        for img in sorted(rig_images, key=lambda i: i.capture_date or datetime.min):
            rig_frames.append(FrameRecord(
                timestamp=img.capture_date.isoformat() if img.capture_date else "",
                filter_used=normalize_filter(img.filter_used, filter_map),
                exposure_time=img.exposure_time,
                median_hfr=img.median_hfr,
                eccentricity=img.eccentricity,
                sensor_temp=img.sensor_temp,
                gain=img.camera_gain,
                file_name=img.file_name,
                image_id=str(img.id),
                file_path=img.file_path,
                thumbnail_url=f"/thumbnails/{img.thumbnail_path.split('/')[-1].split(chr(92))[-1]}" if img.thumbnail_path else None,
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
                rig=rig_label,
            ))

        # Gain/offset/thumbnail from first image in rig
        ref = rig_images[0]
        offset_val = next(
            (int(img.raw_headers.get("OFFSET", 0))
             for img in rig_images
             if img.raw_headers and img.raw_headers.get("OFFSET") is not None),
            None,
        )
        rig_thumb = None
        for img in rig_images:
            if img.thumbnail_path:
                fn = img.thumbnail_path.split("/")[-1].split("\\")[-1]
                rig_thumb = f"/thumbnails/{fn}"
                break

        rig_details.append(RigDetail(
            rig_label=rig_label,
            telescope=tel,
            camera=cam,
            frame_count=len(rig_images),
            integration_seconds=rig_exp,
            median_hfr=statistics.median(rig_hfr) if rig_hfr else None,
            median_eccentricity=statistics.median(rig_ecc) if rig_ecc else None,
            median_fwhm=statistics.median(rig_fwhm) if rig_fwhm else None,
            median_guiding_rms=statistics.median(rig_guiding) if rig_guiding else None,
            median_detected_stars=statistics.median(rig_stars) if rig_stars else None,
            gain=ref.camera_gain,
            offset=offset_val,
            exposure_times=sorted(set(i.exposure_time for i in rig_images if i.exposure_time is not None)),
            filter_details=rig_filter_details,
            frames=rig_frames,
            thumbnail_url=rig_thumb,
        ))

    return rig_details


# ---------------------------------------------------------------------------
# SIMBAD object type → human-readable category mapping
# The first code in the comma-separated SIMBAD type string is the primary.
# ---------------------------------------------------------------------------
SIMBAD_CATEGORY_MAP: dict[str, str] = {
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


# Solar-system categories for user-defined targets (planets, comets, ...).
# These are not SIMBAD otypes; they are assigned manually at creation.
SOLAR_SYSTEM_CATEGORIES: tuple[str, ...] = ("Planet", "Moon", "Sun", "Comet", "Asteroid")

# Category names themselves are valid object_type values (admin edits and
# custom targets store them directly), so categorization passes them through.
_CATEGORY_NAME_LOOKUP: dict[str, str] = {
    v.upper(): v
    for v in (*SIMBAD_CATEGORY_MAP.values(), *SOLAR_SYSTEM_CATEGORIES, "Other")
}


def categorize_object_type(raw: str | None) -> str:
    """Map a raw SIMBAD object type string to a human-readable category."""
    if not raw:
        return "Other"
    primary = raw.split(",")[0].strip()
    mapped = SIMBAD_CATEGORY_MAP.get(primary)
    if mapped:
        return mapped
    return _CATEGORY_NAME_LOOKUP.get(primary.upper(), "Other")


def sort_clause(sort_by: str, sort_dir: str) -> str:
    """Build SQL ORDER BY clause for target pagination."""
    col_map = {
        "integration": "total_integration",
        "lastSession": "last_session_date",
        "name": "primary_name",
    }
    col = col_map.get(sort_by, "total_integration")
    direction = "ASC" if sort_dir == "asc" else "DESC"
    nulls = "NULLS LAST" if direction == "DESC" else "NULLS FIRST"
    return f"{col} {direction} {nulls}"


def compute_insights(
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
            message=f"Session duration: {int(hours)}h {int(minutes)}m ({first_frame.capture_date.strftime('%H:%M')} → {last_frame.capture_date.strftime('%H:%M')})",
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
                message=f"Stable sensor temperature ({min(temp_values):.0f}°C ± {temp_range:.1f}°C)",
            ))
        elif temp_range >= 3.0:
            insights.append(SessionInsight(
                level="warning",
                message=f"Unstable sensor temperature (range: {min(temp_values):.0f}°C to {max(temp_values):.0f}°C)",
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


async def search_targets(
    q: str, limit: int, session: AsyncSession, *, include_unresolved: bool = False,
) -> list[TargetSearchResultFuzzy]:
    """Search targets by name or alias with fuzzy trigram matching.

    With include_unresolved, distinct unlinked OBJECT header names matching the
    query are appended as "obj:<name>" pseudo entries so merge flows can offer
    unresolved image groups as merge sources.
    """
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"

    # Also create a space-normalized pattern for catalog IDs like "M31" → "M 31"
    spaced = re.sub(r"([A-Za-z])(\d)", r"\1 \2", escaped)
    spaced_pattern = f"%{spaced}%" if spaced != escaped else None

    # Tier 1: Exact substring matches - exclude soft-deleted
    aliases_str = func.array_to_string(Target.aliases, ' ')
    ilike_conditions = [
        Target.primary_name.ilike(pattern),
        Target.catalog_id.ilike(pattern),
        Target.common_name.ilike(pattern),
        aliases_str.ilike(pattern),
    ]
    if spaced_pattern:
        ilike_conditions.extend([
            Target.primary_name.ilike(spaced_pattern),
            Target.catalog_id.ilike(spaced_pattern),
            Target.common_name.ilike(spaced_pattern),
            aliases_str.ilike(spaced_pattern),
        ])
    exact_query = (
        select(Target)
        .where(
            Target.merged_into_id.is_(None),
            or_(*ilike_conditions),
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

    # Tier 1.5: Common name map lookup - match colloquial names to catalog IDs
    if len(results) < limit:
        q_lower = q.lower()
        mapped_catalog_ids = set()
        for common_name, catalog_id in COMMON_NAME_MAP.items():
            if q_lower in common_name or common_name in q_lower:
                mapped_catalog_ids.add(catalog_id)
        if mapped_catalog_ids:
            exclude_ids = exact_ids | {r.id for r in results}
            map_conditions = [Target.catalog_id == cid for cid in mapped_catalog_ids]
            map_query = (
                select(Target)
                .where(
                    Target.merged_into_id.is_(None),
                    Target.id.notin_(exclude_ids) if exclude_ids else True,
                    or_(*map_conditions),
                )
                .limit(limit - len(results))
            )
            map_result = await session.execute(map_query)
            for t in map_result.scalars().all():
                # Find which common name matched for display
                matched_name = None
                for cn, cid in COMMON_NAME_MAP.items():
                    if cid == t.catalog_id and (q_lower in cn or cn in q_lower):
                        matched_name = cn.title()
                        break
                exact_ids.add(t.id)
                results.append(TargetSearchResultFuzzy(
                    id=t.id,
                    primary_name=t.primary_name,
                    object_type=t.object_type,
                    aliases=t.aliases or [],
                    match_source=matched_name,
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

    if include_unresolved:
        unresolved_rows = (await session.execute(
            text("""
                SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
                FROM images
                WHERE resolved_target_id IS NULL
                  AND raw_headers->>'OBJECT' IS NOT NULL
                  AND raw_headers->>'OBJECT' != ''
                  AND raw_headers->>'OBJECT' ILIKE :pattern
                GROUP BY raw_headers->>'OBJECT'
                ORDER BY cnt DESC
                LIMIT :lim
            """).bindparams(pattern=pattern, lim=limit)
        )).all()
        for obj_name, cnt in unresolved_rows:
            results.append(TargetSearchResultFuzzy(
                id=f"obj:{obj_name}",
                primary_name=obj_name,
                unresolved=True,
                image_count=cnt,
            ))

    return results


async def get_equipment(session: AsyncSession) -> EquipmentResponse:
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


async def get_object_types(session: AsyncSession) -> list[ObjectTypeCount]:
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
        category = categorize_object_type(raw_type)
        category_counts[category] += count

    return sorted(
        [ObjectTypeCount(object_type=cat, count=cnt) for cat, cnt in category_counts.items()],
        key=lambda x: x.count,
        reverse=True,
    )


async def export_target(target_id, sessions: str | None, session: AsyncSession) -> ExportResponse:
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(404, "Target not found")

    # Get settings for AstroBin filter IDs and bortle
    from app.models import UserSettings, SETTINGS_ROW_ID
    settings_row = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings_row.general if settings_row else {}
    astrobin_filter_ids = general.get("astrobin_filter_ids", {})
    bortle = general.get("astrobin_bortle")

    # Fetch LIGHT frames for this target
    q = (
        select(Image)
        .where(Image.resolved_target_id == target_id)
        .where(Image.image_type == "LIGHT")
        .where(Image.capture_date.is_not(None))
        .order_by(Image.capture_date)
    )
    images = (await session.execute(q)).scalars().all()

    # Filter by selected sessions
    selected_dates = None
    if sessions:
        selected_dates = set(sessions.split(","))

    # Group by (date, filter, exposure_time)
    import statistics as stats_mod
    groups: dict[tuple[str, str, float], list] = defaultdict(list)
    equip_set: set[tuple] = set()

    filter_aliases, _, _ = await load_alias_maps(session)

    for img in images:
        date_key = str(img.session_date) if img.session_date else "unknown"
        if selected_dates and date_key not in selected_dates:
            continue
        filter_name = img.filter_used or "Unknown"
        exp = img.exposure_time or 0
        groups[(date_key, filter_name, exp)].append(img)
        equip_set.add((img.telescope, img.camera))

    rows = []
    all_dates = set()
    total_seconds = 0.0

    for (date_key, filter_name, exposure), imgs in sorted(groups.items()):
        all_dates.add(date_key)
        frame_count = len(imgs)
        integration = sum(i.exposure_time or 0 for i in imgs)
        total_seconds += integration

        gains = [i.camera_gain for i in imgs if i.camera_gain is not None]
        temps = [i.sensor_temp for i in imgs if i.sensor_temp is not None]
        fwhms = [i.fwhm for i in imgs if i.fwhm is not None]
        sqms = [i.sky_quality for i in imgs if i.sky_quality is not None]
        amb_temps = [i.ambient_temp for i in imgs if i.ambient_temp is not None]

        # Normalize filter name for AstroBin ID lookup
        canonical_filter = normalize_filter(filter_name, filter_aliases)
        ab_id = astrobin_filter_ids.get(canonical_filter) or astrobin_filter_ids.get(filter_name)

        rows.append(ExportFilterRow(
            date=date_key,
            filter_name=filter_name,
            astrobin_filter_id=ab_id,
            frames=frame_count,
            exposure=round(exposure, 4),
            total_seconds=round(integration, 1),
            gain=max(set(gains), key=gains.count) if gains else None,  # mode
            sensor_temp=round(stats_mod.median(temps)) if temps else None,
            fwhm=round(stats_mod.median(fwhms), 2) if fwhms else None,
            sky_quality=round(stats_mod.median(sqms), 2) if sqms else None,
            ambient_temp=round(stats_mod.median(amb_temps), 2) if amb_temps else None,
        ))

    # Calibration frame counts
    camera_names = {e[1] for e in equip_set if e[1]}

    dark_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "DARK")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    dark_count = (await session.execute(dark_q)).scalar() or 0

    flat_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "FLAT")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    flat_count = (await session.execute(flat_q)).scalar() or 0

    bias_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "BIAS")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    bias_count = (await session.execute(bias_q)).scalar() or 0

    return ExportResponse(
        target_name=target.primary_name,
        catalog_id=target.catalog_id,
        equipment=[ExportEquipment(telescope=t, camera=c) for t, c in equip_set],
        dates=sorted(all_dates),
        rows=rows,
        calibration=ExportCalibration(darks=dark_count, flats=flat_count, bias=bias_count),
        total_integration_seconds=total_seconds,
        bortle=bortle,
    )


async def get_target_detail(target_id: str, session: AsyncSession) -> TargetDetailResponse:
    """Return target identity with cumulative stats and session overviews."""
    # Column projection: only fetch the fields used for aggregation and
    # response construction.  Excludes heavy columns like file_path,
    # file_size, and the many weather/ADU/focuser columns not needed here.
    _detail_cols = (
        Image.session_date,
        Image.capture_date,
        Image.exposure_time,
        Image.median_hfr,
        Image.eccentricity,
        Image.fwhm,
        Image.guiding_rms_arcsec,
        Image.detected_stars,
        Image.camera,
        Image.telescope,
        Image.filter_used,
        Image.raw_headers,
        Image.rotator_position,
    )

    if target_id == "obj:__uncategorized__":
        target_name = "Uncategorized"
        target_obj = None
        # Images with no resolved target AND no OBJECT header
        query = (
            select(*_detail_cols)
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
            select(*_detail_cols)
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
            select(*_detail_cols)
            .where(
                Image.resolved_target_id == tid,
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )

    result = await session.execute(query)
    images = result.all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found for this target")

    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # Fetch session note dates for has_notes flag
    note_dates: set = set()
    if target_obj:
        note_dates_q = select(SessionNote.session_date).where(SessionNote.target_id == target_obj.id)
        note_dates = {r[0] for r in (await session.execute(note_dates_q)).all()}

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
        date_key = str(img.session_date) if img.session_date else "unknown"
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

    # Fetch session-level custom values for session header display
    from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
    session_custom_map: dict[str, dict[str, str]] = {}  # date_key -> {slug: value}
    if target_obj:
        cv_q = (
            select(CustomColumnValue.session_date, CustomColumn.slug, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumnValue.target_id == target_obj.id,
                CustomColumn.applies_to == AppliesTo.session,
                CustomColumnValue.session_date.isnot(None),
            )
        )
        for sd, slug, val in (await session.execute(cv_q)).all():
            dk = str(sd)
            if dk not in session_custom_map:
                session_custom_map[dk] = {}
            session_custom_map[dk][slug] = val

    session_overviews = []
    for date_key in sorted(sessions_map.keys(), reverse=True):
        sess_images = sessions_map[date_key]
        # Count distinct rigs for this session
        rig_set = set()
        for img in sess_images:
            tel = normalize_equipment(img.telescope, tel_map)
            cam = normalize_equipment(img.camera, cam_map)
            rig_set.add((tel, cam))
        sess_rig_count = len(rig_set)
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

        # Per-session coordinates from plate-solved headers
        sess_ra_vals = []
        sess_dec_vals = []
        sess_rotator = None
        for img in sess_images:
            hdrs = img.raw_headers or {}
            try:
                ra_val = float(hdrs.get("RA", ""))
                dec_val = float(hdrs.get("DEC", ""))
                sess_ra_vals.append(ra_val)
                sess_dec_vals.append(dec_val)
            except (ValueError, TypeError):
                pass
            if img.rotator_position is not None:
                sess_rotator = img.rotator_position

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
            has_notes=date_type.fromisoformat(date_key) in note_dates if date_key != "unknown" else False,
            rig_count=sess_rig_count,
            custom_values=session_custom_map.get(date_key),
            ra=statistics.median(sess_ra_vals) if sess_ra_vals else None,
            dec=statistics.median(sess_dec_vals) if sess_dec_vals else None,
            position_angle=sess_rotator,
        ))

    sorted_dates = sorted(sessions_map.keys())

    # Fallback RA/Dec from FITS headers for obj: targets
    fallback_ra: float | None = None
    fallback_dec: float | None = None
    if not target_obj and images:
        for img in images:
            hdrs = img.raw_headers or {}
            ra_str = hdrs.get("RA") or hdrs.get("OBJCTRA")
            dec_str = hdrs.get("DEC") or hdrs.get("OBJCTDEC")
            if ra_str and dec_str:
                try:
                    fallback_ra = float(ra_str)
                    fallback_dec = float(dec_str)
                except (ValueError, TypeError):
                    fallback_ra = parse_sexa_ra(str(ra_str))
                    fallback_dec = parse_sexa_dec(str(dec_str))
                if fallback_ra is not None and fallback_dec is not None:
                    break

    # Fallback position angle from most recent image's rotator position
    fallback_pa: float | None = None
    effective_pa = target_obj.position_angle if target_obj else None
    if effective_pa is None and images:
        for img in reversed(images):
            if img.rotator_position is not None:
                fallback_pa = img.rotator_position
                break

    # Fetch catalog memberships
    catalog_memberships = []
    if target_obj:
        memberships_result = await session.execute(
            select(TargetCatalogMembership).where(TargetCatalogMembership.target_id == target_obj.id)
        )
        catalog_memberships = [
            {"catalog_name": m.catalog_name, "catalog_number": m.catalog_number, "metadata": m.metadata_}
            for m in memberships_result.scalars().all()
        ]

    return TargetDetailResponse(
        target_id=target_id,
        primary_name=target_name,
        aliases=target_obj.aliases if target_obj else [],
        object_type=target_obj.object_type if target_obj else None,
        object_category=(
            categorize_object_type(target_obj.object_type)
            if target_obj and target_obj.object_type
            else None
        ),
        ra=target_obj.ra if target_obj else fallback_ra,
        dec=target_obj.dec if target_obj else fallback_dec,
        position_angle=effective_pa if effective_pa is not None else fallback_pa,
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
        notes=target_obj.notes if target_obj else None,
        sac_description=target_obj.sac_description if target_obj else None,
        sac_notes=target_obj.sac_notes if target_obj else None,
        reference_thumbnail_path=target_obj.reference_thumbnail_path if target_obj else None,
        distance_pc=target_obj.distance_pc if target_obj else None,
        hubble_t_type=target_obj.hubble_t_type if target_obj else None,
        inclination=target_obj.inclination if target_obj else None,
        catalog_memberships=catalog_memberships,
        name_locked=target_obj.name_locked if target_obj else False,
        user_defined=target_obj.user_defined if target_obj else False,
    )


async def list_targets_aggregated(
    *,
    session: AsyncSession,
    search: str | None,
    target_id: str | None,
    camera: str | None,
    telescope: str | None,
    filters: str | None,
    date_from: str | None,
    date_to: str | None,
    fits_key: list[str] | None,
    fits_op: list[str] | None,
    fits_val: list[str] | None,
    object_type: str | None,
    hfr_min: float | None,
    hfr_max: float | None,
    fwhm_min: float | None,
    fwhm_max: float | None,
    eccentricity_min: float | None,
    eccentricity_max: float | None,
    stars_min: int | None,
    stars_max: int | None,
    guiding_rms_min: float | None,
    guiding_rms_max: float | None,
    adu_mean_min: float | None,
    adu_mean_max: float | None,
    focuser_temp_min: float | None,
    focuser_temp_max: float | None,
    ambient_temp_min: float | None,
    ambient_temp_max: float | None,
    humidity_min: float | None,
    humidity_max: float | None,
    airmass_min: float | None,
    airmass_max: float | None,
    catalog: str | None,
    sort_by: str,
    sort_dir: str,
    page: int,
    page_size: int,
    include_custom: bool,
    custom_filters: str | None,
) -> TargetAggregationResponse:
    """Return targets with aggregated session data, filtered by query params."""
    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # ---------------------------------------------------------------
    # Parse custom column filters
    # ---------------------------------------------------------------
    cc_filter_entries: list[dict] = []
    cc_columns_by_slug: dict[str, dict] = {}
    if custom_filters:
        import json as _json
        try:
            cc_filter_entries = _json.loads(custom_filters)
        except (ValueError, TypeError):
            cc_filter_entries = []

        if cc_filter_entries:
            from app.models.custom_column import CustomColumn
            cc_q = select(CustomColumn.id, CustomColumn.slug, CustomColumn.column_type, CustomColumn.applies_to)
            cc_rows = (await session.execute(cc_q)).all()
            cc_columns_by_slug = {
                r.slug: {"id": str(r.id), "column_type": r.column_type, "applies_to": r.applies_to}
                for r in cc_rows
            }

    # ---------------------------------------------------------------
    # Phases 1-3: Raw SQL for grouped + aggregates + pagination
    # ---------------------------------------------------------------
    where_parts: list[str] = [
        "i.image_type = 'LIGHT'",
        "(i.resolved_target_id IS NULL OR t.merged_into_id IS NULL)",
    ]
    params: dict = {}

    # Generate EXISTS subqueries for custom column filters
    has_cc_session_filters = False
    for idx, entry in enumerate(cc_filter_entries):
        slug = entry.get("slug", "")
        value = entry.get("value", "")
        col_meta = cc_columns_by_slug.get(slug)
        if not col_meta or not value:
            continue

        col_id_param = f"cc_col_{idx}"
        val_param = f"cc_val_{idx}"
        params[col_id_param] = col_meta["id"]

        applies_to = col_meta["applies_to"]
        col_type = col_meta["column_type"]

        if col_type == "text":
            escaped_val = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params[val_param] = f"%{escaped_val}%"
            match_expr = f"cv.value ILIKE :{val_param}"
        else:
            params[val_param] = value
            match_expr = f"cv.value = :{val_param}"

        if applies_to == "target":
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND {match_expr}
            )""")
        elif applies_to == "session":
            has_cc_session_filters = True
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND cv.session_date IS NOT NULL AND {match_expr}
            )""")
        elif applies_to == "rig":
            has_cc_session_filters = True
            where_parts.append(f"""EXISTS (
                SELECT 1 FROM custom_column_values cv
                WHERE cv.target_id = t.id AND cv.column_id = CAST(:{col_id_param} AS uuid)
                AND cv.rig_label IS NOT NULL AND {match_expr}
            )""")

    if camera:
        cam_variants = expand_canonical(camera, cam_map)
        where_parts.append("i.camera = ANY(:cam_variants)")
        params["cam_variants"] = cam_variants
    if telescope:
        tel_variants = expand_canonical(telescope, tel_map)
        where_parts.append("i.telescope = ANY(:tel_variants)")
        params["tel_variants"] = tel_variants
    if filters:
        filter_list = [f.strip() for f in filters.split(",")]
        all_filter_variants: list[str] = []
        for f in filter_list:
            all_filter_variants.extend(expand_canonical(f, filter_map))
        where_parts.append("i.filter_used = ANY(:filter_variants)")
        params["filter_variants"] = all_filter_variants
    if date_from:
        where_parts.append("i.session_date >= :date_from")
        params["date_from"] = datetime.strptime(date_from, "%Y-%m-%d").date()
    if date_to:
        where_parts.append("i.session_date <= :date_to")
        params["date_to"] = datetime.strptime(date_to, "%Y-%m-%d").date()
    if target_id:
        where_parts.append("i.resolved_target_id = CAST(:exact_target_id AS uuid)")
        params["exact_target_id"] = target_id
    elif search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        where_parts.append("""(
            t.primary_name ILIKE :search_pat
            OR t.catalog_id ILIKE :search_pat
            OR t.common_name ILIKE :search_pat
            OR array_to_string(t.aliases, ' ') ILIKE :search_pat
            OR similarity(concat(coalesce(t.catalog_id,''),' ',coalesce(t.common_name,''),' ',array_to_string(t.aliases,' ')), :search_raw) > 0.3
            OR i.raw_headers->>'OBJECT' ILIKE :search_pat
        )""")
        params["search_pat"] = pattern
        params["search_raw"] = search

    if object_type:
        type_list = [tp.strip() for tp in object_type.split(",")]
        has_unresolved = "Unresolved" in type_list
        categories = [tp for tp in type_list if tp != "Unresolved"]

        if categories:
            matching_codes: set[str] = set()
            for code, cat in SIMBAD_CATEGORY_MAP.items():
                if cat in categories:
                    matching_codes.add(code)

            type_conds: list[str] = []
            for idx, code in enumerate(matching_codes):
                pname = f"simbad_{idx}"
                type_conds.append(f"(t.object_type LIKE :{pname}_like OR t.object_type = :{pname}_eq)")
                params[f"{pname}_like"] = f"{code},%"
                params[f"{pname}_eq"] = code

            if "Other" in categories:
                mapped = list(SIMBAD_CATEGORY_MAP.keys())
                oparts: list[str] = []
                for idx2, code in enumerate(mapped):
                    pn = f"other_{idx2}"
                    oparts.append(f"(t.object_type NOT LIKE :{pn}_like AND t.object_type != :{pn}_eq)")
                    params[f"{pn}_like"] = f"{code},%"
                    params[f"{pn}_eq"] = code
                type_conds.append(f"({' AND '.join(oparts)})")

            if has_unresolved:
                type_conds.append("i.resolved_target_id IS NULL")
            where_parts.append(f"({' OR '.join(type_conds)})")
        elif has_unresolved:
            where_parts.append("i.resolved_target_id IS NULL")

    if catalog:
        where_parts.append("""EXISTS (
            SELECT 1 FROM target_catalog_memberships tcm
            WHERE tcm.target_id = t.id AND tcm.catalog_name = :catalog_name
        )""")
        params["catalog_name"] = catalog

    if fits_key and fits_op and fits_val:
        for idx, (key, op_str, val) in enumerate(zip(fits_key, fits_op, fits_val)):
            if not re.match(r'^[A-Za-z0-9_-]{1,20}$', key):
                continue
            pn = f"fits_{idx}"
            field = f"i.raw_headers->>'{key}'"
            if op_str == "eq":
                where_parts.append(f"{field} = :{pn}")
                params[pn] = val
            elif op_str == "neq":
                where_parts.append(f"{field} != :{pn}")
                params[pn] = val
            elif op_str in ("gt", "lt", "gte", "lte"):
                try:
                    float(val)
                except ValueError:
                    continue
                op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<="}
                where_parts.append(f"CAST({field} AS FLOAT) {op_map[op_str]} :{pn}")
                params[pn] = float(val)
            elif op_str == "contains":
                esc = val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where_parts.append(f"{field} ILIKE :{pn}")
                params[pn] = f"%{esc}%"

    where_sql = " AND ".join(where_parts)

    # HAVING clauses for metric range filters
    having_parts: list[str] = []
    metric_cols = {
        "hfr": "median_hfr", "fwhm": "fwhm", "eccentricity": "eccentricity",
        "stars": "CAST(detected_stars AS FLOAT)", "guiding_rms": "guiding_rms_arcsec",
        "adu_mean": "adu_mean", "focuser_temp": "focuser_temp",
        "ambient_temp": "ambient_temp", "humidity": "humidity", "airmass": "airmass",
    }
    metric_ranges = {
        "hfr": (hfr_min, hfr_max), "fwhm": (fwhm_min, fwhm_max),
        "eccentricity": (eccentricity_min, eccentricity_max),
        "stars": (stars_min, stars_max), "guiding_rms": (guiding_rms_min, guiding_rms_max),
        "adu_mean": (adu_mean_min, adu_mean_max), "focuser_temp": (focuser_temp_min, focuser_temp_max),
        "ambient_temp": (ambient_temp_min, ambient_temp_max),
        "humidity": (humidity_min, humidity_max), "airmass": (airmass_min, airmass_max),
    }
    for mname, (m_min, m_max) in metric_ranges.items():
        col = metric_cols[mname]
        if m_min is not None:
            having_parts.append(f"avg(i.{col}) >= :{mname}_min")
            params[f"{mname}_min"] = m_min
        if m_max is not None:
            having_parts.append(f"avg(i.{col}) <= :{mname}_max")
            params[f"{mname}_max"] = m_max

    has_metric_filters = bool(having_parts)
    having_sql = f"HAVING {' AND '.join(having_parts)}" if having_parts else ""

    # An empty-string OBJECT header is treated the same as a missing one
    # (nullif -> NULL -> __uncategorized__). This MUST match the detail-phase
    # key derivation (detail_target_key below) so a frame lands in the same
    # group in both phases.
    gk = "coalesce(CAST(i.resolved_target_id AS VARCHAR), concat('obj:', coalesce(nullif(i.raw_headers->>'OBJECT', ''), '__uncategorized__')))"

    # NOTE (AUD-032, axis 1): the resulting `agg.target_count` below counts
    # every group in `gk`, including unresolved-OBJECT / uncategorized "obj:"
    # buckets, alongside resolved targets. This is intentionally a different,
    # broader count than the Statistics overview's `target_count`
    # (`stats._query_overview`, which counts only `count(distinct
    # resolved_target_id)` and so excludes unresolved frames entirely). Both
    # are kept as distinct metrics -- this one drives the Dashboard sidebar's
    # "Targets" figure (a list-entry count including unresolved groups), the
    # Statistics figure is labeled "Resolved targets". Do not silently unify
    # them without updating both labels.
    combined_sql = text(f"""
    WITH grouped AS (
        SELECT {gk} AS target_key,
               coalesce(min(t.primary_name), min(nullif(i.raw_headers->>'OBJECT', '')), 'Uncategorized') AS primary_name,
               coalesce(bool_or(t.user_defined), false) AS user_defined,
               sum(coalesce(i.exposure_time, 0)) AS total_integration,
               count(i.id) AS total_frames,
               count(distinct coalesce(CAST(i.session_date AS VARCHAR), 'unknown')) AS session_count,
               max(i.session_date) AS last_session_date,
               min(i.session_date) AS oldest_date,
               max(i.session_date) AS newest_date
        FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id
        WHERE {where_sql}
        GROUP BY {gk}
        {having_sql}
    ),
    agg AS (
        SELECT count(*) AS target_count, sum(total_integration) AS total_integration,
               sum(total_frames) AS total_frames,
               min(oldest_date) AS oldest, max(newest_date) AS newest FROM grouped
    ),
    page AS (
        SELECT * FROM grouped ORDER BY {sort_clause(sort_by, sort_dir)}
        LIMIT :page_size OFFSET :page_offset
    )
    SELECT (SELECT target_count FROM agg) AS agg_target_count,
           (SELECT total_integration FROM agg) AS agg_total_integration,
           (SELECT total_frames FROM agg) AS agg_total_frames,
           (SELECT oldest FROM agg) AS agg_oldest,
           (SELECT newest FROM agg) AS agg_newest,
           p.target_key, p.primary_name, p.user_defined, p.total_integration, p.total_frames, p.session_count
    FROM page p
    """)
    params["page_size"] = page_size
    params["page_offset"] = (page - 1) * page_size

    combined_result = await session.execute(combined_sql, params)
    combined_rows = combined_result.all()

    if not combined_rows:
        return TargetAggregationResponse(
            targets=[],
            aggregates=AggregateStats(
                total_integration_seconds=0, target_count=0, total_frames=0, disk_usage_bytes=0,
            ),
            total_count=0, page=page, page_size=page_size,
        )

    first = combined_rows[0]
    total_count = first.agg_target_count or 0
    aggregates = AggregateStats(
        total_integration_seconds=float(first.agg_total_integration or 0),
        target_count=total_count,
        total_frames=int(first.agg_total_frames or 0),
        disk_usage_bytes=0,
        oldest_date=str(first.agg_oldest) if first.agg_oldest else None,
        newest_date=str(first.agg_newest) if first.agg_newest else None,
    )

    page_keys: list[str] = []
    page_basics: dict[str, dict] = {}
    for row in combined_rows:
        tk = row.target_key
        page_keys.append(tk)
        page_basics[tk] = {
            "target_key": tk,
            "primary_name": row.primary_name,
            "user_defined": bool(row.user_defined),
            "total_integration": float(row.total_integration),
            "total_frames": int(row.total_frames),
            "session_count": int(row.session_count),
        }

    # ---------------------------------------------------------------
    # Phase 4: Detail query for current page's targets (raw SQL)
    # ---------------------------------------------------------------
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
                page_uuids.append(str(uuid.UUID(tk)))
            except ValueError:
                pass

    key_conds = []
    if page_uuids:
        key_conds.append("i.resolved_target_id = ANY(CAST(:page_uuids AS uuid[]))")
        params["page_uuids"] = page_uuids
    if page_obj_names:
        key_conds.append("(i.resolved_target_id IS NULL AND i.raw_headers->>'OBJECT' = ANY(:page_obj_names))")
        params["page_obj_names"] = page_obj_names
    if has_uncategorized:
        key_conds.append("(i.resolved_target_id IS NULL AND (NOT i.raw_headers ? 'OBJECT' OR i.raw_headers->>'OBJECT' = '' OR i.raw_headers->>'OBJECT' IS NULL))")

    key_filter = f"({' OR '.join(key_conds)})" if key_conds else "FALSE"

    # SQL-side target key, mirroring the Python derivation that previously ran
    # per frame: resolved UUID -> its text; otherwise obj:<OBJECT>, where an
    # empty/missing OBJECT collapses to obj:__uncategorized__.
    detail_target_key = (
        "CASE WHEN i.resolved_target_id IS NOT NULL "
        "THEN CAST(i.resolved_target_id AS VARCHAR) "
        "ELSE concat('obj:', coalesce(nullif(i.raw_headers->>'OBJECT', ''), '__uncategorized__')) "
        "END"
    )
    # Per-frame OBJECT header, NULL when empty/missing (mirrors `if row.fits_object`).
    detail_fits_object = "nullif(i.raw_headers->>'OBJECT', '')"

    # Two-level aggregation: collapse frames to one row per target_key, carrying
    # raw (un-normalized) filter sums, distinct raw equipment, distinct OBJECT
    # aliases, and a per-session breakdown as JSON. Alias normalization/merging
    # is applied in Python below over these small per-target sets.
    detail_sql = text(f"""
        WITH frames AS (
            SELECT {detail_target_key} AS target_key,
                   {detail_fits_object} AS fits_object,
                   coalesce(i.exposure_time, 0) AS exp,
                   i.filter_used,
                   i.camera,
                   i.telescope,
                   i.median_hfr,
                   i.eccentricity,
                   CASE WHEN i.session_date IS NULL THEN 'unknown'
                        ELSE CAST(i.session_date AS VARCHAR) END AS session_key
            FROM images i LEFT JOIN targets t ON i.resolved_target_id = t.id
            WHERE {where_sql} AND {key_filter}
        ),
        per_filter AS (
            SELECT target_key, filter_used, sum(exp) AS filter_exp
            FROM frames
            WHERE filter_used IS NOT NULL
            GROUP BY target_key, filter_used
        ),
        per_session AS (
            SELECT target_key, session_key,
                   sum(exp) AS session_exp,
                   count(*) AS frame_count,
                   array_agg(DISTINCT filter_used) FILTER (WHERE filter_used IS NOT NULL) AS session_filters,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY median_hfr)
                       FILTER (WHERE median_hfr IS NOT NULL) AS session_median_hfr,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY eccentricity)
                       FILTER (WHERE eccentricity IS NOT NULL) AS session_median_ecc
            FROM frames
            GROUP BY target_key, session_key
        ),
        per_target AS (
            SELECT target_key,
                   array_agg(DISTINCT camera) FILTER (WHERE camera IS NOT NULL) AS cameras,
                   array_agg(DISTINCT telescope) FILTER (WHERE telescope IS NOT NULL) AS telescopes,
                   array_agg(DISTINCT fits_object) FILTER (WHERE fits_object IS NOT NULL) AS fits_objects
            FROM frames
            GROUP BY target_key
        ),
        -- Roll per_filter up to one row per target ONCE (set-based), then
        -- LEFT JOIN onto per_target. Avoids a correlated scalar subquery that
        -- would rescan the frames CTE once per target.
        filter_agg AS (
            SELECT target_key,
                   jsonb_object_agg(filter_used, filter_exp) AS filter_raw_dist
            FROM per_filter
            GROUP BY target_key
        ),
        -- Roll per_session up to one row per target ONCE (set-based).
        session_agg AS (
            SELECT target_key,
                   jsonb_agg(jsonb_build_object(
                       'session_key', session_key,
                       'session_exp', session_exp,
                       'frame_count', frame_count,
                       'filters', coalesce(session_filters, ARRAY[]::varchar[]),
                       'median_hfr', session_median_hfr,
                       'median_eccentricity', session_median_ecc)) AS sessions
            FROM per_session
            GROUP BY target_key
        )
        SELECT pt.target_key,
               pt.cameras,
               pt.telescopes,
               pt.fits_objects,
               fa.filter_raw_dist,
               sa.sessions
        FROM per_target pt
        LEFT JOIN filter_agg fa USING (target_key)
        LEFT JOIN session_agg sa USING (target_key)
    """)
    detail_result = await session.execute(detail_sql, params)
    detail_rows = detail_result.all()

    # Build per-target detail maps. One row per target_key now; alias
    # normalization and merging happen here over the small per-target sets,
    # preserving the exact semantics of the former per-frame loop.
    filter_dist: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    equipment_map: dict[str, set] = defaultdict(set)
    sessions_detail: dict[str, dict[str, dict]] = defaultdict(dict)
    aliases_map: dict[str, set] = defaultdict(set)

    for row in detail_rows:
        tk = row.target_key
        if tk not in page_basics:
            continue

        # Filter distribution: normalize each raw filter and SUM exposures
        # that collapse to the same canonical name.
        for raw_filter, exp_sum in (row.filter_raw_dist or {}).items():
            f = normalize_filter(raw_filter, filter_map)
            if f:
                filter_dist[tk][f] += float(exp_sum)

        # Equipment: normalize cameras + telescopes, dedupe into one set.
        for raw_cam in (row.cameras or []):
            cam = normalize_equipment(raw_cam, cam_map)
            if cam:
                equipment_map[tk].add(cam)
        for raw_tel in (row.telescopes or []):
            tel = normalize_equipment(raw_tel, tel_map)
            if tel:
                equipment_map[tk].add(tel)

        # Aliases: distinct non-empty OBJECT headers.
        for obj_name in (row.fits_objects or []):
            if obj_name:
                aliases_map[tk].add(obj_name)

        # Sessions: normalize each session's filters, dedupe, cast numerics.
        for sess in (row.sessions or []):
            date_key = sess["session_key"]
            if date_key not in sessions_detail[tk]:
                sessions_detail[tk][date_key] = {
                    "session_date": date_key,
                    "integration_seconds": 0,
                    "frame_count": 0,
                    "filters_set": set(),
                    "median_hfr": None,
                    "median_eccentricity": None,
                }
            s = sessions_detail[tk][date_key]
            s["integration_seconds"] += float(sess["session_exp"])
            s["frame_count"] += int(sess["frame_count"])
            # Per-session median sharpness/roundness, computed SQL-side over the
            # session's frames (nulls ignored). Each (target_key, session_key)
            # appears once per detail row, so a direct set is correct.
            mh = sess.get("median_hfr")
            if mh is not None:
                s["median_hfr"] = float(mh)
            me = sess.get("median_eccentricity")
            if me is not None:
                s["median_eccentricity"] = float(me)
            for raw_filter in (sess.get("filters") or []):
                f = normalize_filter(raw_filter, filter_map)
                if f:
                    s["filters_set"].add(f)

    # ---------------------------------------------------------------
    # Phase 4b: Mosaic membership lookup
    # ---------------------------------------------------------------
    from app.models.mosaic_panel import MosaicPanel
    from app.models.mosaic import Mosaic
    page_target_uuids = [uuid.UUID(tk) for tk in page_keys if not tk.startswith("obj:")]
    panel_q = (
        select(MosaicPanel.target_id, Mosaic.id, Mosaic.name)
        .join(Mosaic)
        .where(MosaicPanel.target_id.in_(page_target_uuids))
    )
    panel_rows = (await session.execute(panel_q)).all()
    mosaic_map = {str(r[0]): (str(r[1]), r[2]) for r in panel_rows}

    # ---------------------------------------------------------------
    # Phase 4c: Custom column values (target-level)
    # ---------------------------------------------------------------
    custom_values_map: dict[str, dict[str, str]] = {}
    if include_custom:
        from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
        cv_q = (
            select(CustomColumnValue.target_id, CustomColumn.slug, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumn.applies_to == AppliesTo.target,
                CustomColumnValue.target_id.in_(page_target_uuids),
            )
        )
        cv_rows = (await session.execute(cv_q)).all()
        for tid, slug, val in cv_rows:
            tid_str = str(tid)
            if tid_str not in custom_values_map:
                custom_values_map[tid_str] = {}
            custom_values_map[tid_str][slug] = val

    # ---------------------------------------------------------------
    # Phase 4d: Batch pre-fetch custom column session/rig values
    # ---------------------------------------------------------------
    _cc_batch_values: dict[str, dict[str, list[tuple[str, str]]]] = {}
    if has_cc_session_filters:
        from app.models.custom_column import CustomColumnValue
        import uuid as _uuid
        page_uuids = [_uuid.UUID(tk) for tk in page_keys if not tk.startswith("obj:")]
        col_ids = [
            _uuid.UUID(col_meta["id"])
            for col_meta in cc_columns_by_slug.values()
            if col_meta["applies_to"] in ("session", "rig")
        ]
        if page_uuids and col_ids:
            _batch_q = select(
                cast(CustomColumnValue.target_id, String),
                cast(CustomColumnValue.column_id, String),
                cast(CustomColumnValue.session_date, String),
                CustomColumnValue.value,
            ).where(
                CustomColumnValue.target_id.in_(page_uuids),
                CustomColumnValue.column_id.in_(col_ids),
                CustomColumnValue.session_date.isnot(None),
            )
            for row in (await session.execute(_batch_q)).all():
                tid_str, cid_str, sd_str, val = row
                _cc_batch_values.setdefault(tid_str, {}).setdefault(cid_str, []).append((sd_str, val))

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

        # Count sessions matching custom column session/rig filters
        if has_cc_session_filters and not tk.startswith("obj:"):
            cc_matched_dates: set[str] | None = None
            for idx, entry in enumerate(cc_filter_entries):
                slug = entry.get("slug", "")
                value = entry.get("value", "")
                col_meta = cc_columns_by_slug.get(slug)
                if not col_meta or not value:
                    continue
                if col_meta["applies_to"] not in ("session", "rig"):
                    continue

                col_id = col_meta["id"]
                col_type = col_meta["column_type"]

                # Look up pre-fetched values for this target + column
                target_key = basics["target_key"]
                cv_entries = _cc_batch_values.get(target_key, {}).get(col_id, [])
                matching_dates: set[str] = set()
                for sd, val in cv_entries:
                    if col_type == "text":
                        if value.lower() in (val or "").lower():
                            matching_dates.add(sd)
                    else:
                        if val == value:
                            matching_dates.add(sd)

                if cc_matched_dates is None:
                    cc_matched_dates = matching_dates
                else:
                    cc_matched_dates &= matching_dates

            if cc_matched_dates is not None:
                session_dates_for_target = set(sessions_detail.get(tk, {}).keys())
                if matched_session_count is not None:
                    # Intersect with metric-filtered sessions
                    metric_dates = {s["session_date"] for s in sessions_list}
                    cc_matched_dates &= metric_dates
                    matched_session_count = len(cc_matched_dates)
                else:
                    matched_session_count = len(cc_matched_dates & session_dates_for_target)

        sessions = [
            SessionSummary(
                session_date=s["session_date"],
                integration_seconds=s["integration_seconds"],
                frame_count=s["frame_count"],
                filters_used=sorted(s["filters_set"]),
                median_hfr=s["median_hfr"],
                median_eccentricity=s["median_eccentricity"],
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
            mosaic_id=mosaic_map.get(basics["target_key"], (None, None))[0],
            mosaic_name=mosaic_map.get(basics["target_key"], (None, None))[1],
            custom_values=custom_values_map.get(basics["target_key"]) if include_custom else None,
            user_defined=basics["user_defined"],
        ))

    return TargetAggregationResponse(
        targets=target_list,
        aggregates=aggregates,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )


async def get_session_detail(target_id: str, date: str, session: AsyncSession) -> SessionDetailResponse:
    """Return detailed session data for a target on a specific date.

    The date string is interpreted as a UTC calendar day to match the
    listing endpoint, which groups by `session_date`.
    """
    session_date_val = date_type.fromisoformat(date)
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
                Image.session_date == session_date_val,
            )
            .order_by(Image.capture_date)
        )
        avg_hfr_q = select(func.avg(Image.median_hfr)).where(
            Image.resolved_target_id.is_(None),
            _no_object,
            Image.median_hfr.isnot(None),
        )
    elif target_id.startswith("obj:"):
        object_name = target_id[4:]
        target_name = object_name
        target_obj = None
        query = (
            select(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == object_name,
                Image.session_date == session_date_val,
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )
        avg_hfr_q = select(func.avg(Image.median_hfr)).where(
            Image.raw_headers["OBJECT"].astext == object_name,
            Image.image_type == "LIGHT",
            Image.median_hfr.isnot(None),
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
                Image.session_date == session_date_val,
                Image.image_type == "LIGHT",
            )
            .order_by(Image.capture_date)
        )
        avg_hfr_q = select(func.avg(Image.median_hfr)).where(
            Image.resolved_target_id == tid,
            Image.image_type == "LIGHT",
            Image.median_hfr.isnot(None),
        )

    result = await session.execute(query)
    images = result.scalars().all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found for this session")

    target_avg_hfr = (await session.execute(avg_hfr_q)).scalar()

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

    filter_groups: dict[tuple[str, float | None], list] = defaultdict(list)
    for img in images:
        f = normalize_filter(img.filter_used, filter_map)
        if f:
            filter_groups[(f, img.exposure_time)].append(img)

    filter_details = []
    for (fname, exp), fimages in sorted(filter_groups.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
        f_hfr = [i.median_hfr for i in fimages if i.median_hfr is not None]
        f_ecc = [i.eccentricity for i in fimages if i.eccentricity is not None]
        f_exp = sum(i.exposure_time or 0 for i in fimages)
        filter_details.append(FilterDetail(
            filter_name=fname,
            frame_count=len(fimages),
            integration_seconds=f_exp,
            median_hfr=statistics.median(f_hfr) if f_hfr else None,
            median_eccentricity=statistics.median(f_ecc) if f_ecc else None,
            exposure_time=exp,
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
            image_id=str(img.id),
            file_path=img.file_path,
            thumbnail_url=f"/thumbnails/{img.thumbnail_path.split('/')[-1].split(chr(92))[-1]}" if img.thumbnail_path else None,
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
            rig=f"{normalize_equipment(img.telescope, tel_map) or 'Unknown'} / {normalize_equipment(img.camera, cam_map) or 'Unknown'}",
        ))

    rig_details = build_rig_details(images, filter_map, cam_map, tel_map)

    is_best_hfr = False
    if median_hfr is not None:
        # Query HFR data across all sessions for this target
        if target_id == "obj:__uncategorized__":
            all_hfr_q = select(Image.session_date, Image.median_hfr).where(
                Image.resolved_target_id.is_(None),
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
                Image.median_hfr.isnot(None),
            )
        elif target_id.startswith("obj:"):
            all_hfr_q = select(Image.session_date, Image.median_hfr).where(
                Image.raw_headers["OBJECT"].astext == target_id[4:],
                Image.image_type == "LIGHT",
                Image.median_hfr.isnot(None),
            )
        else:
            all_hfr_q = select(Image.session_date, Image.median_hfr).where(
                Image.resolved_target_id == tid,
                Image.image_type == "LIGHT",
                Image.median_hfr.isnot(None),
            )
        all_hfr_rows = (await session.execute(all_hfr_q)).all()
        all_session_dates: dict[str, list[float]] = defaultdict(list)
        for session_date_val, hfr_val in all_hfr_rows:
            if session_date_val:
                all_session_dates[str(session_date_val)].append(hfr_val)
        all_session_medians = [statistics.median(v) for v in all_session_dates.values() if v]
        if all_session_medians:
            is_best_hfr = median_hfr <= min(all_session_medians)

    insights = compute_insights(
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

    # Per-rig insights for multi-rig sessions
    if len(rig_details) > 1:
        for rd in rig_details:
            rig_hfr = [f.median_hfr for f in rd.frames if f.median_hfr is not None]
            rig_ecc = [f.eccentricity for f in rd.frames if f.eccentricity is not None]
            rig_median_hfr = statistics.median(rig_hfr) if rig_hfr else None
            rig_median_ecc = statistics.median(rig_ecc) if rig_ecc else None
            prefix = f"[{rd.rig_label}] "
            if rig_median_hfr is not None and target_avg_hfr is not None:
                if rig_median_hfr <= target_avg_hfr:
                    insights.append(SessionInsight(
                        level="good",
                        message=f"{prefix}Good HFR (median {rig_median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
                    ))
                elif rig_median_hfr > target_avg_hfr * 1.3:
                    insights.append(SessionInsight(
                        level="warning",
                        message=f"{prefix}Poor HFR (median {rig_median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
                    ))
            if rig_median_hfr is not None and len(rig_hfr) > 2:
                threshold = rig_median_hfr * 1.5
                outlier_count = sum(1 for v in rig_hfr if v > threshold)
                if outlier_count > 0:
                    insights.append(SessionInsight(
                        level="warning",
                        message=f"{prefix}{outlier_count} frame{'s' if outlier_count > 1 else ''} with HFR outlier{'s' if outlier_count > 1 else ''} (> {threshold:.1f})",
                    ))
            if rig_median_ecc is not None and len(rig_ecc) > 2:
                threshold = rig_median_ecc * 1.5
                outlier_count = sum(1 for v in rig_ecc if v > threshold)
                if outlier_count > 0:
                    insights.append(SessionInsight(
                        level="warning",
                        message=f"{prefix}{outlier_count} frame{'s' if outlier_count > 1 else ''} with eccentricity outlier{'s' if outlier_count > 1 else ''} (> {threshold:.2f})",
                    ))

    # Fetch session note
    session_note = None
    resolved_target_id = target_obj.id if target_obj else None
    if resolved_target_id:
        note_q = select(SessionNote.notes).where(
            SessionNote.target_id == resolved_target_id,
            SessionNote.session_date == date_type.fromisoformat(date),
        )
        session_note = (await session.execute(note_q)).scalar_one_or_none()

    # Fetch custom column values for this session (session + rig level)
    from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
    custom_values_list = None
    if resolved_target_id:
        cv_q = (
            select(CustomColumn.slug, CustomColumnValue.session_date,
                   CustomColumnValue.rig_label, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumnValue.target_id == resolved_target_id,
                CustomColumn.applies_to.in_([AppliesTo.session, AppliesTo.rig]),
                CustomColumnValue.session_date == date_type.fromisoformat(date),
            )
        )
        cv_rows = (await session.execute(cv_q)).all()
        if cv_rows:
            custom_values_list = [
                {
                    "column_slug": slug,
                    "session_date": str(sd) if sd else None,
                    "rig_label": rl,
                    "value": val,
                }
                for slug, sd, rl, val in cv_rows
            ]

    # --- Frame-quality baselines (MAD-based, computed on the fly) ---
    # Group keys use normalized telescope/camera/filter so they match the
    # frontend `groupKey(frame)` built from the same normalized values.
    def _baseline_frame(tel, cam, filt, hfr, fwhm_v, ecc, stars, adu_med, guide):
        return {
            "telescope": normalize_equipment(tel, tel_map),
            "camera": normalize_equipment(cam, cam_map),
            "filter_used": normalize_filter(filt, filter_map),
            "median_hfr": hfr,
            "fwhm": fwhm_v,
            "eccentricity": ecc,
            "detected_stars": stars,
            "adu_median": adu_med,
            "guiding_rms_arcsec": guide,
        }

    session_frame_dicts = [
        _baseline_frame(
            img.telescope, img.camera, img.filter_used,
            img.median_hfr, img.fwhm, img.eccentricity,
            img.detected_stars, img.adu_median, img.guiding_rms_arcsec,
        )
        for img in images
    ]
    session_baselines = frame_quality.group_baselines(session_frame_dicts)

    # Catalog-wide frames: every LIGHT frame across all targets and sessions,
    # grouped by telescope|camera|filter. This is the "This rig overall"
    # baseline. It is target-independent, which makes the per-frame
    # "This session / This rig overall" toggle meaningful even for
    # single-session targets. Select only the columns the baseline needs.
    metric_cols = (
        Image.telescope, Image.camera, Image.filter_used,
        Image.median_hfr, Image.fwhm, Image.eccentricity,
        Image.detected_stars, Image.adu_median, Image.guiding_rms_arcsec,
    )
    catalog_frames_q = select(*metric_cols).where(Image.image_type == "LIGHT")
    catalog_frame_rows = (await session.execute(catalog_frames_q)).all()
    catalog_frame_dicts = [_baseline_frame(*row) for row in catalog_frame_rows]
    rig_baselines = frame_quality.group_baselines(catalog_frame_dicts)

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
        notes=session_note,
        rigs=rig_details,
        custom_values=custom_values_list,
        session_baselines=session_baselines,
        rig_baselines=rig_baselines,
    )
