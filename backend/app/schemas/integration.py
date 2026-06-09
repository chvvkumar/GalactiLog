from __future__ import annotations

from pydantic import BaseModel


class IntegrationResponse(BaseModel):
    ok: bool
    error: str | None = None
