from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    result: Any | None = None


class JobEntry(BaseModel):
    task_id: str
    name: str
    state: str  # "queued" | "running"
    queued_at: float | None = None
    started_at: float | None = None
    # ISO timestamp from Celery's eta/countdown, when the task was dispatched
    # with a delay; lets the UI say "starts in Ns" instead of just "waiting".
    eta: str | None = None


class JobsResponse(BaseModel):
    jobs: list[JobEntry]
