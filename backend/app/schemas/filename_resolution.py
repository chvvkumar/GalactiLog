from __future__ import annotations

from pydantic import BaseModel


class CandidateCountResponse(BaseModel):
    count: int


class DetectResponse(BaseModel):
    status: str
    task_id: str
