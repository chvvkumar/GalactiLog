import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    role: str


class MeResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(admin|viewer)$")


class UserUpdateRequest(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|viewer)$")
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
