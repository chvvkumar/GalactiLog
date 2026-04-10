from __future__ import annotations

"""Export/restore user customizations as portable versioned JSON backups."""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.models.session_note import SessionNote
from app.models.custom_column import CustomColumn
from app.models.target import Target
from app.models.mosaic import Mosaic
from app.models.user import User

CURRENT_BACKUP_SCHEMA_VERSION = 1
APP_VERSION = "0.1.0"

# ── Schema migrations ────────────────────────────────────────────────
# Each key is the version to migrate FROM. The function transforms the
# backup dict in-place and returns it.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def apply_migrations(data: dict) -> dict:
    """Apply schema migrations sequentially from data's schema_version to current.

    Migrations should transform the backup dict and return it (either in-place
    or as a new dict). Raises ValueError if the backup's schema is newer than
    this app supports, or if a migration step is missing from MIGRATIONS.
    """
    version = data["meta"]["schema_version"]
    if version > CURRENT_BACKUP_SCHEMA_VERSION:
        raise ValueError(
            f"Backup was created by a newer app version (schema v{version}). "
            f"This app supports up to schema v{CURRENT_BACKUP_SCHEMA_VERSION}. "
            f"Please upgrade the app before restoring this backup."
        )
    while version < CURRENT_BACKUP_SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise ValueError(f"No migration path from schema v{version}")
        data = MIGRATIONS[version](data)
        version += 1
        data["meta"]["schema_version"] = version
    return data


# ── Export ────────────────────────────────────────────────────────────


async def export_backup(session: AsyncSession) -> dict:
    data: dict = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        },
        "settings": {},
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }

    # ── Settings ──
    row = (await session.execute(
        select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
    )).scalar_one_or_none()

    if row:
        display_data = dict(row.display or {})
        column_vis_per_user = display_data.pop("column_visibility_per_user", {})

        data["settings"] = {
            "general": row.general or {},
            "filters": row.filters or {},
            "equipment": row.equipment or {},
            "display": display_data,
            "graph": row.graph or {},
            "dismissed_suggestions": row.dismissed_suggestions or [],
        }

        # ── Column visibility (keyed by username) ──
        if column_vis_per_user:
            all_users = (await session.execute(select(User))).scalars().all()
            id_to_username = {str(u.id): u.username for u in all_users}
            for uid, vis in column_vis_per_user.items():
                username = id_to_username.get(uid)
                if username:
                    data["column_visibility"].append({
                        "username": username,
                        "visibility_settings": vis,
                    })

    # ── Session notes ──
    notes = (await session.execute(select(SessionNote))).scalars().all()
    target_ids = {n.target_id for n in notes}
    if target_ids:
        targets = (await session.execute(
            select(Target).where(Target.id.in_(target_ids))
        )).scalars().all()
        tid_to_name = {t.id: t.primary_name for t in targets}
    else:
        tid_to_name = {}

    for n in notes:
        tname = tid_to_name.get(n.target_id)
        if tname:
            data["session_notes"].append({
                "target_name": tname,
                "session_date": n.session_date.isoformat(),
                "notes": n.notes,
            })

    # ── Custom columns + values ──
    columns = (await session.execute(
        select(CustomColumn).options(selectinload(CustomColumn.values))
    )).scalars().all()

    val_target_ids = set()
    for col in columns:
        for v in col.values:
            val_target_ids.add(v.target_id)
    if val_target_ids:
        val_targets = (await session.execute(
            select(Target).where(Target.id.in_(val_target_ids))
        )).scalars().all()
        vtid_to_name = {t.id: t.primary_name for t in val_targets}
    else:
        vtid_to_name = {}

    for col in columns:
        col_data = {
            "name": col.name,
            "slug": col.slug,
            "column_type": col.column_type.value,
            "applies_to": col.applies_to.value,
            "dropdown_options": col.dropdown_options,
            "display_order": col.display_order,
            "values": [],
        }
        for v in col.values:
            tname = vtid_to_name.get(v.target_id)
            if tname:
                col_data["values"].append({
                    "target_name": tname,
                    "session_date": v.session_date.isoformat() if v.session_date else None,
                    "rig_label": v.rig_label,
                    "value": v.value,
                })
        data["custom_columns"].append(col_data)

    # ── Target overrides (user-modified fields only) ──
    targets_all = (await session.execute(select(Target))).scalars().all()
    merged_id_to_name = {t.id: t.primary_name for t in targets_all}

    for t in targets_all:
        has_override = t.notes or t.common_name or t.merged_into_id
        if has_override:
            data["target_overrides"].append({
                "target_name": t.primary_name,
                "custom_name": t.common_name,
                "notes": t.notes,
                "merged_into": merged_id_to_name.get(t.merged_into_id) if t.merged_into_id else None,
            })

    # ── Mosaics ──
    mosaics = (await session.execute(
        select(Mosaic).options(selectinload(Mosaic.panels))
    )).scalars().all()

    panel_target_ids = set()
    for m in mosaics:
        for p in m.panels:
            panel_target_ids.add(p.target_id)
    if panel_target_ids:
        panel_targets = (await session.execute(
            select(Target).where(Target.id.in_(panel_target_ids))
        )).scalars().all()
        ptid_to_name = {t.id: t.primary_name for t in panel_targets}
    else:
        ptid_to_name = {}

    for m in mosaics:
        data["mosaics"].append({
            "name": m.name,
            "notes": m.notes,
            "panels": [
                {
                    "object_name": ptid_to_name.get(p.target_id, ""),
                    "panel_label": p.panel_label,
                    "sort_order": p.sort_order,
                }
                for p in m.panels
            ],
        })

    # ── Users ──
    users = (await session.execute(select(User))).scalars().all()
    for u in users:
        data["users"].append({
            "username": u.username,
            "role": u.role.value,
        })

    return data
