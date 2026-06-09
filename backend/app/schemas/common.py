from __future__ import annotations

from pydantic import BaseModel


class StatusResponse(BaseModel):
    """Generic single-field status response, e.g. {"status": "ok"}."""
    status: str
