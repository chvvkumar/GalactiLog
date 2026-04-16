import uuid

from pydantic import BaseModel


class MosaicPanelCreate(BaseModel):
    target_id: uuid.UUID
    panel_label: str
    object_pattern: str | None = None


class MosaicPanelUpdate(BaseModel):
    panel_label: str | None = None
    sort_order: int | None = None
    object_pattern: str | None = None
    grid_row: int | None = None
    grid_col: int | None = None
    rotation: int | None = None
    flip_h: bool | None = None


class MosaicCreate(BaseModel):
    name: str
    notes: str | None = None
    panels: list[MosaicPanelCreate] = []


class MosaicUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None
    rotation_angle: float | None = None
    pixel_coords: bool | None = None


class PanelStats(BaseModel):
    panel_id: str
    target_id: str
    target_name: str
    panel_label: str
    sort_order: int
    ra: float | None = None
    dec: float | None = None
    total_integration_seconds: float
    total_frames: int
    filter_distribution: dict[str, float]
    last_session_date: str | None = None
    thumbnail_url: str | None = None
    thumbnail_pier_side: str | None = None
    thumbnail_image_id: str | None = None
    thumbnail_file_path: str | None = None
    object_pattern: str | None = None
    grid_row: int | None = None
    grid_col: int | None = None
    rotation: int = 0
    flip_h: bool = False
    available_session_count: int = 0


class PanelThumbnail(BaseModel):
    panel_id: str
    thumbnail_url: str | None = None
    frame_id: str | None = None
    score: float | None = None
    filter_used: str


class MosaicSummary(BaseModel):
    id: str
    name: str
    notes: str | None = None
    panel_count: int
    total_integration_seconds: float
    total_frames: int
    completion_pct: float
    first_session: str | None = None
    last_session: str | None = None
    needs_review: bool = False


class MosaicPanelBatchItem(BaseModel):
    panel_id: uuid.UUID
    grid_row: int | None = None
    grid_col: int | None = None
    rotation: int | None = None
    flip_h: bool | None = None


class MosaicPanelBatchRequest(BaseModel):
    panels: list[MosaicPanelBatchItem]
    rotation_angle: float | None = None


class MosaicDetailResponse(BaseModel):
    id: str
    name: str
    notes: str | None = None
    rotation_angle: float | None = None
    pixel_coords: bool = False
    total_integration_seconds: float
    total_frames: int
    panels: list[PanelStats]
    available_filters: list[str] = []
    default_filter: str | None = None
    needs_review: bool = False


class SuggestionPanelSession(BaseModel):
    panel_label: str
    object_name: str
    date: str
    frames: int
    integration_seconds: float
    filter_used: str | None = None


class AcceptSuggestionRequest(BaseModel):
    selected_panels: list[str] | None = None  # subset of panel_labels to accept; None = all


class PanelSessionInfo(BaseModel):
    session_date: str
    status: str
    total_frames: int
    total_integration_seconds: float
    filters: dict[str, dict[str, float | int]]


class PanelSessionsResponse(BaseModel):
    panel_id: str
    panel_label: str
    sessions: list[PanelSessionInfo]


class SessionStatusUpdate(BaseModel):
    include: list[str] = []
    exclude: list[str] = []


class MosaicSuggestionResponse(BaseModel):
    id: str
    suggested_name: str
    base_name: str | None = None
    target_ids: list[str]
    panel_labels: list[str]
    panel_patterns: list[str] | None = None
    target_names: dict[str, str]
    sessions: list[SuggestionPanelSession]
    session_dates: dict[str, list[str]] | None = None
    other_session_count: int = 0
    status: str
