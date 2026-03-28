import asyncio
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Image, Target
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment
from app.schemas.stats import (
    StatsResponse, OverviewStats, EquipmentStats, EquipmentItem,
    TimelineEntry, TopTarget, DataQualityStats, HfrBucket,
    StorageStats, IngestEntry,
)

router = APIRouter(prefix="/stats", tags=["stats"])

# --- Storage size cache (expensive to compute, updated in background) ---
_storage_cache: dict[str, int] = {"fits": 0, "thumbnails": 0}
_storage_last_update: float = 0
_storage_lock = asyncio.Lock()
_STORAGE_TTL = 300  # refresh every 5 minutes


def _compute_dir_size(path: str) -> int:
    """Compute directory size using du (fast) with Python fallback."""
    p = Path(path)
    if not p.exists():
        return 0
    try:
        result = subprocess.run(
            ["du", "-sb", str(p)], capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    return 0


async def _refresh_storage_cache() -> None:
    """Refresh storage sizes in a background thread."""
    global _storage_last_update
    async with _storage_lock:
        if time.time() - _storage_last_update < _STORAGE_TTL:
            return  # another task already refreshed
        fits = await asyncio.to_thread(_compute_dir_size, settings.fits_data_path)
        thumbs = await asyncio.to_thread(_compute_dir_size, settings.thumbnails_path)
        _storage_cache["fits"] = fits
        _storage_cache["thumbnails"] = thumbs
        _storage_last_update = time.time()


@router.get("", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Return comprehensive database analytics for the admin page.

    Storage sizes are cached and refreshed in the background every 5 minutes.
    The first request after startup returns 0 for storage while du runs.
    """

    # Kick off storage refresh in background (non-blocking)
    if time.time() - _storage_last_update >= _STORAGE_TTL:
        asyncio.create_task(_refresh_storage_cache())

    # --- All DB queries below are fast (indexed) ---

    filter_map, cam_map, tel_map = await load_alias_maps(session)

    # Overview
    overview_q = select(
        func.coalesce(func.sum(Image.exposure_time), 0),
        func.count(func.distinct(Image.resolved_target_id)),
        func.count(Image.id),
    ).where(Image.image_type == "LIGHT")
    ov = await session.execute(overview_q)
    total_seconds, target_count, total_frames = ov.one()

    overview = OverviewStats(
        total_integration_seconds=float(total_seconds),
        target_count=target_count,
        total_frames=total_frames,
        disk_usage_bytes=_storage_cache["fits"] + _storage_cache["thumbnails"],
    )

    # Equipment
    cam_q = select(Image.camera, func.count(Image.id)).where(
        Image.camera.isnot(None)
    ).group_by(Image.camera).order_by(func.count(Image.id).desc())
    cam_result = await session.execute(cam_q)
    raw_cam_counts: dict[str, int] = {}
    for r in cam_result.all():
        canonical = normalize_equipment(r[0], cam_map) or r[0]
        raw_cam_counts[canonical] = raw_cam_counts.get(canonical, 0) + r[1]
    cameras = [EquipmentItem(name=name, frame_count=count) for name, count in sorted(raw_cam_counts.items(), key=lambda x: x[1], reverse=True)]

    tel_q = select(Image.telescope, func.count(Image.id)).where(
        Image.telescope.isnot(None)
    ).group_by(Image.telescope).order_by(func.count(Image.id).desc())
    tel_result = await session.execute(tel_q)
    raw_tel_counts: dict[str, int] = {}
    for r in tel_result.all():
        canonical = normalize_equipment(r[0], tel_map) or r[0]
        raw_tel_counts[canonical] = raw_tel_counts.get(canonical, 0) + r[1]
    telescopes = [EquipmentItem(name=name, frame_count=count) for name, count in sorted(raw_tel_counts.items(), key=lambda x: x[1], reverse=True)]

    equipment = EquipmentStats(cameras=cameras, telescopes=telescopes)

    # Filter usage (total seconds per optical filter)
    filter_q = select(
        Image.filter_used, func.coalesce(func.sum(Image.exposure_time), 0)
    ).where(
        Image.filter_used.isnot(None), Image.image_type == "LIGHT"
    ).group_by(Image.filter_used)
    filter_result = await session.execute(filter_q)
    raw_filter_usage = {r[0]: float(r[1]) for r in filter_result.all() if r[0]}
    normalized_usage: dict[str, float] = {}
    for name, seconds in raw_filter_usage.items():
        canonical = normalize_filter(name, filter_map) or name
        normalized_usage[canonical] = normalized_usage.get(canonical, 0.0) + seconds
    filter_usage = normalized_usage

    # Timeline (monthly integration)
    month_label = func.to_char(Image.capture_date, 'YYYY-MM').label('month')
    timeline_q = select(
        month_label,
        func.coalesce(func.sum(Image.exposure_time), 0),
    ).where(
        Image.capture_date.isnot(None), Image.image_type == "LIGHT"
    ).group_by(month_label).order_by(month_label)
    timeline_result = await session.execute(timeline_q)
    timeline = [TimelineEntry(month=r[0], integration_seconds=float(r[1])) for r in timeline_result.all()]

    # Top targets
    top_q = select(
        Target.primary_name, func.coalesce(func.sum(Image.exposure_time), 0)
    ).join(Target, Image.resolved_target_id == Target.id).where(
        Image.image_type == "LIGHT"
    ).group_by(Target.primary_name).order_by(
        func.sum(Image.exposure_time).desc()
    ).limit(20)
    top_result = await session.execute(top_q)
    top_targets = [TopTarget(name=r[0], integration_seconds=float(r[1])) for r in top_result.all()]

    # Data quality
    quality_q = select(
        func.avg(Image.median_hfr),
        func.avg(Image.eccentricity),
        func.min(Image.median_hfr),
    ).where(Image.image_type == "LIGHT")
    quality_result = await session.execute(quality_q)
    avg_hfr, avg_ecc, best_hfr = quality_result.one()

    # HFR distribution buckets (single query instead of N queries)
    hfr_buckets = []
    bucket_ranges = [(0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 100)]
    for low, high in bucket_ranges:
        bucket_q = select(func.count(Image.id)).where(
            Image.median_hfr >= low, Image.median_hfr < high, Image.image_type == "LIGHT"
        )
        br = await session.execute(bucket_q)
        count = br.scalar_one()
        if count > 0:
            label = f"{low:.1f}-{high:.1f}" if high < 100 else f"{low:.1f}+"
            hfr_buckets.append(HfrBucket(bucket=label, count=count))

    data_quality = DataQualityStats(
        avg_hfr=round(float(avg_hfr), 2) if avg_hfr else None,
        avg_eccentricity=round(float(avg_ecc), 2) if avg_ecc else None,
        best_hfr=round(float(best_hfr), 2) if best_hfr else None,
        hfr_distribution=hfr_buckets,
    )

    # Storage — use cached values (background task refreshes them)
    db_size_q = select(func.pg_database_size(func.current_database()))
    try:
        db_result = await session.execute(db_size_q)
        db_bytes = db_result.scalar_one()
    except Exception:
        db_bytes = 0

    storage = StorageStats(
        fits_bytes=_storage_cache["fits"],
        thumbnail_bytes=_storage_cache["thumbnails"],
        database_bytes=db_bytes,
    )

    # Ingest history (images grouped by capture date)
    capture_day = func.date(Image.capture_date).label('capture_day')
    ingest_q = select(
        capture_day, func.count(Image.id)
    ).where(
        Image.capture_date.isnot(None)
    ).group_by(capture_day).order_by(capture_day.desc()).limit(30)
    ingest_result = await session.execute(ingest_q)
    ingest_history = [
        IngestEntry(date=str(r[0]), files_added=r[1]) for r in ingest_result.all()
    ]

    return StatsResponse(
        overview=overview,
        equipment=equipment,
        filter_usage=filter_usage,
        timeline=timeline,
        top_targets=top_targets,
        data_quality=data_quality,
        storage=storage,
        ingest_history=ingest_history,
    )
