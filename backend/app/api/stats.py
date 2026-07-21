import asyncio
import logging
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from starlette.responses import Response
from sqlalchemy import select, func, case, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, async_redis
from app.database import get_session, async_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models import Image, Target
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment

from app.schemas.stats import (
    StatsResponse, OverviewStats, EquipmentStats, EquipmentItem,
    TimelineEntry, TimelineDetailEntry, TopTarget, DataQualityStats, HfrBucket,
    StorageStats, IngestEntry,
    EquipmentComboMetrics, EquipmentFilterMetrics,
    SiteCoords,
    CalendarEntry,
)
# astro_night is no longer imported here - efficiency uses precomputed DB table

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])

_STATS_CACHE_KEY = "galactilog:stats:cache"
_STATS_CACHE_TTL = 300  # 5 minutes

# Arcsec HFR histogram buckets: 0 to 8 arcsec in 0.5 steps, then an overflow
# bucket (8.0+). The final entry's high bound is None (unbounded).
_HFR_ARCSEC_BUCKET_RANGES: list[tuple[float, float | None]] = [
    (i * 0.5, (i + 1) * 0.5) for i in range(16)
] + [(8.0, None)]


def _should_cache_stats() -> bool:
    """Whether a freshly computed stats response is safe to persist to Redis.

    Guards the cold-start race: the on-disk storage sizes (fits_disk_bytes,
    thumbnail_bytes, overview.disk_usage_bytes) come from _storage_cache, which
    starts at 0 and is only filled by the background _refresh_storage_cache().
    The very first request after startup runs before that du finishes, so its
    response carries 0 for those sizes. Persisting that would freeze "0 on disk"
    for the full cache TTL even though du warms the in-memory cache ~1.5s later.
    _storage_last_update stays at 0 until at least one refresh has completed
    (it is set on every refresh, including timeout), so a non-zero value means
    storage has been computed at least once and the response is safe to cache.
    """
    return _storage_last_update != 0

# --- Storage size cache (du over the FITS and thumbnails volumes) ---
# Both the true on-disk FITS size and the thumbnail size are measured by du and
# cached here. Separately, _compute_fits_bytes sums the catalogued FITS size
# from the DB (Image.file_size); the two FITS figures are exposed side by side
# (catalogued vs. true on-disk) since the FITS directory is an NFS share where a
# recursive stat of ~90k files can be slow and may include uncatalogued files.
_storage_cache: dict[str, int] = {"fits": 0, "thumbnails": 0}
_storage_last_update: float = 0
# No asyncio.Lock here: a module-level Lock binds to the first event loop that
# uses it and raises RuntimeError on any later loop (test isolation, multi-worker).
# Concurrent du refreshes are idempotent — the last writer wins, which is fine.
_STORAGE_TTL = 300  # refresh every 5 minutes


_DU_TIMEOUT = 120  # seconds; the local thumbnails volume is fast, but allow a
# generous bound so a momentarily busy disk degrades to the cached value
# rather than failing.


async def _compute_fits_bytes(session: AsyncSession) -> int:
    """Total bytes of catalogued FITS files, summed from the DB.

    Replaces a recursive `du` over the FITS directory, which lives on an NFS
    share where stat-ing ~90k files routinely exceeds any timeout. The DB
    aggregate is O(rows) and runs in milliseconds.

    This naturally tracks the `include_calibration` setting: when calibration
    frames are excluded (the default) they are never ingested, so they are not
    rows here and contribute nothing; when calibration is included, their
    file_size is summed in. Rows with a NULL file_size (older ingests that
    predate the column) are ignored by SUM, and COALESCE guards an empty table.
    """
    q = select(func.coalesce(func.sum(Image.file_size), 0))
    return int((await session.execute(q)).scalar_one())


def _compute_dir_size(path: str, fallback: int = 0) -> int:
    """Compute directory size using du (fast).

    On timeout or any error, returns `fallback` (the last-known cached value)
    so callers never display a bogus 0 after a transient failure.
    """
    p = Path(path)
    if not p.exists():
        return 0
    try:
        result = subprocess.run(
            ["du", "-sb", str(p)], capture_output=True, text=True, timeout=_DU_TIMEOUT
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except subprocess.TimeoutExpired:
        logger.warning("du timed out for %s after %ss; using cached size", path, _DU_TIMEOUT)
    except Exception:
        logger.debug("du failed for %s; using cached size", path)
    return fallback


async def _refresh_storage_cache() -> None:
    """Refresh the FITS and thumbnail storage sizes in background threads.

    On timeout or error, the existing cached value is preserved rather than
    being overwritten with 0.  Concurrent refreshes within the same TTL window
    are harmless: the TTL guard short-circuits the second call and any races
    produce an idempotent last-write-wins outcome.
    """
    global _storage_last_update
    if time.time() - _storage_last_update < _STORAGE_TTL:
        return  # still fresh; skip
    fits = await asyncio.to_thread(
        _compute_dir_size, settings.fits_data_path, _storage_cache["fits"]
    )
    thumbs = await asyncio.to_thread(
        _compute_dir_size, settings.thumbnails_path, _storage_cache["thumbnails"]
    )
    _storage_cache["fits"] = fits
    _storage_cache["thumbnails"] = thumbs
    _storage_last_update = time.time()


_site_coords_cache: SiteCoords | None = None
_site_coords_ts: float = 0.0
_SITE_COORDS_TTL = 3600  # 1 hour


async def _extract_site_coords(session: AsyncSession) -> SiteCoords | None:
    """Extract the most common lat/lon from FITS raw_headers.

    Checks SITELAT/SITELONG (N.I.N.A.), OBSLAT/OBSLONG, and LAT-OBS/LONG-OBS.
    Returns the most frequently occurring coordinate pair, or None.
    Results are cached in-memory for 1 hour since site coordinates never change
    between scans.
    """
    global _site_coords_cache, _site_coords_ts
    if _site_coords_cache is not None and (time.time() - _site_coords_ts) < _SITE_COORDS_TTL:
        return _site_coords_cache

    lat_keys = ["SITELAT", "OBSLAT", "LAT-OBS"]
    lon_keys = ["SITELONG", "OBSLONG", "LONG-OBS"]

    for lat_key, lon_key in zip(lat_keys, lon_keys):
        q = select(
            Image.raw_headers[lat_key].astext.label("lat"),
            Image.raw_headers[lon_key].astext.label("lon"),
            func.count().label("cnt"),
        ).where(
            Image.raw_headers[lat_key].isnot(None),
            Image.raw_headers[lon_key].isnot(None),
        ).group_by("lat", "lon").order_by(func.count().desc()).limit(1)

        result = await session.execute(q)
        row = result.first()
        if row and row.lat and row.lon:
            try:
                coords = SiteCoords(latitude=float(row.lat), longitude=float(row.lon))
                _site_coords_cache = coords
                _site_coords_ts = time.time()
                return coords
            except (ValueError, TypeError):
                continue
    return None


def _extract_site_coords_sync(session) -> SiteCoords | None:
    """Sync version of _extract_site_coords for use in Celery workers."""
    lat_keys = ["SITELAT", "OBSLAT", "LAT-OBS"]
    lon_keys = ["SITELONG", "OBSLONG", "LONG-OBS"]

    for lat_key, lon_key in zip(lat_keys, lon_keys):
        q = select(
            Image.raw_headers[lat_key].astext.label("lat"),
            Image.raw_headers[lon_key].astext.label("lon"),
            func.count().label("cnt"),
        ).where(
            Image.raw_headers[lat_key].isnot(None),
            Image.raw_headers[lon_key].isnot(None),
        ).group_by("lat", "lon").order_by(func.count().desc()).limit(1)

        result = session.execute(q)
        row = result.first()
        if row and row.lat and row.lon:
            try:
                return SiteCoords(latitude=float(row.lat), longitude=float(row.lon))
            except (ValueError, TypeError):
                continue
    return None


@router.get("", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return comprehensive database analytics for the admin page.

    Two FITS sizes are reported: the catalogued size summed from the DB
    (Image.file_size) and the true on-disk size measured by du. Both the FITS
    and thumbnail du sizes are cached and refreshed in the background every 5
    minutes, so the first request after startup may report 0 for those until
    that du completes. Stats response is cached in Redis for 5 minutes to avoid
    repeated full-table scans.
    """

    # Check Redis cache first
    try:
        async with async_redis() as r:
            cached = await r.get(_STATS_CACHE_KEY)
        if cached:
            return Response(content=cached, media_type="application/json")
    except Exception:
        logger.debug("Redis cache read failed for stats, computing fresh")

    # Kick off storage refresh in background (non-blocking)
    if time.time() - _storage_last_update >= _STORAGE_TTL:
        asyncio.create_task(_refresh_storage_cache())

    # --- All DB queries below run in parallel where possible ---
    # Each parallel branch uses its own session (asyncpg requires it).

    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # --- Define parallel query coroutines (each opens its own session) ---

    async def _query_overview():
        capture_date_col = Image.session_date
        has_date = Image.capture_date.isnot(None)
        # Frames belonging to a merged-away (loser) target should not be
        # double-counted under a stale target id; mirrors the merged-target
        # guard in target_aggregation.list_targets_aggregated (AUD-032, axis 3).
        merged_ok = or_(Image.resolved_target_id.is_(None), Target.merged_into_id.is_(None))
        # rig_session_count: distinct (night, telescope, camera) combinations.
        # This is deliberately NOT "distinct nights" -- a night imaged with two
        # rigs counts as two rig-sessions here. Every other surface (the
        # calendar below, target-detail session_count, the paginated
        # aggregation) counts distinct session_date alone, i.e. imaging
        # nights. Both definitions are kept and exposed as separate,
        # explicitly-named metrics rather than unified; see AUD-019. Do not
        # rename this back to a bare "session_count" / "sessions" label.
        rig_session_expr = func.concat(
            capture_date_col,
            "|",
            func.coalesce(Image.telescope, ""),
            "|",
            func.coalesce(Image.camera, ""),
        )
        q = select(
            func.coalesce(func.sum(Image.exposure_time).filter(has_date), 0),
            func.count(func.distinct(Image.resolved_target_id)).filter(has_date),
            # total_frames: all LIGHT frames regardless of capture_date, matching
            # its "all LIGHT frames" label (AUD-032, axis 2: the aggregation
            # used for the Dashboard sidebar counts NULL-capture_date frames
            # too, so this no longer silently excludes them here).
            func.count(Image.id),
            func.count(func.distinct(rig_session_expr)).filter(has_date),
            func.min(capture_date_col).filter(has_date),
            func.max(capture_date_col).filter(has_date),
        ).select_from(Image).outerjoin(
            Target, Image.resolved_target_id == Target.id
        ).where(
            Image.image_type == "LIGHT",
            merged_ok,
        )
        async with async_session() as s:
            return (await s.execute(q)).one()

    # Plate scale (arcsec/px) materialized at scan time from the
    # XPIXSZ/FOCALLEN raw headers; NULL when underivable, so multiplying a
    # pixel metric by it yields NULL and percentile_cont skips the frame.
    # This keeps the pooled arcsec medians unit-consistent across optical
    # trains, unlike the raw pixel medians beside them.
    _scale = Image.arcsec_per_pixel

    async def _query_cameras():
        q = select(
            Image.camera,
            func.count(Image.id),
            func.coalesce(func.sum(Image.exposure_time), 0),
            func.array_agg(func.distinct(Image.session_date)),
            func.array_agg(func.distinct(Image.resolved_target_id)),
            func.percentile_cont(0.5).within_group(func.nullif(Image.fwhm, 0)).label("med_fwhm"),
            func.percentile_cont(0.5).within_group(func.nullif(Image.guiding_rms_arcsec, 0)).label("med_guide"),
            func.percentile_cont(0.5).within_group(func.nullif(Image.fwhm, 0) * _scale).label("med_fwhm_arcsec"),
        ).where(
            Image.camera.isnot(None)
        ).group_by(Image.camera).order_by(func.count(Image.id).desc())
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_telescopes():
        q = select(
            Image.telescope,
            func.count(Image.id),
            func.coalesce(func.sum(Image.exposure_time), 0),
            func.array_agg(func.distinct(Image.session_date)),
            func.array_agg(func.distinct(Image.resolved_target_id)),
            func.percentile_cont(0.5).within_group(func.nullif(Image.fwhm, 0)).label("med_fwhm"),
            func.percentile_cont(0.5).within_group(func.nullif(Image.guiding_rms_arcsec, 0)).label("med_guide"),
            func.percentile_cont(0.5).within_group(func.nullif(Image.fwhm, 0) * _scale).label("med_fwhm_arcsec"),
        ).where(
            Image.telescope.isnot(None)
        ).group_by(Image.telescope).order_by(func.count(Image.id).desc())
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_equipment_perf():
        hfr_nz = func.nullif(Image.median_hfr, 0)
        ecc_nz = func.nullif(Image.eccentricity, 0)
        fwhm_nz = func.nullif(Image.fwhm, 0)
        q = select(
            Image.telescope,
            Image.camera,
            Image.filter_used,
            func.count(Image.id).label("frame_count"),
            func.coalesce(func.sum(Image.exposure_time), 0).label("total_seconds"),
            func.array_agg(func.distinct(Image.session_date)).label("session_dates"),
            func.percentile_cont(0.5).within_group(hfr_nz).label("med_hfr"),
            func.min(hfr_nz).label("best_hfr"),
            func.percentile_cont(0.5).within_group(ecc_nz).label("med_ecc"),
            func.percentile_cont(0.5).within_group(fwhm_nz).label("med_fwhm"),
        ).where(
            Image.image_type == "LIGHT",
            Image.telescope.isnot(None),
            Image.camera.isnot(None),
        ).group_by(Image.telescope, Image.camera, Image.filter_used)
        async with async_session() as s:
            return (await s.execute(q)).all()

    def _norm_case(col, alias_map: dict[str, str]):
        """SQL expression mapping a raw equipment name to its canonical form.

        Mirrors normalize_equipment() (an exact-match dict lookup) so MAD can be
        grouped by the SAME normalized (telescope, camera) combo the Python
        post-processing uses. Empty map -> the column unchanged.
        """
        if not alias_map:
            return col
        return case(alias_map, value=col, else_=col)

    async def _query_equipment_mad():
        """Median absolute deviation of hfr/ecc/fwhm per normalized (telescope,
        camera) combo, computed entirely in SQL (two passes of percentile_cont):
        group median, then median of abs(value - median). Replaces shipping every
        frame's raw metric values to Python via array_agg.
        """
        norm_tel = _norm_case(Image.telescope, tel_map).label("norm_tel")
        norm_cam = _norm_case(Image.camera, cam_map).label("norm_cam")
        hfr_nz = func.nullif(Image.median_hfr, 0)
        ecc_nz = func.nullif(Image.eccentricity, 0)
        fwhm_nz = func.nullif(Image.fwhm, 0)
        base = (
            select(
                norm_tel,
                norm_cam,
                hfr_nz.label("hfr"),
                ecc_nz.label("ecc"),
                fwhm_nz.label("fwhm"),
            )
            .where(
                Image.image_type == "LIGHT",
                Image.telescope.isnot(None),
                Image.camera.isnot(None),
            )
            .subquery()
        )
        med = (
            select(
                base.c.norm_tel,
                base.c.norm_cam,
                func.percentile_cont(0.5).within_group(base.c.hfr).label("med_hfr"),
                func.percentile_cont(0.5).within_group(base.c.ecc).label("med_ecc"),
                func.percentile_cont(0.5).within_group(base.c.fwhm).label("med_fwhm"),
            )
            .group_by(base.c.norm_tel, base.c.norm_cam)
            .subquery()
        )
        mad_q = (
            select(
                base.c.norm_tel,
                base.c.norm_cam,
                func.percentile_cont(0.5)
                .within_group(func.abs(base.c.hfr - med.c.med_hfr))
                .label("mad_hfr"),
                func.percentile_cont(0.5)
                .within_group(func.abs(base.c.ecc - med.c.med_ecc))
                .label("mad_ecc"),
                func.percentile_cont(0.5)
                .within_group(func.abs(base.c.fwhm - med.c.med_fwhm))
                .label("mad_fwhm"),
            )
            .select_from(
                base.join(
                    med,
                    and_(
                        base.c.norm_tel == med.c.norm_tel,
                        base.c.norm_cam == med.c.norm_cam,
                    ),
                )
            )
            .group_by(base.c.norm_tel, base.c.norm_cam)
        )
        async with async_session() as s:
            rows = (await s.execute(mad_q)).all()
        return {(r.norm_tel, r.norm_cam): r for r in rows}

    async def _query_filter_usage():
        q = select(
            Image.filter_used, func.coalesce(func.sum(Image.exposure_time), 0)
        ).where(
            Image.filter_used.isnot(None), Image.image_type == "LIGHT"
        ).group_by(Image.filter_used)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_timeline_monthly():
        month_label = func.to_char(Image.session_date, 'YYYY-MM').label('month')
        q = select(
            month_label,
            func.coalesce(func.sum(Image.exposure_time), 0),
        ).where(
            Image.session_date.isnot(None), Image.image_type == "LIGHT"
        ).group_by(month_label).order_by(month_label)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_site_coords():
        async with async_session() as s:
            return await _extract_site_coords(s)

    async def _query_timeline_weekly():
        week_label = func.to_char(Image.session_date, 'IYYY-"W"IW').label('week')
        q = select(
            week_label,
            func.coalesce(func.sum(Image.exposure_time), 0),
        ).where(
            Image.session_date.isnot(None), Image.image_type == "LIGHT"
        ).group_by(week_label).order_by(week_label)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_timeline_daily():
        day_label = func.to_char(Image.session_date, 'YYYY-MM-DD').label('day')
        q = select(
            day_label,
            func.coalesce(func.sum(Image.exposure_time), 0),
        ).where(
            Image.session_date.isnot(None), Image.image_type == "LIGHT"
        ).group_by(day_label).order_by(day_label)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_top_targets():
        q = select(
            Target.primary_name, func.coalesce(func.sum(Image.exposure_time), 0)
        ).join(Target, Image.resolved_target_id == Target.id).where(
            Image.image_type == "LIGHT"
        ).group_by(Target.primary_name).order_by(
            func.sum(Image.exposure_time).desc()
        ).limit(20)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_data_quality():
        hfr_arcsec = Image.median_hfr * _scale
        q = select(
            func.avg(Image.median_hfr),
            func.avg(Image.eccentricity),
            func.min(Image.median_hfr),
            # Arcsec equivalents pool only plate-scaled frames (NULL scale
            # nulls the product and avg/min skip it).
            func.avg(hfr_arcsec),
            func.min(hfr_arcsec),
            # Frames with an HFR but no derivable plate scale, excluded from
            # the arcsec aggregates; surfaced so the UI can disclose it.
            func.count(Image.id).filter(
                Image.median_hfr.isnot(None), _scale.is_(None)
            ),
        ).where(Image.image_type == "LIGHT")
        async with async_session() as s:
            return (await s.execute(q)).one()

    async def _query_hfr_buckets():
        bucket_ranges = [(0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 100)]
        bucket_cases = [
            func.count(Image.id).filter(
                Image.median_hfr >= low, Image.median_hfr < high
            ).label(f"b{i}")
            for i, (low, high) in enumerate(bucket_ranges)
        ]
        q = select(*bucket_cases).where(Image.image_type == "LIGHT")
        async with async_session() as s:
            return (await s.execute(q)).one()

    async def _query_hfr_arcsec_buckets():
        """HFR histogram in arcsec over plate-scaled frames only."""
        hfr_arcsec = Image.median_hfr * _scale
        bucket_cases = [
            func.count(Image.id).filter(
                hfr_arcsec >= low, hfr_arcsec < high
            ).label(f"a{i}")
            for i, (low, high) in enumerate(_HFR_ARCSEC_BUCKET_RANGES[:-1])
        ]
        overflow_low = _HFR_ARCSEC_BUCKET_RANGES[-1][0]
        bucket_cases.append(
            func.count(Image.id).filter(hfr_arcsec >= overflow_low).label("a_overflow")
        )
        q = select(*bucket_cases).where(Image.image_type == "LIGHT")
        async with async_session() as s:
            return (await s.execute(q)).one()

    async def _query_ecc_sources():
        """Per-provenance-source eccentricity counts and means.

        The three eccentricity_source values (header/ellipticity/csv, plus
        NULL for unknown) measure eccentricity by different methods and must
        not be pooled; the library average is restricted to the modal source.
        """
        q = select(
            Image.eccentricity_source,
            func.count(Image.id),
            func.avg(Image.eccentricity),
        ).where(
            Image.image_type == "LIGHT",
            Image.eccentricity.isnot(None),
        ).group_by(Image.eccentricity_source)
        async with async_session() as s:
            return (await s.execute(q)).all()

    async def _query_db_size():
        q = select(func.pg_database_size(func.current_database()))
        async with async_session() as s:
            try:
                return (await s.execute(q)).scalar_one()
            except Exception:
                return 0

    async def _query_fits_bytes():
        async with async_session() as s:
            return await _compute_fits_bytes(s)

    async def _query_all_frames():
        q = select(func.count(Image.id))
        async with async_session() as s:
            return (await s.execute(q)).scalar_one()

    async def _query_ingest_history():
        capture_day = Image.session_date.label('capture_day')
        q = select(
            capture_day, func.count(Image.id)
        ).where(
            Image.session_date.isnot(None)
        ).group_by(capture_day).order_by(capture_day.desc()).limit(30)
        async with async_session() as s:
            return (await s.execute(q)).all()

    # --- Run all queries in parallel ---
    (
        ov_row,
        cam_rows,
        tel_rows,
        perf_rows,
        mad_by_combo,
        filter_rows,
        monthly_rows,
        site_coords,
        weekly_rows,
        daily_rows,
        top_rows,
        quality_row,
        bucket_row,
        db_bytes,
        ingest_rows,
        fits_bytes,
        all_frames,
        arcsec_bucket_row,
        ecc_source_rows,
    ) = await asyncio.gather(
        _query_overview(),
        _query_cameras(),
        _query_telescopes(),
        _query_equipment_perf(),
        _query_equipment_mad(),
        _query_filter_usage(),
        _query_timeline_monthly(),
        _query_site_coords(),
        _query_timeline_weekly(),
        _query_timeline_daily(),
        _query_top_targets(),
        _query_data_quality(),
        _query_hfr_buckets(),
        _query_db_size(),
        _query_ingest_history(),
        _query_fits_bytes(),
        _query_all_frames(),
        _query_hfr_arcsec_buckets(),
        _query_ecc_sources(),
    )

    # --- Post-processing (sequential, CPU-only) ---

    # Overview
    (
        total_seconds,
        target_count,
        total_frames,
        rig_session_count,
        first_capture_date,
        last_capture_date,
    ) = ov_row

    overview = OverviewStats(
        total_integration_seconds=float(total_seconds),
        target_count=target_count,
        total_frames=total_frames,
        all_frames=all_frames,
        disk_usage_bytes=_storage_cache["fits"] + _storage_cache["thumbnails"],
        rig_session_count=rig_session_count or 0,
        first_capture_date=first_capture_date.isoformat() if first_capture_date else None,
        last_capture_date=last_capture_date.isoformat() if last_capture_date else None,
    )

    # Equipment - cameras
    # Rows are positional: r[0]=name, r[1]=count, r[2]=secs, r[3]=session_dates,
    # r[4]=target_ids, r[5]=med_fwhm (raw group), r[6]=med_guiding_rms (raw group).
    raw_cam_counts: dict[str, int] = {}
    raw_cam_secs: dict[str, float] = {}
    raw_cam_sessions: dict[str, set] = {}
    cam_raw_names: dict[str, set[str]] = {}
    raw_cam_targets: dict[str, set] = {}
    raw_cam_fwhm: dict[str, list[tuple[float, int]]] = {}
    raw_cam_guide: dict[str, list[tuple[float, int]]] = {}
    raw_cam_fwhm_as: dict[str, list[tuple[float, int]]] = {}
    for r in cam_rows:
        canonical = normalize_equipment(r[0], cam_map) or r[0]
        raw_cam_counts[canonical] = raw_cam_counts.get(canonical, 0) + r[1]
        raw_cam_secs[canonical] = raw_cam_secs.get(canonical, 0) + (r[2] or 0)
        raw_cam_sessions.setdefault(canonical, set()).update(d for d in (r[3] or []) if d is not None)
        cam_raw_names.setdefault(canonical, set()).add(r[0])
        raw_cam_targets.setdefault(canonical, set()).update(t for t in (r[4] or []) if t is not None)
        if r[5] is not None:
            raw_cam_fwhm.setdefault(canonical, []).append((r[5], r[1]))
        if r[6] is not None:
            raw_cam_guide.setdefault(canonical, []).append((r[6], r[1]))
        if len(r) > 7 and r[7] is not None:
            raw_cam_fwhm_as.setdefault(canonical, []).append((r[7], r[1]))

    # Equipment - telescopes
    raw_tel_counts: dict[str, int] = {}
    raw_tel_secs: dict[str, float] = {}
    raw_tel_sessions: dict[str, set] = {}
    tel_raw_names: dict[str, set[str]] = {}
    raw_tel_targets: dict[str, set] = {}
    raw_tel_fwhm: dict[str, list[tuple[float, int]]] = {}
    raw_tel_guide: dict[str, list[tuple[float, int]]] = {}
    raw_tel_fwhm_as: dict[str, list[tuple[float, int]]] = {}
    for r in tel_rows:
        canonical = normalize_equipment(r[0], tel_map) or r[0]
        raw_tel_counts[canonical] = raw_tel_counts.get(canonical, 0) + r[1]
        raw_tel_secs[canonical] = raw_tel_secs.get(canonical, 0) + (r[2] or 0)
        raw_tel_sessions.setdefault(canonical, set()).update(d for d in (r[3] or []) if d is not None)
        tel_raw_names.setdefault(canonical, set()).add(r[0])
        raw_tel_targets.setdefault(canonical, set()).update(t for t in (r[4] or []) if t is not None)
        if r[5] is not None:
            raw_tel_fwhm.setdefault(canonical, []).append((r[5], r[1]))
        if r[6] is not None:
            raw_tel_guide.setdefault(canonical, []).append((r[6], r[1]))
        if len(r) > 7 and r[7] is not None:
            raw_tel_fwhm_as.setdefault(canonical, []).append((r[7], r[1]))

    # EquipmentItem lists (and EquipmentStats) are built after the
    # weighted_median_approx helper is defined below, since the new median_fwhm /
    # median_guiding_rms fields depend on it.

    # Equipment Performance - aggregate by normalized telescope+camera
    combo_data: dict[tuple[str, str], dict] = {}
    for r in perf_rows:
        tel = normalize_equipment(r.telescope, tel_map) or r.telescope
        cam = normalize_equipment(r.camera, cam_map) or r.camera
        filt = normalize_filter(r.filter_used, filter_map) or r.filter_used
        key = (tel, cam)

        if key not in combo_data:
            combo_data[key] = {
                "frame_count": 0,
                "total_seconds": 0.0,
                "sessions": set(),
                "hfr_vals": [],
                "ecc_vals": [],
                "fwhm_vals": [],
                "best_hfr": None,
                "filters": set(),
                "filter_rows": {},
                "raw_telescopes": set(),
                "raw_cameras": set(),
            }

        combo_data[key]["raw_telescopes"].add(r.telescope)
        combo_data[key]["raw_cameras"].add(r.camera)

        cd = combo_data[key]
        cd["frame_count"] += r.frame_count
        cd["total_seconds"] += float(r.total_seconds)
        if getattr(r, "session_dates", None):
            cd["sessions"].update(d for d in r.session_dates if d is not None)

        if r.med_hfr is not None:
            cd["hfr_vals"].append((r.med_hfr, r.frame_count))
        if r.best_hfr is not None:
            if cd["best_hfr"] is None or r.best_hfr < cd["best_hfr"]:
                cd["best_hfr"] = r.best_hfr
        if r.med_ecc is not None:
            cd["ecc_vals"].append((r.med_ecc, r.frame_count))
        if r.med_fwhm is not None:
            cd["fwhm_vals"].append((r.med_fwhm, r.frame_count))

        if filt is None:
            continue
        cd["filters"].add(filt)

        fr = cd["filter_rows"].get(filt)
        if fr is None:
            fr = {
                "frame_count": 0,
                "total_seconds": 0.0,
                "hfr_vals": [],
                "ecc_vals": [],
                "fwhm_vals": [],
                "best_hfr": None,
            }
            cd["filter_rows"][filt] = fr

        fr["frame_count"] += r.frame_count
        fr["total_seconds"] += float(r.total_seconds)

        if r.med_hfr is not None:
            fr["hfr_vals"].append((r.med_hfr, r.frame_count))
        if r.best_hfr is not None:
            if fr["best_hfr"] is None or r.best_hfr < fr["best_hfr"]:
                fr["best_hfr"] = r.best_hfr
        if r.med_ecc is not None:
            fr["ecc_vals"].append((r.med_ecc, r.frame_count))
        if r.med_fwhm is not None:
            fr["fwhm_vals"].append((r.med_fwhm, r.frame_count))

    def weighted_median_approx(vals: list[tuple[float, int]]) -> float | None:
        """Approximate median from per-group medians weighted by frame count."""
        if not vals:
            return None
        vals_sorted = sorted(vals, key=lambda x: x[0])
        total = sum(c for _, c in vals_sorted)
        half = total / 2
        running = 0
        for val, count in vals_sorted:
            running += count
            if running >= half:
                return round(float(val), 2)
        return round(float(vals_sorted[-1][0]), 2)

    # Build equipment lists now that weighted_median_approx exists. nights is the
    # count of distinct session_date; target_count the distinct resolved targets;
    # median_fwhm / median_guiding_rms the frame-weighted median of the raw-group
    # medians via weighted_median_approx (consistent with the rest of stats).
    cameras = [
        EquipmentItem(
            name=name,
            frame_count=count,
            integration_seconds=raw_cam_secs[name],
            avg_session_seconds=(raw_cam_secs[name] / len(raw_cam_sessions[name])) if raw_cam_sessions[name] else None,
            grouped=len(cam_raw_names[name]) > 1,
            nights=len(raw_cam_sessions[name]),
            target_count=len(raw_cam_targets.get(name, set())),
            median_fwhm=weighted_median_approx(raw_cam_fwhm.get(name, [])),
            median_fwhm_arcsec=weighted_median_approx(raw_cam_fwhm_as.get(name, [])),
            median_guiding_rms=weighted_median_approx(raw_cam_guide.get(name, [])),
        )
        for name, count in sorted(raw_cam_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    telescopes = [
        EquipmentItem(
            name=name,
            frame_count=count,
            integration_seconds=raw_tel_secs[name],
            avg_session_seconds=(raw_tel_secs[name] / len(raw_tel_sessions[name])) if raw_tel_sessions[name] else None,
            grouped=len(tel_raw_names[name]) > 1,
            nights=len(raw_tel_sessions[name]),
            target_count=len(raw_tel_targets.get(name, set())),
            median_fwhm=weighted_median_approx(raw_tel_fwhm.get(name, [])),
            median_fwhm_arcsec=weighted_median_approx(raw_tel_fwhm_as.get(name, [])),
            median_guiding_rms=weighted_median_approx(raw_tel_guide.get(name, [])),
        )
        for name, count in sorted(raw_tel_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    equipment = EquipmentStats(cameras=cameras, telescopes=telescopes)

    def safe_round(v: float | None) -> float | None:
        return round(float(v), 2) if v is not None else None

    def combo_mad(value: float | None) -> float | None:
        return round(float(value), 3) if value is not None else None

    def build_filter_metrics(filter_rows_dict: dict) -> list[EquipmentFilterMetrics]:
        result = []
        for fname, fr in sorted(filter_rows_dict.items(), key=lambda x: x[1]["frame_count"], reverse=True):
            result.append(EquipmentFilterMetrics(
                filter_name=fname,
                frame_count=fr["frame_count"],
                total_integration_seconds=fr["total_seconds"],
                median_hfr=weighted_median_approx(fr["hfr_vals"]),
                best_hfr=safe_round(fr["best_hfr"]),
                median_eccentricity=weighted_median_approx(fr["ecc_vals"]),
                median_fwhm=weighted_median_approx(fr["fwhm_vals"]),
            ))
        return result

    equipment_performance = []
    for (tel, cam), cd in sorted(combo_data.items(), key=lambda x: x[1]["frame_count"], reverse=True):
        mad_row = mad_by_combo.get((tel, cam))
        equipment_performance.append(EquipmentComboMetrics(
            telescope=tel,
            camera=cam,
            frame_count=cd["frame_count"],
            total_integration_seconds=cd["total_seconds"],
            avg_session_seconds=(cd["total_seconds"] / len(cd["sessions"])) if cd["sessions"] else None,
            median_hfr=weighted_median_approx(cd["hfr_vals"]),
            best_hfr=safe_round(cd["best_hfr"]),
            median_eccentricity=weighted_median_approx(cd["ecc_vals"]),
            median_fwhm=weighted_median_approx(cd["fwhm_vals"]),
            mad_hfr=combo_mad(mad_row.mad_hfr if mad_row else None),
            mad_eccentricity=combo_mad(mad_row.mad_ecc if mad_row else None),
            mad_fwhm=combo_mad(mad_row.mad_fwhm if mad_row else None),
            grouped=len(cd["raw_telescopes"]) > 1 or len(cd["raw_cameras"]) > 1,
            filters=sorted(cd["filters"]),
            filter_breakdown=build_filter_metrics(cd["filter_rows"]),
        ))

    # Filter usage
    raw_filter_usage = {r[0]: float(r[1]) for r in filter_rows if r[0]}
    normalized_usage: dict[str, float] = {}
    for name, seconds in raw_filter_usage.items():
        canonical = normalize_filter(name, filter_map) or name
        normalized_usage[canonical] = normalized_usage.get(canonical, 0.0) + seconds
    filter_usage = normalized_usage

    # Timeline - monthly
    timeline = [TimelineEntry(month=r[0], integration_seconds=float(r[1])) for r in monthly_rows]

    # Timeline - weekly / daily raw
    weekly_raw = [(r[0], float(r[1])) for r in weekly_rows]
    daily_raw = [(r[0], float(r[1])) for r in daily_rows]

    # Top targets
    top_targets = [TopTarget(name=r[0], integration_seconds=float(r[1])) for r in top_rows]

    # Data quality
    (
        avg_hfr, avg_ecc, best_hfr,
        avg_hfr_arcsec, best_hfr_arcsec, unscaled_frame_count,
    ) = quality_row

    bucket_ranges = [(0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 100)]
    hfr_buckets = []
    for i, (low, high) in enumerate(bucket_ranges):
        count = bucket_row[i] or 0
        if count > 0:
            label = f"{low:.1f}-{high:.1f}" if high < 100 else f"{low:.1f}+"
            hfr_buckets.append(HfrBucket(bucket=label, count=count))

    hfr_arcsec_buckets = []
    for i, (low, high) in enumerate(_HFR_ARCSEC_BUCKET_RANGES):
        count = (arcsec_bucket_row[i] if i < len(arcsec_bucket_row) else 0) or 0
        if count > 0:
            label = f"{low:.1f}-{high:.1f}" if high is not None else f"{low:.1f}+"
            hfr_arcsec_buckets.append(HfrBucket(bucket=label, count=count))

    # Eccentricity provenance: pool only the modal source (the three sources
    # measure eccentricity differently and are not interchangeable). Falls
    # back to the blind pooled average only when no per-source rows exist.
    ecc_excluded_count = None
    avg_ecc_final = round(float(avg_ecc), 2) if avg_ecc else None
    src_rows = [r for r in (ecc_source_rows or []) if r[1]]
    if src_rows:
        # Deterministic tie-break: highest count, then lexicographically
        # smallest source name (None source sorts last).
        modal = min(src_rows, key=lambda r: (-r[1], r[0] is None, r[0] or ""))
        total_ecc_frames = sum(r[1] for r in src_rows)
        ecc_excluded_count = total_ecc_frames - modal[1]
        avg_ecc_final = round(float(modal[2]), 2) if modal[2] is not None else None

    data_quality = DataQualityStats(
        avg_hfr=round(float(avg_hfr), 2) if avg_hfr else None,
        avg_eccentricity=avg_ecc_final,
        best_hfr=round(float(best_hfr), 2) if best_hfr else None,
        hfr_distribution=hfr_buckets,
        avg_hfr_arcsec=round(float(avg_hfr_arcsec), 2) if avg_hfr_arcsec else None,
        best_hfr_arcsec=round(float(best_hfr_arcsec), 2) if best_hfr_arcsec else None,
        unscaled_frame_count=int(unscaled_frame_count) if unscaled_frame_count is not None else None,
        hfr_arcsec_hist=hfr_arcsec_buckets,
        ecc_excluded_count=ecc_excluded_count,
    )

    # Storage
    storage = StorageStats(
        fits_bytes=fits_bytes,
        fits_disk_bytes=_storage_cache["fits"],
        thumbnail_bytes=_storage_cache["thumbnails"],
        database_bytes=db_bytes,
    )

    # Ingest history
    ingest_history = [
        IngestEntry(date=str(r[0]), files_added=r[1]) for r in ingest_rows
    ]

    # --- Dark hours lookup (depends on site_coords + daily_raw) ---
    from datetime import date as date_type, timedelta
    from app.models.site_dark_hours import SiteDarkHours
    import calendar as cal

    dark_map: dict[date_type, float] = {}
    if site_coords and daily_raw:
        min_date_str = daily_raw[0][0]
        max_date_str = daily_raw[-1][0]
        min_date_parts = min_date_str.split("-")
        max_date_parts = max_date_str.split("-")
        min_date = date_type(int(min_date_parts[0]), int(min_date_parts[1]), int(min_date_parts[2]))
        max_date = date_type(int(max_date_parts[0]), int(max_date_parts[1]), int(max_date_parts[2]))
        dark_q = select(SiteDarkHours.date, SiteDarkHours.dark_hours).where(
            SiteDarkHours.latitude == site_coords.latitude,
            SiteDarkHours.longitude == site_coords.longitude,
            SiteDarkHours.date >= min_date,
            SiteDarkHours.date <= max_date,
        )
        async with async_session() as s:
            dark_result = await s.execute(dark_q)
            dark_map = {row[0]: row[1] for row in dark_result.all()}

    def _eff_for_dates(dates: list[date_type], integration_secs: float) -> float | None:
        total_dark = sum(dark_map.get(d, 0.0) for d in dates)
        if total_dark > 0:
            return round((integration_secs / 3600) / total_dark * 100, 1)
        return None

    # Monthly
    timeline_monthly: list[TimelineDetailEntry] = []
    for entry in timeline:
        year, month = map(int, entry.month.split("-"))
        dates = [date_type(year, month, d) for d in range(1, cal.monthrange(year, month)[1] + 1)]
        timeline_monthly.append(TimelineDetailEntry(
            period=entry.month, integration_seconds=entry.integration_seconds,
            efficiency_pct=_eff_for_dates(dates, entry.integration_seconds),
        ))

    # Weekly
    timeline_weekly: list[TimelineDetailEntry] = []
    for period, secs in weekly_raw:
        parts = period.split("-W")
        year, week = int(parts[0]), int(parts[1])
        jan4 = date_type(year, 1, 4)
        start_of_week1 = jan4 - timedelta(days=jan4.weekday())
        monday = start_of_week1 + timedelta(weeks=week - 1)
        dates = [monday + timedelta(days=i) for i in range(7)]
        timeline_weekly.append(TimelineDetailEntry(
            period=period, integration_seconds=secs,
            efficiency_pct=_eff_for_dates(dates, secs),
        ))

    # Daily
    timeline_daily: list[TimelineDetailEntry] = []
    for period, secs in daily_raw:
        parts = period.split("-")
        d = date_type(int(parts[0]), int(parts[1]), int(parts[2]))
        dark_h = dark_map.get(d, 0.0)
        eff = round((secs / 3600) / dark_h * 100, 1) if dark_h > 0 else None
        timeline_daily.append(TimelineDetailEntry(
            period=period, integration_seconds=secs, efficiency_pct=eff,
        ))

    response = StatsResponse(
        overview=overview,
        equipment=equipment,
        equipment_performance=equipment_performance,
        filter_usage=filter_usage,
        timeline=timeline,
        timeline_monthly=timeline_monthly,
        timeline_weekly=timeline_weekly,
        timeline_daily=timeline_daily,
        site_coords=site_coords,
        top_targets=top_targets,
        data_quality=data_quality,
        storage=storage,
        ingest_history=ingest_history,
    )

    # Cache the computed response in Redis, but skip during the cold-start
    # window when the on-disk storage sizes are still 0 (see _should_cache_stats)
    # so we don't freeze a "0 on disk" response for the full TTL.
    if _should_cache_stats():
        try:
            async with async_redis() as r:
                await r.setex(_STATS_CACHE_KEY, _STATS_CACHE_TTL, response.model_dump_json())
        except Exception:
            logger.debug("Redis cache write failed for stats")

    return response


@router.get("/calendar", response_model=list[CalendarEntry])
async def get_calendar(
    year: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    # Grouped by distinct imaging night (session_date alone), not by rig -- see
    # the rig_session_count comment in _query_overview (AUD-019). A night with
    # two rigs is one calendar cell here, but two rig-sessions in the overview.
    date_col = Image.session_date
    q = (
        select(
            date_col.label("night"),
            func.sum(Image.exposure_time).label("integration"),
            func.count(func.distinct(Image.resolved_target_id)).label("targets"),
            func.count(Image.id).label("frames"),
        )
        .where(Image.image_type == "LIGHT")
        .where(Image.session_date.is_not(None))
        .group_by(date_col)
        .order_by(date_col)
    )
    if year:
        q = q.where(func.extract("year", Image.session_date) == year)
    else:
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=365)
        q = q.where(Image.capture_date >= cutoff)

    rows = (await session.execute(q)).all()
    return [
        CalendarEntry(
            date=str(r.night),
            integration_seconds=r.integration or 0,
            target_count=r.targets,
            frame_count=r.frames,
        )
        for r in rows
    ]
