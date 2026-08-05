import copy
import uuid
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes

from app.config import async_redis
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.models import Image
from app.services import phd2_profiles
from app.services.normalization import load_alias_maps, normalize_filter, normalize_equipment, invalidate_alias_cache
from app.schemas.settings import (
    GeneralSettings, FilterConfig, EquipmentConfig, EquipmentAliases,
    SettingsResponse, SuggestionsResponse, SuggestionGroup,
    DiscoveredItem, DiscoveredResponse,
    DisplaySettings, default_display_settings,
    GraphSettings, default_graph_settings,
    ColumnVisibility,
    ActivitySettingsResponse, ActivitySettingsUpdate,
)
from app.services.activity import emit

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


def _queue_worker_task(name: str, **kwargs) -> None:
    """Queue a Celery task by name, tolerating a run with no worker.

    The import is deferred and every failure swallowed because the API process
    serves fine without a broker in dev; a settings save must not fail because
    the follow-up pass could not be enqueued.
    """
    try:
        from importlib import import_module

        getattr(import_module("app.worker.tasks"), name).delay(**kwargs)
    except Exception:
        pass  # Worker may not be available in dev


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

    display_data = {k: v for k, v in (row.display or {}).items() if k != "column_visibility_per_user"}
    display = DisplaySettings(**display_data) if display_data else default_display_settings()
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

    Uses three strategies (no edit distance - too many false positives
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
    old_general = row.general or {}
    new_values = payload.model_dump()
    row.general = {
        **old_general,
        **new_values,
        "_migrated": True,
    }
    await session.commit()
    await session.refresh(row)

    # The stored profile map may be in the legacy `{"Rig": "Scope"}` form while
    # the payload always arrives canonical, so every comparison below is made
    # against the normalized stored value. Comparing the raw stored dict would
    # report a change on every single save.
    old_map = phd2_profiles.normalize_profile_map(old_general.get("phd2_profile_map"))
    new_map = new_values.get("phd2_profile_map") or {}
    old_comparable = {**old_general, "phd2_profile_map": old_map}

    # Emit a curated event listing which keys changed (no secrets in GeneralSettings).
    changed_keys = [k for k, v in new_values.items() if old_comparable.get(k) != v]
    if changed_keys:
        await emit(
            session, category="user_action", severity="info",
            event_type="settings_changed",
            message=f"Settings updated: {', '.join(changed_keys)}",
            details={"keys": changed_keys}, actor=user.username,
        )

    # One profile map now carries three kinds of change with three very
    # different costs, so the follow-up work is decided per kind rather than on
    # the map as a whole. Each answer is the RESOLVED one: a profile's own
    # value when it has one and the global value otherwise, so editing the
    # global setting moves every rig that inherits it and leaves the rest
    # alone. `None` stands for a log section that names no profile at all.
    profiles: set[str | None] = {None, *old_map, *new_map}

    old_zone = phd2_profiles.profile_zone_resolver(
        old_map, old_general.get("observer_timezone", "")
    )
    new_zone = phd2_profiles.profile_zone_resolver(new_map, payload.observer_timezone)
    zone_changed = any(old_zone(p) != new_zone(p) for p in profiles)

    old_longitude = phd2_profiles.longitude_resolver(
        old_map, old_general.get("observer_longitude")
    )
    new_longitude = phd2_profiles.longitude_resolver(new_map, payload.observer_longitude)
    longitude_changed = any(old_longitude(p) != new_longitude(p) for p in profiles)

    telescopes_changed = (
        phd2_profiles.telescope_map(old_map) != phd2_profiles.telescope_map(new_map)
    )
    night_changed = (
        old_general.get("use_imaging_night", False) != payload.use_imaging_night
    )

    if zone_changed:
        # A zone cannot be re-keyed in place: ended_at_utc has no stored local
        # counterpart, so it has to be applied while parsing. PHD2 never
        # rewrites a closed log, so the scan's size/mtime short-circuit would
        # skip every file forever without the force flag.
        #
        # This one pass re-parses, re-applies the profile map and re-keys every
        # stored session, so it already does the work of both passes below.
        # They are deliberately not queued alongside it: two of them writing
        # session_date from a single save would race each other.
        #
        # KNOWN GAP: a save that changes a zone AND toggles the night boundary
        # or moves a longitude leaves the IMAGE side of the recompute undone,
        # because the forced pass only touches guiding rows. Changing one
        # setting at a time is unaffected; chaining the two passes is the fix
        # and it belongs in the worker, not here.
        _queue_worker_task("scan_phd2_logs", force=True)
    else:
        if telescopes_changed:
            # Which telescope a profile belongs to is a setting, not a property
            # of the log, so this edit takes effect without re-reading a file.
            _queue_worker_task("scan_phd2_logs", remap_only=True)
        if night_changed or (payload.use_imaging_night and longitude_changed):
            # Longitude decides where a night breaks, for images from their own
            # headers and for guiding rows from the rig's own site.
            _queue_worker_task("recompute_session_dates")

    return _row_to_response(row)


def _activity_settings_payload(general: dict) -> dict:
    """Build the activity-settings response dict from a stored general dict."""
    return {
        "activity_retention_days": int(general.get("activity_retention_days", 90)),
        "app_log_capture_level": general.get("app_log_capture_level", "warning"),
        "app_log_retention_days": int(general.get("app_log_retention_days", 14)),
        "app_log_max_rows": int(general.get("app_log_max_rows", 50000)),
    }


@router.get("/activity", response_model=ActivitySettingsResponse)
async def get_activity_settings(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return activity-event and application-log retention/capture settings."""
    row = await _get_or_create_settings(session)
    return _activity_settings_payload(row.general or {})


@router.put("/activity", response_model=ActivitySettingsResponse)
async def update_activity_settings(
    payload: ActivitySettingsUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Update activity-event and application-log retention/capture settings.

    Accepts the legacy ``retention_days`` key (activity retention) as well as
    the explicit field names. On a capture-level change the Redis key is updated
    so log handlers in every process pick it up without a DB read.
    """
    row = await _get_or_create_settings(session)
    old_general = dict(row.general or {})

    changed: dict = {}
    # Activity retention: accept either key, prefer the explicit one.
    if payload.activity_retention_days is not None:
        changed["activity_retention_days"] = payload.activity_retention_days
    elif payload.retention_days is not None:
        changed["activity_retention_days"] = payload.retention_days
    if payload.app_log_capture_level is not None:
        changed["app_log_capture_level"] = payload.app_log_capture_level
    if payload.app_log_retention_days is not None:
        changed["app_log_retention_days"] = payload.app_log_retention_days
    if payload.app_log_max_rows is not None:
        changed["app_log_max_rows"] = payload.app_log_max_rows

    row.general = {**old_general, **changed, "_migrated": True}
    await session.commit()
    await session.refresh(row)

    # Mirror capture level so log handlers in all processes see it without a DB read.
    if "app_log_capture_level" in changed:
        try:
            from app.services.log_capture import CAPTURE_LEVEL_KEY
            async with async_redis() as r:
                await r.set(CAPTURE_LEVEL_KEY, changed["app_log_capture_level"])
        except Exception:
            pass

    # Emit a curated event listing the changed keys (no secrets here).
    changed_keys = [k for k in changed if old_general.get(k) != changed[k]]
    if changed_keys:
        await emit(
            session, category="user_action", severity="info",
            event_type="settings_changed",
            message=f"Activity settings updated: {', '.join(changed_keys)}",
            details={"keys": changed_keys}, actor=user.username,
        )

    return _activity_settings_payload(row.general)


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
    invalidate_alias_cache()
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
    invalidate_alias_cache()

    # Grouping two telescope names together turns one of them into an alias.
    # The PHD2 profile map's values are telescope names the user picked when
    # they mapped each profile, and nothing has ever rewritten them, so a
    # grouping made afterwards strands the map pointing at an alias. Reads
    # tolerate that through normalization.equipment_match_set; the per-image
    # guiding correlation does not, because it attributes on the value stored
    # on the session row. Fold the map onto the new canonical names here,
    # while the change that caused the drift is being saved.
    general = dict(row.general or {})
    profile_map = general.get("phd2_profile_map") or {}
    if profile_map:
        from app.services.normalization import (
            build_equipment_alias_maps, normalize_equipment,
        )

        _, tel_map = build_equipment_alias_maps(row.equipment or {})
        # Only the telescope of each entry moves. An entry's timezone and site
        # are not equipment and must survive a regrouping untouched, so the
        # rewrite goes through the shape owner rather than rebuilding the map
        # from bare names, which would flatten a configured rig back to the
        # legacy form and silently discard the zone its logs are read in.
        corrected = phd2_profiles.rewrite_telescopes(
            profile_map, lambda name: normalize_equipment(name, tel_map)
        )
        # Against the NORMALIZED stored map, never the raw one: a legacy map
        # always differs from its canonical form, so comparing against what is
        # stored would report a move on every equipment save.
        if corrected != phd2_profiles.normalize_profile_map(profile_map):
            row.general = {**general, "phd2_profile_map": corrected}
            await session.commit()
            await session.refresh(row)
            # The re-key rewrites every stored guiding session, so it is only
            # worth queueing when the map actually moved. A telescope is all
            # that moved here, so the cheap in-place pass covers it.
            _queue_worker_task("scan_phd2_logs", remap_only=True)

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
    existing = dict(row.display) if row.display else {}
    updated = payload.model_dump()
    # Preserve per-user column visibility when updating display settings
    if "column_visibility_per_user" in existing:
        updated["column_visibility_per_user"] = existing["column_visibility_per_user"]
    row.display = updated
    attributes.flag_modified(row, "display")
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
    """Return all distinct values from DB with frame counts for a section.

    For filters/cameras/telescopes, raw DB values are normalized through
    the user-configured alias maps so that e.g. "Ha" and "ha" are merged
    into a single canonical entry.
    """
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

    filter_map, cam_map, tel_map = await load_alias_maps(session)
    normalize_map = {
        DiscoveredSection.filters: lambda n: normalize_filter(n, filter_map),
        DiscoveredSection.cameras: lambda n: normalize_equipment(n, cam_map),
        DiscoveredSection.telescopes: lambda n: normalize_equipment(n, tel_map),
    }
    normalize = normalize_map[section]

    # Merge counts for names that normalize to the same canonical form
    merged: dict[str, int] = {}
    for name, count in rows:
        canonical = normalize(name) or name
        merged[canonical] = merged.get(canonical, 0) + count

    items = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    return DiscoveredResponse(
        items=[DiscoveredItem(name=name, count=count) for name, count in items]
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


# ---------------------------------------------------------------------------
# Column visibility endpoints
# ---------------------------------------------------------------------------

@router.get("/column-visibility/{user_id}")
async def get_column_visibility(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    row = await _get_or_create_settings(session)
    all_vis = (row.display or {}).get("column_visibility_per_user", {})
    user_vis = all_vis.get(str(user_id), {})
    return user_vis


@router.put("/column-visibility")
async def update_column_visibility(
    payload: ColumnVisibility,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    row = await _get_or_create_settings(session)
    display = copy.deepcopy(row.display) if row.display else {}
    per_user = display.get("column_visibility_per_user", {})
    per_user[str(user.id)] = payload.model_dump()
    display["column_visibility_per_user"] = per_user
    row.display = display
    attributes.flag_modified(row, "display")
    await session.commit()
    return {"ok": True}
