import asyncio
import logging
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text

from app.database import async_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models import Target, Image
from app.models.custom_column import CustomColumn
from app.services.normalization import load_alias_maps, normalize_equipment
from app.services.cache import cached_json
from app.schemas.bootstrap import BootstrapResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])

_FITS_KEYS_CACHE_KEY = "galactilog:fits_keys"
_FITS_KEYS_CACHE_TTL = 3600


async def _fetch_settings() -> dict:
    from app.api.settings import _get_or_create_settings, _row_to_response
    async with async_session() as session:
        row = await _get_or_create_settings(session)
        return _row_to_response(row).model_dump()


async def _fetch_equipment() -> dict:
    async with async_session() as session:
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


async def _fetch_fits_keys() -> list[str]:
    async def _compute():
        async with async_session() as session:
            result = await session.execute(
                text("SELECT DISTINCT key FROM images, jsonb_object_keys(raw_headers) AS key ORDER BY key")
            )
            return [row[0] for row in result.all()]

    return await cached_json(_FITS_KEYS_CACHE_KEY, _FITS_KEYS_CACHE_TTL, _compute)


async def _fetch_object_types() -> list[dict]:
    from app.api.targets import _categorize_object_type as _cat
    query = (
        select(Target.object_type, func.count(Target.id).label("count"))
        .where(
            Target.object_type.isnot(None),
            Target.merged_into_id.is_(None),
        )
        .group_by(Target.object_type)
    )
    async with async_session() as session:
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


async def _fetch_custom_columns() -> list[dict]:
    q = select(CustomColumn).order_by(CustomColumn.display_order, CustomColumn.created_at)
    async with async_session() as session:
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


@router.get("", response_model=BootstrapResponse)
async def get_bootstrap(
    current_user: User = Depends(get_current_user),
):
    """Return all data needed to initialize the SPA in a single request."""
    settings_data, equipment_data, fits_keys_data, object_types_data, custom_columns_data = await asyncio.gather(
        _fetch_settings(),
        _fetch_equipment(),
        _fetch_fits_keys(),
        _fetch_object_types(),
        _fetch_custom_columns(),
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
