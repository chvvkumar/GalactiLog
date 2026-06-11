from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AppLogItem(BaseModel):
    id: int
    timestamp: datetime
    level: str
    source: str
    logger: str
    message: str
    traceback: str | None = None

    model_config = {"from_attributes": True}


class PaginatedAppLogResponse(BaseModel):
    items: list[AppLogItem]
    next_cursor: str | None = None
    total: int
