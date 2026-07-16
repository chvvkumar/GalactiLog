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
    relative_path: str = ""
    # Bytes of exactly the frames frame_count counts. None when any contributing
    # frame's size is unknown (older ingests have a NULL file_size) -- callers must
    # render "unknown" rather than treat None as 0 or show a partial sum.
    frame_bytes: int | None = None


class WbppSessionPreview(BaseModel):
    session_date: str
    levels: list[WbppFolderLevel]
    default_level_index: int
    total_frame_count: int
    excluded_frame_count: int = 0


class WbppPreviewRequest(BaseModel):
    target_id: str
    session_dates: list[str]
    chosen_levels: dict[str, int] = Field(default_factory=dict)
    library_root: str
    target_os: str | None = None
    # LIGHT frame paths (relative to the FITS/library root, POSIX) to omit.
    excluded_source_relatives: list[str] = Field(default_factory=list)


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
    # LIGHT frame paths (relative to the FITS/library root, POSIX) to omit.
    excluded_source_relatives: list[str] = Field(default_factory=list)


class WbppCopyOperation(BaseModel):
    session_date: str
    source: str
    destination: str
    # Path of the source folder relative to the library/FITS root, for the
    # browser File System Access API to navigate the user-granted root handle.
    source_relative: str
    # Folder name to create under the destination handle (staging entry).
    dest_entry: str


class WbppGenerateResponse(BaseModel):
    filename: str
    target_os: str
    staging_root: str
    script: str
    operations: list[WbppCopyOperation]
    exclusions: list[str]
    light_total: int = 0
    light_excluded: int = 0
    light_copied: int = 0
