import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    can_write: bool = False


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    can_write: bool
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(BaseModel):
    """Creation is the only response that ever carries the raw key."""

    key: str
    id: uuid.UUID
    name: str
    prefix: str
    can_write: bool
    created_at: datetime
