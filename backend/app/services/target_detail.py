"""Target detail, session-detail, and export logic.

Pure extraction of the business/DB logic that used to live in
app/services/target_aggregation.py (itself extracted from app/api/targets.py).
Behavior (query shapes, response models, status codes via HTTPException) is
preserved exactly.
"""

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import date as date_type

from fastapi import HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Target, Image
from app.models.catalog_membership import TargetCatalogMembership
from app.models.session_note import SessionNote
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment
from app.services.wbpp_export import fits_relative_path
from app.schemas.target import (
    SessionDetailResponse, TargetDetailResponse, SessionOverview,
    FilterDetail, FilterMedian, SessionInsight, FrameRecord,
)
from app.schemas.export import ExportResponse, ExportFilterRow, ExportEquipment, ExportCalibration
from app.services import frame_quality
from app.services.units import plate_scale_from_headers, to_arcsec
from app.services.target_helpers import (
    parse_sexa_ra, parse_sexa_dec, categorize_object_type, build_rig_details, compute_insights,
    hfr_outlier_insight, ecc_outlier_insight, session_ecc_vs_rig_insights,
)


def image_rotation(img) -> float | None:
    """Return an image's camera/framing rotation in degrees, or None.

    Single source of truth for deriving the rotation that is forwarded to
    NINA's framing assistant (set-rotation). Prefer the parsed
    ``rotator_position`` column; fall back to the ``OBJCTROT`` FITS keyword
    stored in ``raw_headers``. Images scanned before rotator extraction (the
    vast majority) have a null column but still carry OBJCTROT in raw_headers,
    so this keeps rotation available without a re-scan. Units/convention match
    what NINA writes to and reads back from OBJCTROT (degrees, sky position
    angle).
    """
    if img.rotator_position is not None:
        return img.rotator_position
    raw = img.raw_headers or {}
    val = raw.get("OBJCTROT")
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


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

    # Fetch LIGHT frames for this target. Project only the columns the export
    # actually reads instead of loading full ORM rows (which pull the large
    # raw_headers JSONB the export never touches). Pattern mirrors
    # get_target_detail's _detail_cols projection.
    _export_cols = (
        Image.session_date,
        Image.filter_used,
        Image.exposure_time,
        Image.telescope,
        Image.camera,
        Image.camera_gain,
        Image.sensor_temp,
        Image.fwhm,
        Image.sky_quality,
        Image.ambient_temp,
    )
    q = (
        select(*_export_cols)
        .where(Image.resolved_target_id == target_id)
        .where(Image.image_type == "LIGHT")
        .where(Image.capture_date.is_not(None))
        .order_by(Image.capture_date)
    )
    images = (await session.execute(q)).all()

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


def _median_arcsec(images, attr: str) -> float | None:
    """Median of a pixel-domain metric converted per-frame to arcsec.

    Frames without the metric or without a derivable plate scale
    (XPIXSZ/FOCALLEN in raw_headers) are excluded. None when nothing converts.
    """
    vals = []
    for img in images:
        metric = getattr(img, attr, None)
        if metric is None:
            continue
        scale = plate_scale_from_headers(getattr(img, "raw_headers", None))
        if scale is None:
            continue
        try:
            vals.append(float(metric) * scale)
        except (TypeError, ValueError):
            continue
    return statistics.median(vals) if vals else None


def _modal_source_ecc(pairs: list[tuple]) -> tuple[float | None, int | None]:
    """Mean eccentricity restricted to the modal provenance source.

    `pairs` is [(eccentricity_source, eccentricity), ...] for frames with a
    non-None eccentricity. The three sources (header / ellipticity / csv)
    measure eccentricity by different methods and must not be pooled; the mean
    is taken over the most common source only. Returns (mean, excluded_count),
    both None when there are no values.
    """
    if not pairs:
        return None, None
    counts = Counter(src for src, _ in pairs)
    # Deterministic tie-break: highest count, then lexicographically smallest
    # source name (None source sorts last), matching the library-level
    # aggregation in api/stats.py so target and library averages agree.
    modal_src, modal_n = min(
        counts.items(),
        key=lambda kv: (-kv[1], kv[0] is None, kv[0] or ""),
    )
    vals = [v for src, v in pairs if src == modal_src]
    return statistics.mean(vals), len(pairs) - len(vals)


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
        Image.eccentricity_source,
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
    all_hfr_arcsec = []
    all_ecc_pairs: list[tuple] = []  # (eccentricity_source, eccentricity)
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
            hfr_as = to_arcsec(
                img.median_hfr,
                (img.raw_headers or {}).get("XPIXSZ"),
                (img.raw_headers or {}).get("FOCALLEN"),
            )
            if hfr_as is not None:
                all_hfr_arcsec.append(hfr_as)
        if img.eccentricity is not None:
            all_ecc_pairs.append((img.eccentricity_source, img.eccentricity))
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
            img_rot = image_rotation(img)
            if img_rot is not None:
                sess_rotator = img_rot

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
            hfr_arcsec=_median_arcsec(sess_images, "median_hfr"),
            fwhm_arcsec=_median_arcsec(sess_images, "fwhm"),
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
            img_rot = image_rotation(img)
            if img_rot is not None:
                fallback_pa = img_rot
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

    avg_ecc_modal, ecc_excluded = _modal_source_ecc(all_ecc_pairs)

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
        avg_hfr_arcsec=statistics.mean(all_hfr_arcsec) if all_hfr_arcsec else None,
        avg_eccentricity=avg_ecc_modal,
        ecc_excluded_count=ecc_excluded,
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

    result = await session.execute(query)
    images = result.scalars().all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found for this session")

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
            file_size=img.file_size,
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
            rig=f"{normalize_equipment(img.telescope, tel_map) or 'Unknown'} / {normalize_equipment(img.camera, cam_map) or 'Unknown'}",
        ))

    rig_details = build_rig_details(images, filter_map, cam_map, tel_map)

    # --- Frame-quality baselines (MAD-based, computed on the fly) ---
    # Group keys use normalized telescope/camera/filter so they match the
    # frontend `groupKey(frame)` built from the same normalized values.
    # Computed here, above the insight rules, because the insights grade
    # eccentricity against these very baselines: one statistical spine feeds both
    # the per-frame grading table and the sentences printed above it.
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

    # Same frames, bucketed by the label build_rig_details assigns, so the
    # per-rig insight block can grade a rig's frames against their own
    # train+filter baselines without rebuilding them a second way.
    rig_frame_dicts: dict[str, list[dict]] = defaultdict(list)
    for fd in session_frame_dicts:
        label = f"{fd['telescope'] or 'Unknown'} / {fd['camera'] or 'Unknown'}"
        rig_frame_dicts[label].append(fd)

    # --- Cross-session HFR verdicts, ranked in arcsec (AUD: cross-train) ---
    # Sessions for one target can come from different optical trains, so
    # ranking their pixel-domain HFR medians against each other is meaningless.
    # Each frame is converted to arcsec via its own plate scale
    # (XPIXSZ/FOCALLEN raw headers); frames/sessions without a derivable plate
    # scale are EXCLUDED from the ranking rather than silently compared in
    # pixels. When the current session itself has no plate scale, no
    # best/poor-HFR verdict is emitted at all.
    session_hfr_arcsec = _median_arcsec(images, "median_hfr")
    session_fwhm_arcsec = _median_arcsec(images, "fwhm")
    is_best_hfr = False
    target_avg_hfr_arcsec: float | None = None
    if median_hfr is not None:
        # Query HFR data (plus plate-scale headers) across all sessions for
        # this target.
        _hfr_cols = (
            Image.session_date,
            Image.median_hfr,
            Image.raw_headers["XPIXSZ"].astext,
            Image.raw_headers["FOCALLEN"].astext,
        )
        if target_id == "obj:__uncategorized__":
            all_hfr_q = select(*_hfr_cols).where(
                Image.resolved_target_id.is_(None),
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
                Image.median_hfr.isnot(None),
            )
        elif target_id.startswith("obj:"):
            all_hfr_q = select(*_hfr_cols).where(
                Image.raw_headers["OBJECT"].astext == target_id[4:],
                Image.image_type == "LIGHT",
                Image.median_hfr.isnot(None),
            )
        else:
            all_hfr_q = select(*_hfr_cols).where(
                Image.resolved_target_id == tid,
                Image.image_type == "LIGHT",
                Image.median_hfr.isnot(None),
            )
        all_hfr_rows = (await session.execute(all_hfr_q)).all()
        all_session_arcsec: dict[str, list[float]] = defaultdict(list)
        all_arcsec_vals: list[float] = []
        for session_date_val, hfr_val, xpixsz, focallen in all_hfr_rows:
            hfr_as = to_arcsec(hfr_val, xpixsz, focallen)
            if hfr_as is None:
                continue
            all_arcsec_vals.append(hfr_as)
            if session_date_val:
                all_session_arcsec[str(session_date_val)].append(hfr_as)
        if all_arcsec_vals:
            target_avg_hfr_arcsec = statistics.mean(all_arcsec_vals)
        all_session_medians = [statistics.median(v) for v in all_session_arcsec.values() if v]
        if all_session_medians and session_hfr_arcsec is not None:
            is_best_hfr = session_hfr_arcsec <= min(all_session_medians)

    insights = compute_insights(
        median_hfr=median_hfr,
        hfr_values=hfr_values,
        temp_values=temp_values,
        median_hfr_arcsec=session_hfr_arcsec,
        target_avg_hfr_arcsec=target_avg_hfr_arcsec,
        is_best_hfr=is_best_hfr,
        first_frame=images[0],
        last_frame=images[-1],
        frames=session_frame_dicts,
        baselines=session_baselines,
    )

    # Per-rig insights for multi-rig sessions. The HFR-vs-target comparison is
    # done in arcsec for the same cross-train reason as above; a rig whose
    # frames carry no plate scale gets no hfr_vs_target verdict.
    if len(rig_details) > 1:
        rig_images_by_label: dict[str, list] = defaultdict(list)
        for img in images:
            label = (
                f"{normalize_equipment(img.telescope, tel_map) or 'Unknown'}"
                f" / {normalize_equipment(img.camera, cam_map) or 'Unknown'}"
            )
            rig_images_by_label[label].append(img)
        for rd in rig_details:
            rig_hfr = [f.median_hfr for f in rd.frames if f.median_hfr is not None]
            rig_median_hfr = statistics.median(rig_hfr) if rig_hfr else None
            rig_hfr_arcsec = _median_arcsec(rig_images_by_label.get(rd.rig_label, []), "median_hfr")
            prefix = f"[{rd.rig_label}] "
            if rig_hfr_arcsec is not None and target_avg_hfr_arcsec is not None:
                if rig_hfr_arcsec <= target_avg_hfr_arcsec:
                    insights.append(SessionInsight(
                        level="good",
                        kind="hfr_vs_target",
                        message=(
                            f"{prefix}Good HFR (median {rig_hfr_arcsec:.2f}\" vs "
                            f"target avg {target_avg_hfr_arcsec:.2f}\")"
                        ),
                    ))
                elif rig_hfr_arcsec > target_avg_hfr_arcsec * 1.3:
                    insights.append(SessionInsight(
                        level="warning",
                        kind="hfr_vs_target",
                        message=(
                            f"{prefix}Poor HFR (median {rig_hfr_arcsec:.2f}\" vs "
                            f"target avg {target_avg_hfr_arcsec:.2f}\")"
                        ),
                    ))
            # Same two rules as the session-level block, same helpers: HFR keeps
            # its 1.5x-median rule, eccentricity is graded by MAD z.
            rig_hfr_insight = hfr_outlier_insight(rig_median_hfr, rig_hfr, prefix=prefix)
            if rig_hfr_insight:
                insights.append(rig_hfr_insight)
            rig_ecc_insight = ecc_outlier_insight(
                rig_frame_dicts.get(rd.rig_label, []), session_baselines, prefix=prefix
            )
            if rig_ecc_insight:
                insights.append(rig_ecc_insight)

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

    # Catalog-wide frames: every LIGHT frame across all targets and sessions,
    # grouped by telescope|camera|filter. This is the "This rig overall"
    # baseline. It is target-independent, which makes the per-frame
    # "This session / This rig overall" toggle meaningful even for
    # single-session targets.
    #
    # This scanned the entire images table on every session-card open, which
    # dominated the endpoint cost on a large catalog. The result only changes
    # when the catalog does, so it is cached in Redis and invalidated by the
    # catalog-mutating Celery tasks (see worker.tasks._invalidate_stats_cache);
    # the TTL is a backstop for any path that mutates metrics without hitting
    # that invalidation.
    from app.services.cache import (
        cached_json, RIG_BASELINES_CACHE_KEY, RIG_BASELINES_CACHE_TTL,
    )

    async def _compute_rig_baselines():
        metric_cols = (
            Image.telescope, Image.camera, Image.filter_used,
            Image.median_hfr, Image.fwhm, Image.eccentricity,
            Image.detected_stars, Image.adu_median, Image.guiding_rms_arcsec,
        )
        catalog_frames_q = select(*metric_cols).where(Image.image_type == "LIGHT")
        catalog_frame_rows = (await session.execute(catalog_frames_q)).all()
        catalog_frame_dicts = [_baseline_frame(*row) for row in catalog_frame_rows]
        return frame_quality.group_baselines(catalog_frame_dicts)

    rig_baselines = await cached_json(
        RIG_BASELINES_CACHE_KEY, RIG_BASELINES_CACHE_TTL, _compute_rig_baselines
    )

    # Whole-night eccentricity check. Deliberately last: it needs the rig
    # baseline, which is the only sample wide enough to notice that every frame
    # tonight is elongated. The per-frame z-score above is blind to that case
    # because the session median it compares against moves with the bad frames.
    insights.extend(session_ecc_vs_rig_insights(session_baselines, rig_baselines))

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
        hfr_arcsec=session_hfr_arcsec,
        fwhm_arcsec=session_fwhm_arcsec,
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
