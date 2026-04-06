from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CustomColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    column_type: str = Field(..., pattern=r"^(boolean|text|dropdown)$")
    applies_to: str = Field(..., pattern=r"^(target|session|rig)$")
    dropdown_options: list[str] | None = None


class CustomColumnUpdate(BaseModel):
    name: str | None = None
    dropdown_options: list[str] | None = None
    display_order: int | None = None


class CustomColumnResponse(BaseModel):
    id: str
    name: str
    slug: str
    column_type: str
    applies_to: str
    dropdown_options: list[str] | None = None
    display_order: int
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomColumnValueSet(BaseModel):
    column_id: str
    target_id: str
    session_date: date | None = None
    rig_label: str | None = None
    value: str


class CustomColumnValueResponse(BaseModel):
    column_id: str
    column_slug: str
    target_id: str
    session_date: date | None = None
    rig_label: str | None = None
    value: str
    updated_by: str
    updated_at: datetime
