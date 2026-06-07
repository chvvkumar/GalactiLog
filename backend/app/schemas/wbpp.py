"""Request/response schemas for WBPP export endpoints."""
from pydantic import BaseModel, Field


class WbppFolderLevel(BaseModel):
    path: str
    container_path: str
    depth_from_root: int
    frame_count: int
    other_targets: list[str] = Field(default_factory=list)
    other_dates: list[str] = Field(default_factory=list)
    is_contaminated: bool


class WbppSessionPreview(BaseModel):
    session_date: str
    levels: list[WbppFolderLevel]
    default_level_index: int
    total_frame_count: int


class WbppPreviewRequest(BaseModel):
    target_id: str
    session_dates: list[str]
    chosen_levels: dict[str, int] = Field(default_factory=dict)
    library_root: str
    target_os: str | None = None


class WbppPreviewResponse(BaseModel):
    sessions: list[WbppSessionPreview]
    target_os: str


class WbppGenerateRequest(BaseModel):
    target_id: str
    target_name: str
    session_dates: list[str]
    chosen_levels: dict[str, int] = Field(default_factory=dict)
    library_root: str
    target_os: str | None = None
    staging_path: str | None = None
    exclusions: list[str] = Field(
        default_factory=lambda: [
            "WBPP", "PixInsight", "finals", "WORK_AREA",
            "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
        ]
    )


class WbppCopyOperation(BaseModel):
    session_date: str
    source: str
    destination: str


class WbppGenerateResponse(BaseModel):
    filename: str
    target_os: str
    staging_root: str
    script: str
    operations: list[WbppCopyOperation]
