"""Shared target-aggregation helpers: RA/Dec parsing, rig grouping, SIMBAD
object-type categorization, sort clauses, and session insight computation.

Pure extraction from app/services/target_aggregation.py; behavior preserved
exactly. No internal imports of sibling target_* modules, so this file can be
imported cycle-free by both target_listing.py and target_detail.py.
"""

import statistics
from collections import defaultdict
from datetime import datetime

from app.config import settings
from app.services import frame_quality
from app.services.normalization import normalize_filter, normalize_equipment
from app.services.wbpp_export import fits_relative_path
from app.schemas.target import FilterDetail, FrameRecord, RigDetail, SessionInsight


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
                source_relative=fits_relative_path(img.file_path, settings.fits_data_path),
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
        "equipment": "equipment_sort_key",
    }
    col = col_map.get(sort_by, "total_integration")
    direction = "ASC" if sort_dir == "asc" else "DESC"
    nulls = "NULLS LAST" if direction == "DESC" else "NULLS FIRST"
    if sort_by == "equipment":
        # Uncategorized targets always sort last, regardless of direction,
        # matching the previous client-side sort's behavior.
        return f"(target_key = 'obj:__uncategorized__') ASC, {col} {direction} {nulls}"
    return f"{col} {direction} {nulls}"


# A "the whole night was bad" claim compares one session median against the rig's
# history. The dispersion in that comparison comes from the rig baseline, which
# carries its own n >= MIN_GROUP gate inside mad_z; this floor only asks that the
# session median itself rest on more than one or two frames.
MIN_SESSION_MEDIAN_FRAMES = 3


def _group_label(key: str) -> str:
    """Turn a ``"telescope|camera|filter"`` baseline key into readable prose."""
    return " / ".join(part for part in key.split("|") if part) or "Unknown rig"


def hfr_outlier_insight(median_hfr, hfr_values, prefix="") -> SessionInsight | None:
    """Frames whose HFR exceeds 1.5x the session median.

    HFR is unbounded, so `median * 1.5` is always exceedable and the rule has no
    reachability flaw. Its scale-invariance (a soft night tolerates more spread)
    is a calibration opinion, not a bug, and is left as-is.
    """
    if median_hfr is None or len(hfr_values) <= 2:
        return None
    threshold = median_hfr * 1.5
    count = sum(1 for v in hfr_values if v > threshold)
    if count == 0:
        return None
    plural = "s" if count > 1 else ""
    return SessionInsight(
        level="warning",
        kind="hfr_outliers",
        message=f"{prefix}{count} frame{plural} with HFR outlier{plural} (> {threshold:.1f})",
    )


def ecc_outlier_insight(frames, baselines, prefix="") -> SessionInsight | None:
    """Frames whose eccentricity is >= Z_REJECT MAD worse than their own group.

    This replaces a `median_ecc * 1.5` rule that could not work: eccentricity is
    bounded [0, 1] by definition, so the threshold scaled with the median's
    absolute value rather than with dispersion. At median 0.2 a frame tripped at
    0.3; at median 0.5 it needed 0.75; at median >= 0.667 the threshold was >= 1.0
    and nothing could ever trip it. The rule desensitized exactly as frames got
    worse and went fully dark at the extreme, and a night of uniformly bad frames
    flagged nothing.

    A MAD z-score keys off dispersion instead, uses the same baselines the
    per-frame grading table uses, and fires at the same threshold as the
    frontend's "reject" band -- so the sentence and the red cells beside it
    always agree. When no baseline is usable (sparse group, uniform group,
    missing metric) no insight is emitted rather than a wrong one.
    """
    count, graded = frame_quality.count_outliers(frames, baselines, "eccentricity")
    if graded == 0 or count == 0:
        return None
    plural = "s" if count > 1 else ""
    return SessionInsight(
        level="warning",
        kind="eccentricity_outliers",
        message=(
            f"{prefix}{count} frame{plural} with eccentricity outlier{plural} "
            f"(≥ {frame_quality.Z_REJECT:.0f} MAD above the group median)"
        ),
    )


def session_ecc_vs_rig_insights(session_baselines, rig_baselines) -> list[SessionInsight]:
    """Whole-night check: this session's median eccentricity vs the rig's history.

    The per-frame z-score genuinely cannot see a night where *every* frame is
    elongated, because the session median moves with the frames it is measuring.
    Comparing the session median against a baseline built from a different,
    larger sample is the only way to catch systematic failure (bad collimation,
    tilt, a sagging focuser, poor polar alignment for the night).

    Two honest caveats:

    1. `rig_baselines` is built from every LIGHT frame in the catalog for this
       train+filter, which INCLUDES the frames of the session being viewed. That
       is mild self-contamination: the session drags the baseline slightly
       towards itself and shrinks z. The effect is conservative (it can only
       hide a warning, never invent one) and shrinks as the catalog grows, so it
       is noted rather than fixed here.
    2. z compares a median against a per-frame MAD. The sampling distribution of
       a median is narrower than that of a single frame, so Z_REJECT is a
       conservative bar for this comparison too.
    """
    insights: list[SessionInsight] = []
    for key, metrics in sorted((session_baselines or {}).items()):
        session_ecc = (metrics or {}).get("eccentricity") or {}
        session_median = session_ecc.get("median")
        if session_median is None or (session_ecc.get("n") or 0) < MIN_SESSION_MEDIAN_FRAMES:
            continue
        rig_ecc = ((rig_baselines or {}).get(key) or {}).get("eccentricity")
        z = frame_quality.mad_z(session_median, rig_ecc)
        if z is None or z < frame_quality.Z_REJECT:
            continue
        insights.append(SessionInsight(
            level="warning",
            kind="eccentricity_vs_rig",
            message=(
                f"[{_group_label(key)}] Whole session is elongated: median eccentricity "
                f"{session_median:.2f} vs {rig_ecc['median']:.2f} typical for this rig "
                f"({z:.1f} MAD above normal)"
            ),
        ))
    return insights


def compute_insights(
    *,
    median_hfr: float | None,
    hfr_values: list[float],
    temp_values: list[float],
    target_avg_hfr: float | None,
    is_best_hfr: bool,
    first_frame,
    last_frame,
    frames: list | None = None,
    baselines: dict | None = None,
) -> list[SessionInsight]:
    """Session-level insights.

    `frames` and `baselines` are the same normalized frame dicts and
    MAD baselines the per-frame grading table is built from, passed in rather
    than re-derived here so the two never drift apart.
    """
    insights = []

    if first_frame.capture_date and last_frame.capture_date:
        duration = last_frame.capture_date - first_frame.capture_date
        hours = duration.total_seconds() / 3600
        minutes = (duration.total_seconds() % 3600) / 60
        insights.append(SessionInsight(
            level="info",
            kind="session_duration",
            message=f"Session duration: {int(hours)}h {int(minutes)}m ({first_frame.capture_date.strftime('%H:%M')} → {last_frame.capture_date.strftime('%H:%M')})",
        ))

    if median_hfr is not None and target_avg_hfr is not None:
        if is_best_hfr:
            insights.append(SessionInsight(
                level="good",
                kind="hfr_vs_target",
                message=f"Best HFR session for this target (median {median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
            ))
        elif median_hfr > target_avg_hfr * 1.3:
            insights.append(SessionInsight(
                level="warning",
                kind="hfr_vs_target",
                message=f"Poor HFR session (median {median_hfr:.2f} vs target avg {target_avg_hfr:.2f})",
            ))

    if temp_values:
        temp_range = max(temp_values) - min(temp_values)
        if temp_range < 1.0:
            insights.append(SessionInsight(
                level="good",
                kind="sensor_temp",
                message=f"Stable sensor temperature ({min(temp_values):.0f}°C ± {temp_range:.1f}°C)",
            ))
        elif temp_range >= 3.0:
            insights.append(SessionInsight(
                level="warning",
                kind="sensor_temp",
                message=f"Unstable sensor temperature (range: {min(temp_values):.0f}°C to {max(temp_values):.0f}°C)",
            ))

    hfr_insight = hfr_outlier_insight(median_hfr, hfr_values)
    if hfr_insight:
        insights.append(hfr_insight)

    ecc_insight = ecc_outlier_insight(frames, baselines)
    if ecc_insight:
        insights.append(ecc_insight)

    return insights
