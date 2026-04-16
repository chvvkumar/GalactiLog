from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ActivityItem(BaseModel):
    id: int
    timestamp: datetime
    severity: str
    category: str
    event_type: str
    message: str
    details: dict[str, Any] | None = None
    target_id: UUID | None = None
    actor: str | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}


class PaginatedActivityResponse(BaseModel):
    items: list[ActivityItem]
    next_cursor: str | None = None
    total: int


class ActivityFilterParams(BaseModel):
    severity: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
    since: datetime | None = None

    @field_validator("limit", mode="before")
    @classmethod
    def cap_limit(cls, v: int) -> int:
        return min(int(v), 200)
