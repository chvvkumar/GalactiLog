from __future__ import annotations

"""Export/restore user customizations as portable versioned JSON backups."""

import secrets
from collections.abc import Callable
from datetime import datetime, timezone, date as date_type

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.models.session_note import SessionNote
from app.models.custom_column import CustomColumn, CustomColumnValue, ColumnType, AppliesTo
from app.models.target import Target
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.user import User, UserRole
from app.schemas.backup import BackupPayload
from app.services.auth import hash_password

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


# ── Validate / Restore ────────────────────────────────────────────────

ALL_SECTIONS = [
    "settings", "session_notes", "custom_columns",
    "target_overrides", "mosaics", "users", "column_visibility",
]


def validate_backup(
    data: dict,
    sections: list[str] | None,
    mode: str,
) -> dict:
    """Validate a backup dict and return a preview. No DB access.

    NOTE: Preview counts are upper bounds computed from the backup file
    content only. The actual restore result may reclassify some items as
    updates rather than adds. The true breakdown is reported by
    restore_backup in its `applied` field.
    """
    result = {
        "valid": False,
        "meta": None,
        "preview": {},
        "warnings": [],
        "error": None,
    }

    if mode not in ("merge", "replace"):
        result["error"] = f"Invalid mode '{mode}': must be 'merge' or 'replace'"
        return result

    # ── Structure check ──
    if "meta" not in data:
        result["error"] = "Invalid backup file: missing 'meta' field"
        return result

    meta = data["meta"]
    if not isinstance(meta, dict) or "schema_version" not in meta:
        result["error"] = "Invalid backup file: 'meta' must contain 'schema_version'"
        return result

    # ── Schema version check ──
    sv = meta.get("schema_version", 0)
    if sv > CURRENT_BACKUP_SCHEMA_VERSION:
        result["error"] = (
            f"This backup was created by a newer app version (schema v{sv}). "
            f"This app supports up to schema v{CURRENT_BACKUP_SCHEMA_VERSION}. "
            f"Please upgrade the app before restoring."
        )
        return result

    # ── Apply migrations if needed ──
    try:
        data = apply_migrations(data)
    except ValueError as e:
        result["error"] = str(e)
        return result

    # ── Parse with Pydantic for full validation ──
    try:
        parsed = BackupPayload.model_validate(data)
    except Exception as e:
        result["error"] = f"Backup file has invalid structure: {e}"
        return result

    result["valid"] = True
    result["meta"] = {
        "schema_version": parsed.meta.schema_version,
        "app_version": parsed.meta.app_version,
        "exported_at": parsed.meta.exported_at.isoformat(),
    }

    # ── Build preview for selected sections ──
    active = sections if sections else ALL_SECTIONS

    if "settings" in active and data.get("settings"):
        result["preview"]["settings"] = {"add": 0, "update": 1, "skip": 0, "unchanged": 0}

    if "session_notes" in active:
        count = len(parsed.session_notes)
        result["preview"]["session_notes"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    if "custom_columns" in active:
        count = len(parsed.custom_columns)
        result["preview"]["custom_columns"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    if "target_overrides" in active:
        count = len(parsed.target_overrides)
        result["preview"]["target_overrides"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    if "mosaics" in active:
        count = len(parsed.mosaics)
        result["preview"]["mosaics"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    if "users" in active:
        count = len(parsed.users)
        result["preview"]["users"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    if "column_visibility" in active:
        count = len(parsed.column_visibility)
        result["preview"]["column_visibility"] = {"add": count, "update": 0, "skip": 0, "unchanged": 0}

    return result


async def restore_backup(
    session: AsyncSession,
    data: dict,
    sections: list[str] | None,
    mode: str,
    acting_user_id=None,  # UUID from the requesting admin
) -> dict:
    """Apply a validated backup to the database. Runs in caller's transaction."""
    if mode not in ("merge", "replace"):
        raise ValueError(f"Invalid mode '{mode}': must be 'merge' or 'replace'")

    data = apply_migrations(data)
    parsed = BackupPayload.model_validate(data)

    active = sections if sections else ALL_SECTIONS
    result = {
        "success": False,
        "applied": {},
        "temporary_passwords": {},
        "warnings": [],
    }

    # Build target name -> id lookup
    all_targets = (await session.execute(select(Target))).scalars().all()
    name_to_target = {t.primary_name: t for t in all_targets}

    # ── Settings ──
    if "settings" in active and parsed.settings:
        row = (await session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        )).scalar_one_or_none()

        if not row:
            row = UserSettings(id=SETTINGS_ROW_ID)
            session.add(row)

        settings_data = data["settings"]
        row.general = settings_data.get("general", row.general or {})
        row.filters = settings_data.get("filters", row.filters or {})
        row.equipment = settings_data.get("equipment", row.equipment or {})
        row.graph = settings_data.get("graph", row.graph or {})
        row.dismissed_suggestions = settings_data.get("dismissed_suggestions", row.dismissed_suggestions or [])

        # Merge display without clobbering column_visibility_per_user
        existing_display = dict(row.display or {})
        col_vis = existing_display.pop("column_visibility_per_user", {})
        new_display = settings_data.get("display", existing_display)
        new_display["column_visibility_per_user"] = col_vis
        row.display = new_display

        await session.flush()
        result["applied"]["settings"] = {"add": 0, "update": 1, "skip": 0, "unchanged": 0}

    # ── Session notes ──
    if "session_notes" in active:
        if mode == "replace":
            await session.execute(delete(SessionNote))

        added, updated, skipped = 0, 0, 0
        for note in parsed.session_notes:
            target = name_to_target.get(note.target_name)
            if not target:
                result["warnings"].append(
                    f"Target '{note.target_name}' not found — skipping session note"
                )
                skipped += 1
                continue

            existing = (await session.execute(
                select(SessionNote).where(
                    SessionNote.target_id == target.id,
                    SessionNote.session_date == date_type.fromisoformat(note.session_date),
                )
            )).scalar_one_or_none()

            if existing:
                existing.notes = note.notes
                updated += 1
            else:
                session.add(SessionNote(
                    target_id=target.id,
                    session_date=date_type.fromisoformat(note.session_date),
                    notes=note.notes,
                ))
                added += 1

        await session.flush()
        result["applied"]["session_notes"] = {
            "add": added, "update": updated, "skip": skipped, "unchanged": 0,
        }

    # ── Custom columns ──
    if "custom_columns" in active:
        if mode == "replace":
            await session.execute(delete(CustomColumnValue))
            await session.execute(delete(CustomColumn))
            await session.flush()

        added, updated, skipped = 0, 0, 0
        for col_data in parsed.custom_columns:
            existing_col = (await session.execute(
                select(CustomColumn).where(CustomColumn.slug == col_data.slug)
            )).scalar_one_or_none()

            if existing_col:
                existing_col.name = col_data.name
                existing_col.column_type = ColumnType(col_data.column_type)
                existing_col.applies_to = AppliesTo(col_data.applies_to)
                existing_col.dropdown_options = col_data.dropdown_options
                existing_col.display_order = col_data.display_order
                col_obj = existing_col
                updated += 1
            else:
                col_obj = CustomColumn(
                    name=col_data.name,
                    slug=col_data.slug,
                    column_type=ColumnType(col_data.column_type),
                    applies_to=AppliesTo(col_data.applies_to),
                    dropdown_options=col_data.dropdown_options,
                    display_order=col_data.display_order,
                    created_by=acting_user_id,
                )
                session.add(col_obj)
                await session.flush()
                added += 1

            for val in col_data.values:
                target = name_to_target.get(val.target_name)
                if not target:
                    skipped += 1
                    continue

                sd = date_type.fromisoformat(val.session_date) if val.session_date else None

                conditions = [
                    CustomColumnValue.column_id == col_obj.id,
                    CustomColumnValue.target_id == target.id,
                ]
                if sd is None:
                    conditions.append(CustomColumnValue.session_date.is_(None))
                else:
                    conditions.append(CustomColumnValue.session_date == sd)
                if val.rig_label is None:
                    conditions.append(CustomColumnValue.rig_label.is_(None))
                else:
                    conditions.append(CustomColumnValue.rig_label == val.rig_label)

                existing_val = (await session.execute(
                    select(CustomColumnValue).where(*conditions)
                )).scalar_one_or_none()

                if existing_val:
                    existing_val.value = val.value
                else:
                    session.add(CustomColumnValue(
                        column_id=col_obj.id,
                        target_id=target.id,
                        session_date=sd,
                        rig_label=val.rig_label,
                        value=val.value,
                        updated_by=acting_user_id,
                    ))

        await session.flush()
        result["applied"]["custom_columns"] = {
            "add": added, "update": updated, "skip": skipped, "unchanged": 0,
        }

    # ── Target overrides ──
    if "target_overrides" in active:
        added, updated, skipped = 0, 0, 0
        for override in parsed.target_overrides:
            target = name_to_target.get(override.target_name)
            if not target:
                result["warnings"].append(
                    f"Target '{override.target_name}' not found — skipping override"
                )
                skipped += 1
                continue

            target.common_name = override.custom_name
            target.notes = override.notes
            if override.merged_into:
                merge_target = name_to_target.get(override.merged_into)
                if merge_target:
                    target.merged_into_id = merge_target.id
            updated += 1

        await session.flush()
        result["applied"]["target_overrides"] = {
            "add": added, "update": updated, "skip": skipped, "unchanged": 0,
        }

    # ── Mosaics ──
    if "mosaics" in active:
        if mode == "replace":
            await session.execute(delete(MosaicPanel))
            await session.execute(delete(Mosaic))
            await session.flush()

        added, updated, skipped = 0, 0, 0
        for m_data in parsed.mosaics:
            existing_mosaic = (await session.execute(
                select(Mosaic).where(Mosaic.name == m_data.name)
            )).scalar_one_or_none()

            if existing_mosaic:
                existing_mosaic.notes = m_data.notes
                mosaic_obj = existing_mosaic
                await session.execute(
                    delete(MosaicPanel).where(MosaicPanel.mosaic_id == existing_mosaic.id)
                )
                updated += 1
            else:
                mosaic_obj = Mosaic(name=m_data.name, notes=m_data.notes)
                session.add(mosaic_obj)
                await session.flush()
                added += 1

            for p in m_data.panels:
                panel_target = name_to_target.get(p.object_name)
                if not panel_target:
                    result["warnings"].append(
                        f"Target '{p.object_name}' not found — skipping mosaic panel"
                    )
                    continue
                session.add(MosaicPanel(
                    mosaic_id=mosaic_obj.id,
                    target_id=panel_target.id,
                    panel_label=p.panel_label,
                    sort_order=p.sort_order,
                ))

        await session.flush()
        result["applied"]["mosaics"] = {
            "add": added, "update": updated, "skip": skipped, "unchanged": 0,
        }

    # ── Users ──
    if "users" in active:
        # Note: Replace mode does NOT delete existing users by design — this is a safety
        # measure to prevent locking out admins mid-restore. Users are always merged by username.
        added, updated, skipped = 0, 0, 0
        for u_data in parsed.users:
            existing_user = (await session.execute(
                select(User).where(User.username == u_data.username)
            )).scalar_one_or_none()

            if existing_user:
                existing_user.role = UserRole(u_data.role)
                updated += 1
            else:
                temp_password = secrets.token_urlsafe(12)
                session.add(User(
                    username=u_data.username,
                    password_hash=hash_password(temp_password),
                    role=UserRole(u_data.role),
                    is_active=True,
                ))
                result["temporary_passwords"][u_data.username] = temp_password
                added += 1

        await session.flush()
        result["applied"]["users"] = {
            "add": added, "update": updated, "skip": skipped, "unchanged": 0,
        }

    # ── Column visibility ──
    if "column_visibility" in active:
        row = (await session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        )).scalar_one_or_none()

        if row:
            display = dict(row.display or {})
            per_user = display.get("column_visibility_per_user", {})

            all_users = (await session.execute(select(User))).scalars().all()
            username_to_id = {u.username: str(u.id) for u in all_users}

            restored = 0
            for cv in parsed.column_visibility:
                uid = username_to_id.get(cv.username)
                if uid:
                    per_user[uid] = cv.visibility_settings
                    restored += 1

            display["column_visibility_per_user"] = per_user
            row.display = display
            await session.flush()

            result["applied"]["column_visibility"] = {
                "add": restored, "update": 0, "skip": 0, "unchanged": 0,
            }

    result["success"] = True
    return result
