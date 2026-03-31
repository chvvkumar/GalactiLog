from enum import Enum

from fastapi import APIRouter, Depends
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import async_redis
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.models import Image
from app.schemas.settings import (
    GeneralSettings, FilterConfig, EquipmentConfig, EquipmentAliases,
    SettingsResponse, SuggestionsResponse, SuggestionGroup,
    DiscoveredItem, DiscoveredResponse,
    DisplaySettings, default_display_settings,
    GraphSettings, default_graph_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_settings(session: AsyncSession) -> UserSettings:
    result = await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(id=SETTINGS_ROW_ID)
        session.add(row)
        await session.flush()

    # One-time migration: copy auto-scan state from Redis if not yet migrated
    if not row.general or not row.general.get("_migrated"):
        async with async_redis() as r:
            enabled = await r.get("autoscan:enabled")
            interval = await r.get("autoscan:interval")
            if enabled is not None or interval is not None:
                row.general = {
                    **(row.general or {}),
                    "auto_scan_enabled": enabled == "true" if enabled else True,
                    "auto_scan_interval": int(interval) if interval else 240,
                    "_migrated": True,
                }
                await session.flush()

    return row


def _row_to_response(row: UserSettings) -> SettingsResponse:
    """Convert a UserSettings ORM row to a SettingsResponse schema."""
    general_data = row.general or {}
    filters_data = row.filters or {}
    equipment_data = row.equipment or {}

    general = GeneralSettings(**general_data)

    filters = {
        name: FilterConfig(**cfg)
        for name, cfg in filters_data.items()
    }

    eq_cameras = {
        name: EquipmentAliases(**aliases)
        for name, aliases in equipment_data.get("cameras", {}).items()
    }
    eq_telescopes = {
        name: EquipmentAliases(**aliases)
        for name, aliases in equipment_data.get("telescopes", {}).items()
    }
    equipment = EquipmentConfig(cameras=eq_cameras, telescopes=eq_telescopes)

    display = DisplaySettings(**row.display) if row.display else default_display_settings()
    graph = GraphSettings(**row.graph) if row.graph else default_graph_settings()

    return SettingsResponse(
        general=general,
        filters=filters,
        equipment=equipment,
        dismissed_suggestions=row.dismissed_suggestions or [],
        display=display,
        graph=graph,
    )


def _build_known_names(config: dict) -> set[str]:
    """Build a set of all canonical names and their aliases from a config dict."""
    known: set[str] = set()
    for canonical, conf in config.items():
        known.add(canonical)
        for alias in conf.get("aliases", []):
            known.add(alias)
    return known


def _group_already_merged(group: SuggestionGroup, known: set[str]) -> bool:
    """Return True if every member of the group is already a known name or alias."""
    return all(name in known for name in group.group)


def _group_is_dismissed(group: SuggestionGroup, dismissed: list[list[str]]) -> bool:
    """Return True if this suggestion group matches a dismissed entry."""
    sorted_group = sorted(group.group)
    return sorted_group in dismissed



def _normalize_for_comparison(name: str) -> str:
    """Normalize a name for comparison: lowercase, strip separators."""
    return name.lower().replace("_", "").replace("-", "").replace(" ", "")


def _are_similar(a: str, b: str) -> bool:
    """Determine if two equipment/filter names likely refer to the same thing.

    Uses three strategies (no edit distance — too many false positives
    with names like ASI533MC/ASI533MM or Askar40/Askar140):
    1. Case-insensitive exact match
    2. Normalized match (ignore underscores, spaces, hyphens)
    3. One name contains the other (e.g. "ZWO ASI533MM Pro (ASI533MM)" contains "ZWO ASI533MM Pro")
    """
    la, lb = a.lower(), b.lower()

    # Exact case-insensitive
    if la == lb:
        return True

    # Normalized match (strip separators)
    na, nb = _normalize_for_comparison(a), _normalize_for_comparison(b)
    if na == nb:
        return True

    # Containment: one is a substring of the other (min 4 chars to avoid short false matches)
    if len(la) >= 4 and len(lb) >= 4:
        if la in lb or lb in la:
            return True

    return False


def _group_by_similarity(rows: list[tuple[str, int]]) -> list[SuggestionGroup]:
    """
    Group names that likely refer to the same item using multiple similarity
    strategies (case, normalization, containment, edit distance).

    Returns only groups with 2+ members (singletons are not suggestions).
    """
    names = [r[0] for r in rows]
    counts = {r[0]: r[1] for r in rows}

    parent: dict[str, str] = {n: n for n in names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[py] = px

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if find(names[i]) != find(names[j]):
                if _are_similar(names[i], names[j]):
                    union(names[i], names[j])

    # Collect groups
    groups: dict[str, list[str]] = {}
    for name in names:
        root = find(name)
        groups.setdefault(root, []).append(name)

    result = []
    for members in groups.values():
        if len(members) >= 2:
            result.append(SuggestionGroup(
                group=sorted(members),
                counts={m: counts[m] for m in members},
            ))

    return result


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SettingsResponse)
async def get_settings(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return the full settings object, creating defaults if not yet present."""
    row = await _get_or_create_settings(session)
    return _row_to_response(row)


@router.put("/general", response_model=SettingsResponse)
async def update_general(
    payload: GeneralSettings,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update general settings and return the full settings object."""
    row = await _get_or_create_settings(session)
    row.general = {**payload.model_dump(), "_migrated": True}
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.put("/filters", response_model=SettingsResponse)
async def update_filters(
    payload: dict[str, FilterConfig],
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update filter config (colors + aliases) and return full settings."""
    row = await _get_or_create_settings(session)
    row.filters = {name: cfg.model_dump() for name, cfg in payload.items()}
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.put("/equipment", response_model=SettingsResponse)
async def update_equipment(
    payload: EquipmentConfig,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update equipment aliases and return full settings."""
    row = await _get_or_create_settings(session)
    row.equipment = payload.model_dump()
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.put("/dismissed-suggestions", response_model=SettingsResponse)
async def update_dismissed_suggestions(
    payload: list[list[str]],
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update dismissed suggestions list and return full settings."""
    row = await _get_or_create_settings(session)
    # Normalize: sort each inner list for consistent deduplication
    row.dismissed_suggestions = [sorted(group) for group in payload]
    await session.commit()
    await session.refresh(row)
    return _row_to_response(row)


@router.put("/display", response_model=SettingsResponse)
async def update_display(
    payload: DisplaySettings,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    row = await _get_or_create_settings(session)
    row.display = payload.model_dump()
    await session.commit()
    return _row_to_response(row)


@router.put("/graph", response_model=SettingsResponse)
async def update_graph(
    payload: GraphSettings,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    row = await _get_or_create_settings(session)
    row.graph = payload.model_dump()
    await session.commit()
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# Discovered endpoints
# ---------------------------------------------------------------------------

class DiscoveredSection(str, Enum):
    filters = "filters"
    cameras = "cameras"
    telescopes = "telescopes"


@router.get("/discovered/{section}", response_model=DiscoveredResponse)
async def get_discovered(
    section: DiscoveredSection,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return all distinct raw values from DB with frame counts for a section."""
    column_map = {
        DiscoveredSection.filters: Image.filter_used,
        DiscoveredSection.cameras: Image.camera,
        DiscoveredSection.telescopes: Image.telescope,
    }
    column = column_map[section]
    q = (
        select(column, sa_func.count(Image.id))
        .where(column.isnot(None))
        .group_by(column)
        .order_by(sa_func.count(Image.id).desc())
    )
    result = await session.execute(q)
    rows = result.all()
    return DiscoveredResponse(
        items=[DiscoveredItem(name=name, count=count) for name, count in rows]
    )


# ---------------------------------------------------------------------------
# Suggestions endpoints
# ---------------------------------------------------------------------------

@router.get("/suggestions/filters", response_model=SuggestionsResponse)
async def suggest_filters(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return groups of similar filter names found in the image library."""
    q = (
        select(Image.filter_used, sa_func.count(Image.id))
        .where(Image.filter_used.isnot(None))
        .group_by(Image.filter_used)
    )
    result = await session.execute(q)
    rows = result.all()  # list of (name, count)
    suggestions = _group_by_similarity(rows)
    for s in suggestions:
        s.section = "filters"

    # Exclude groups already handled by saved aliases or dismissed
    row = await _get_or_create_settings(session)
    known = _build_known_names(row.filters or {})
    dismissed = row.dismissed_suggestions or []
    suggestions = [
        s for s in suggestions
        if not _group_already_merged(s, known) and not _group_is_dismissed(s, dismissed)
    ]

    return SuggestionsResponse(suggestions=suggestions)


@router.get("/suggestions/equipment", response_model=SuggestionsResponse)
async def suggest_equipment(session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    """Return groups of similar camera/telescope names found in the image library."""
    cam_q = (
        select(Image.camera, sa_func.count(Image.id))
        .where(Image.camera.isnot(None))
        .group_by(Image.camera)
    )
    cam_result = await session.execute(cam_q)
    camera_rows = cam_result.all()

    tel_q = (
        select(Image.telescope, sa_func.count(Image.id))
        .where(Image.telescope.isnot(None))
        .group_by(Image.telescope)
    )
    tel_result = await session.execute(tel_q)
    telescope_rows = tel_result.all()

    cam_suggestions = _group_by_similarity(camera_rows)
    for s in cam_suggestions:
        s.section = "cameras"
    tel_suggestions = _group_by_similarity(telescope_rows)
    for s in tel_suggestions:
        s.section = "telescopes"
    all_suggestions = cam_suggestions + tel_suggestions

    # Exclude groups already handled by saved aliases or dismissed
    row = await _get_or_create_settings(session)
    eq = row.equipment or {}
    known = set()
    for section in ("cameras", "telescopes"):
        known |= _build_known_names(eq.get(section, {}))
    dismissed = row.dismissed_suggestions or []
    all_suggestions = [
        s for s in all_suggestions
        if not _group_already_merged(s, known) and not _group_is_dismissed(s, dismissed)
    ]

    return SuggestionsResponse(suggestions=all_suggestions)
