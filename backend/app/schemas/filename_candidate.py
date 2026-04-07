import uuid
from pydantic import BaseModel


class FilenameCandidateResponse(BaseModel):
    id: uuid.UUID
    extracted_name: str | None
    suggested_target_id: uuid.UUID | None
    suggested_target_name: str | None
    method: str
    confidence: float
    status: str
    file_count: int
    file_paths: list[str]
    created_at: str
    resolved_at: str | None


class AcceptRequest(BaseModel):
    target_id: uuid.UUID | None = None
    create_new: bool = False
