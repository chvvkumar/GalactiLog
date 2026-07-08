from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, computed_field


class DataJobItem(BaseModel):
    id: UUID
    job_type: str
    job_key: str
    status: str
    step: int | None = None
    total_steps: int | None = None
    message: str | None = None
    attempt_count: int
    last_error: str | None = None
    enqueued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def percent(self) -> float | None:
        if not self.total_steps:
            return None
        if self.step is None:
            return 0.0
        return round(min(self.step, self.total_steps) / self.total_steps * 100, 1)
