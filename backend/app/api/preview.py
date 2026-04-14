import hashlib
import logging
import uuid as _uuid
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_sync_redis, settings
from app.database import get_session
from app.models import Image, UserSettings, SETTINGS_ROW_ID
from app.schemas.settings import GeneralSettings
from app.services.preview import generate_preview
from app.services.preview_cache import PreviewCache
from app.services.scanner import CALIBRATION_FRAME_TYPES
from app.services.thumbnail import generate_thumbnail
from app.services.xisf_parser import generate_xisf_thumbnail

router = APIRouter(prefix="/preview", tags=["preview"])
logger = logging.getLogger(__name__)


@router.get("/{image_id}")
async def get_preview(
    image_id: UUID,
    resolution: int = Query(..., ge=0, le=20000),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Serve a high-resolution preview JPEG for an image.

    Caches rendered JPEGs in a Redis-tracked LRU on disk. Returns
    X-Accel-Redirect so nginx streams the cached file directly.
    """
    result = await session.execute(select(Image).where(Image.id == image_id))
    image = result.scalar_one_or_none()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")

    fits_path = Path(image.file_path)
    if not fits_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Load user settings for cache cap
    settings_row = (
        await session.execute(select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID))
    ).scalar_one_or_none()
    general = GeneralSettings(**(settings_row.general if settings_row and settings_row.general else {}))
    cap_bytes = max(general.preview_cache_mb, 100) * 1024 * 1024

    previews_dir = Path(settings.previews_path)
    previews_dir.mkdir(parents=True, exist_ok=True)

    cache_key = f"{image_id}_{resolution}.jpg"
    redis = get_sync_redis()
    try:
        cache = PreviewCache(redis, previews_dir, cap_bytes)

        cached_path = previews_dir / cache_key
        if cache.has(cache_key) and cached_path.exists():
            cache.touch(cache_key)
            return _redirect_response(cache_key, cached_path)

        image_type = (image.image_type or "").upper()
        is_calibration = image_type in CALIBRATION_FRAME_TYPES

        # Missing-thumbnail fallback for light frames only
        if not is_calibration and not image.thumbnail_path:
            try:
                path_hash = hashlib.md5(str(fits_path).encode()).hexdigest()[:12]
                thumb_filename = f"{fits_path.stem}_{path_hash}.jpg"
                thumb_path = Path(settings.thumbnails_path) / thumb_filename
                is_xisf = fits_path.suffix.lower() == ".xisf"
                if is_xisf:
                    generate_xisf_thumbnail(fits_path, thumb_path, max_width=settings.thumbnail_max_width)
                else:
                    generate_thumbnail(fits_path, thumb_path, max_width=settings.thumbnail_max_width)
                image.thumbnail_path = str(thumb_path)
                await session.commit()
            except Exception as exc:
                logger.warning("Thumbnail fallback failed for %s: %s", image_id, exc)

        # Render preview to temp file, then atomically move into cache directory
        temp_path = previews_dir / f".{cache_key}.{_uuid.uuid4().hex[:8]}.tmp"
        try:
            generate_preview(fits_path, temp_path, max_width=resolution)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Preview render failed: {exc}")

        size = temp_path.stat().st_size
        temp_path.replace(cached_path)
        cache.record(cache_key, size)

        return _redirect_response(cache_key, cached_path)
    finally:
        redis.close()


def _redirect_response(cache_key: str, cached_path: Path) -> FileResponse:
    return FileResponse(
        path=cached_path,
        media_type="image/jpeg",
        headers={
            "X-Accel-Redirect": f"/_previews_internal/{cache_key}",
            "Cache-Control": "public, max-age=86400",
        },
    )
