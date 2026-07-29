"""View-layer normalization: maps aliases to canonical names.

Does NOT mutate stored data - applied at query time only.
"""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Alias map cache
#
# load_alias_maps() is called several times per request (dashboard, stats,
# analysis, etc.) and hit the user_settings table on every call. The settings
# row changes rarely, so we cache the derived maps in-process with a short TTL.
#
# Single-process asyncio: a plain module-level variable is sufficient (no
# cross-thread mutation). The cache is invalidated explicitly when settings
# that affect aliases are written (see invalidate_alias_cache), so the TTL is
# only a backstop for any write path that forgets to invalidate.
# ---------------------------------------------------------------------------
_ALIAS_CACHE_TTL_SECONDS = 30.0
_alias_cache: tuple[dict[str, str], dict[str, str], dict[str, str]] | None = None
_alias_cache_ts: float = 0.0


def invalidate_alias_cache() -> None:
    """Clear the cached alias maps. Call after writing alias-affecting settings."""
    global _alias_cache, _alias_cache_ts
    _alias_cache = None
    _alias_cache_ts = 0.0


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


def equipment_match_set(names, alias_map: dict[str, str]) -> set[str]:
    """Every stored string that could name one of these pieces of equipment.

    Folding alias to canonical is one-sided and is not enough on its own when
    both sides of a comparison are user data written at different times. The
    PHD2 profile map is the live example: a profile mapped before the rig was
    grouped stores the raw name, grouping it afterwards never rewrites that
    map, and a fold-only comparison then misses in the opposite direction from
    the one it was added to fix. Normalizing and then expanding covers both:
    the result holds the canonical name and every alias of it, whichever form
    the caller supplied and whichever form was stored.
    """
    matches: set[str] = set()
    for name in names:
        if not name:
            continue
        canonical = normalize_equipment(name, alias_map) or name
        matches.update(expand_canonical(canonical, alias_map))
    return matches


async def load_telescope_match_set(session: AsyncSession, names) -> set[str]:
    """equipment_match_set for telescopes, against the stored alias map."""
    _, _, tel_map = await load_alias_maps(session)
    return equipment_match_set(names, tel_map)


async def load_alias_maps(session: AsyncSession) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Load filter, camera, and telescope alias maps from settings DB.

    Returns:
        (filter_alias_map, camera_alias_map, telescope_alias_map)

    Results are cached in-process for a short TTL and explicitly invalidated
    when alias-affecting settings are written (see invalidate_alias_cache).
    """
    global _alias_cache, _alias_cache_ts

    now = time.monotonic()
    if _alias_cache is not None and (now - _alias_cache_ts) < _ALIAS_CACHE_TTL_SECONDS:
        return _alias_cache

    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID

    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        maps: tuple[dict[str, str], dict[str, str], dict[str, str]] = ({}, {}, {})
    else:
        filter_map = build_alias_maps(row.filters or {})
        cam_map, tel_map = build_equipment_alias_maps(row.equipment or {})
        maps = (filter_map, cam_map, tel_map)

    _alias_cache = maps
    _alias_cache_ts = now
    return maps
