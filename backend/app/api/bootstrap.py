import asyncio
import json
import logging
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.config import async_redis
from app.models.user import User
from app.models import Target, Image
from app.models.custom_column import CustomColumn
from app.services.normalization import load_alias_maps, normalize_equipment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])

_FITS_KEYS_CACHE_KEY = "galactilog:fits_keys"
_FITS_KEYS_CACHE_TTL = 3600


async def _fetch_settings(session: AsyncSession) -> dict:
    from app.api.settings import _get_or_create_settings, _row_to_response
    row = await _get_or_create_settings(session)
    return _row_to_response(row).model_dump()


async def _fetch_equipment(session: AsyncSession) -> dict:
    _, cam_map, tel_map = await load_alias_maps(session)

    cam_result = await session.execute(
        select(Image.camera).where(Image.camera.isnot(None)).distinct().order_by(Image.camera)
    )
    tel_result = await session.execute(
        select(Image.telescope).where(Image.telescope.isnot(None)).distinct().order_by(Image.telescope)
    )
    raw_cameras = [r[0] for r in cam_result.all() if r[0]]
    raw_telescopes = [r[0] for r in tel_result.all() if r[0]]

    cam_canonical: dict[str, set[str]] = {}
    for c in raw_cameras:
        canonical = normalize_equipment(c, cam_map) or c
        cam_canonical.setdefault(canonical, set()).add(c)
    tel_canonical: dict[str, set[str]] = {}
    for t in raw_telescopes:
        canonical = normalize_equipment(t, tel_map) or t
        tel_canonical.setdefault(canonical, set()).add(t)

    cameras = [{"name": name, "grouped": len(raw) > 1} for name, raw in sorted(cam_canonical.items())]
    telescopes = [{"name": name, "grouped": len(raw) > 1} for name, raw in sorted(tel_canonical.items())]
    return {"cameras": cameras, "telescopes": telescopes}


async def _fetch_fits_keys(session: AsyncSession) -> list[str]:
    try:
        async with async_redis() as r:
            cached = await r.get(_FITS_KEYS_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        logger.debug("Redis cache read failed for fits-keys in bootstrap, computing fresh")

    result = await session.execute(
        text("SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers) AS key ORDER BY key")
    )
    keys = [row[0] for row in result.all()]

    try:
        async with async_redis() as r:
            await r.setex(_FITS_KEYS_CACHE_KEY, _FITS_KEYS_CACHE_TTL, json.dumps(keys))
    except Exception:
        logger.debug("Redis cache write failed for fits-keys in bootstrap")

    return keys


async def _fetch_object_types(session: AsyncSession) -> list[dict]:
    from app.api.targets import _categorize_object_type as _cat
    query = (
        select(Target.object_type, func.count(Target.id).label("count"))
        .where(
            Target.object_type.isnot(None),
            Target.merged_into_id.is_(None),
        )
        .group_by(Target.object_type)
    )
    result = await session.execute(query)

    category_counts: dict[str, int] = defaultdict(int)
    for raw_type, count in result.all():
        category = _cat(raw_type)
        category_counts[category] += count

    return sorted(
        [{"object_type": cat, "count": cnt} for cat, cnt in category_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


async def _fetch_custom_columns(session: AsyncSession) -> list[dict]:
    q = select(CustomColumn).order_by(CustomColumn.display_order, CustomColumn.created_at)
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "slug": r.slug,
            "column_type": r.column_type.value,
            "applies_to": r.applies_to.value,
            "dropdown_options": r.dropdown_options,
            "display_order": r.display_order,
            "created_by": str(r.created_by),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("")
async def get_bootstrap(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all data needed to initialize the SPA in a single request."""
    settings_data, equipment_data, fits_keys_data, object_types_data, custom_columns_data = await asyncio.gather(
        _fetch_settings(session),
        _fetch_equipment(session),
        _fetch_fits_keys(session),
        _fetch_object_types(session),
        _fetch_custom_columns(session),
    )

    return {
        "user": {
            "id": str(current_user.id),
            "username": current_user.username,
            "role": current_user.role.value,
        },
        "settings": settings_data,
        "equipment": equipment_data,
        "fits_keys": fits_keys_data,
        "object_types": object_types_data,
        "custom_columns": custom_columns_data,
    }
