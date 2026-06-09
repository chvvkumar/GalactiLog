from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    result: Any | None = None
