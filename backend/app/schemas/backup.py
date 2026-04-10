from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ── Export format ──────────────────────────────────────────────────────


class BackupMeta(BaseModel):
    schema_version: int
    app_version: str
    exported_at: datetime


class BackupSessionNote(BaseModel):
    target_name: str
    session_date: str  # ISO date YYYY-MM-DD
    notes: str


class BackupCustomColumnValue(BaseModel):
    target_name: str
    session_date: str | None = None
    rig_label: str | None = None
    value: str


class BackupCustomColumn(BaseModel):
    name: str
    slug: str
    column_type: str  # "boolean" | "text" | "dropdown"
    applies_to: str  # "target" | "session" | "rig"
    dropdown_options: list[str] | None = None
    display_order: int = 0
    values: list[BackupCustomColumnValue] = []


class BackupTargetOverride(BaseModel):
    target_name: str
    custom_name: str | None = None
    notes: str | None = None
    merged_into: str | None = None  # target name, not ID


class BackupMosaicPanel(BaseModel):
    object_name: str
    panel_label: str
    sort_order: int = 0
    ra: float | None = None
    dec: float | None = None


class BackupMosaic(BaseModel):
    name: str
    notes: str | None = None
    panels: list[BackupMosaicPanel] = []


class BackupUser(BaseModel):
    username: str
    role: str  # "admin" | "viewer"


class BackupColumnVisibility(BaseModel):
    username: str
    visibility_settings: dict[str, Any]


class BackupPayload(BaseModel):
    meta: BackupMeta
    settings: dict[str, Any]
    session_notes: list[BackupSessionNote] = []
    custom_columns: list[BackupCustomColumn] = []
    target_overrides: list[BackupTargetOverride] = []
    mosaics: list[BackupMosaic] = []
    users: list[BackupUser] = []
    column_visibility: list[BackupColumnVisibility] = []


# ── Validate / restore responses ──────────────────────────────────────


class SectionPreview(BaseModel):
    add: int = 0
    update: int = 0
    skip: int = 0
    unchanged: int = 0


class ValidateResponse(BaseModel):
    valid: bool
    meta: BackupMeta | None = None
    preview: dict[str, SectionPreview] = {}
    warnings: list[str] = []
    error: str | None = None


class RestoreResponse(BaseModel):
    success: bool
    applied: dict[str, SectionPreview] = {}
    temporary_passwords: dict[str, str] = {}
    warnings: list[str] = []
    error: str | None = None
