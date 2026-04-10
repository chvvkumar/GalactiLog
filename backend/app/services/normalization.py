"""View-layer normalization: maps aliases to canonical names.

Does NOT mutate stored data - applied at query time only.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def build_alias_maps(filters_config: dict) -> dict[str, str]:
    """Build alias -> canonical map from filters JSONB.

    Args:
        filters_config: e.g. {"OIII": {"color": "#3498db", "aliases": ["Oiii", "O"]}}

    Returns:
        Dict mapping each alias to its canonical name.
    """
    alias_map: dict[str, str] = {}
    for canonical, conf in filters_config.items():
        for alias in conf.get("aliases", []):
            alias_map[alias] = canonical
    return alias_map


def build_equipment_alias_maps(
    equipment_config: dict,
) -> tuple[dict[str, str], dict[str, str]]:
    """Build camera and telescope alias maps from equipment JSONB.

    Returns:
        (camera_alias_map, telescope_alias_map)
    """
    cam_map: dict[str, str] = {}
    for canonical, conf in equipment_config.get("cameras", {}).items():
        for alias in conf.get("aliases", []):
            cam_map[alias] = canonical
    tel_map: dict[str, str] = {}
    for canonical, conf in equipment_config.get("telescopes", {}).items():
        for alias in conf.get("aliases", []):
            tel_map[alias] = canonical
    return cam_map, tel_map


def normalize_filter(value: str | None, alias_map: dict[str, str]) -> str | None:
    """Map a filter name to its canonical form, or return as-is."""
    if value is None:
        return None
    return alias_map.get(value, value)


def normalize_equipment(value: str | None, alias_map: dict[str, str]) -> str | None:
    """Map an equipment name to its canonical form, or return as-is."""
    if value is None:
        return None
    return alias_map.get(value, value)


def expand_canonical(canonical: str, alias_map: dict[str, str]) -> list[str]:
    """Return all raw names that map to `canonical` (including canonical itself).

    Used for query-time expansion: when filtering by canonical name,
    match all raw DB values that alias to it.
    """
    names = [canonical]
    for alias, canon in alias_map.items():
        if canon == canonical:
            names.append(alias)
    return names


async def load_alias_maps(session: AsyncSession) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Load filter, camera, and telescope alias maps from settings DB.

    Returns:
        (filter_alias_map, camera_alias_map, telescope_alias_map)
    """
    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID

    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}, {}, {}

    filter_map = build_alias_maps(row.filters or {})
    cam_map, tel_map = build_equipment_alias_maps(row.equipment or {})
    return filter_map, cam_map, tel_map
