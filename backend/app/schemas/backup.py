from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    column_type: Literal["boolean", "text", "dropdown"]
    applies_to: Literal["target", "session", "rig"]
    dropdown_options: list[str] | None = None
    display_order: int = 0
    values: list[BackupCustomColumnValue] = Field(default_factory=list)


class BackupTargetOverride(BaseModel):
    target_name: str
    custom_name: str | None = None
    notes: str | None = None
    merged_into: str | None = None  # target name, not ID


class BackupMosaicPanel(BaseModel):
    object_name: str
    panel_label: str
    sort_order: int = 0


class BackupMosaic(BaseModel):
    name: str
    notes: str | None = None
    panels: list[BackupMosaicPanel] = Field(default_factory=list)


class BackupUser(BaseModel):
    username: str
    role: Literal["admin", "viewer"]


class BackupColumnVisibility(BaseModel):
    username: str
    visibility_settings: dict[str, Any]


class BackupPayload(BaseModel):
    meta: BackupMeta
    settings: dict[str, Any]
    session_notes: list[BackupSessionNote] = Field(default_factory=list)
    custom_columns: list[BackupCustomColumn] = Field(default_factory=list)
    target_overrides: list[BackupTargetOverride] = Field(default_factory=list)
    mosaics: list[BackupMosaic] = Field(default_factory=list)
    users: list[BackupUser] = Field(default_factory=list)
    column_visibility: list[BackupColumnVisibility] = Field(default_factory=list)


# ── Validate / restore responses ──────────────────────────────────────


class SectionPreview(BaseModel):
    add: int = 0
    update: int = 0
    skip: int = 0
    unchanged: int = 0


class ValidateResponse(BaseModel):
    valid: bool
    meta: BackupMeta | None = None
    preview: dict[str, SectionPreview] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class RestoreResponse(BaseModel):
    success: bool
    applied: dict[str, SectionPreview] = Field(default_factory=dict)
    temporary_passwords: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
