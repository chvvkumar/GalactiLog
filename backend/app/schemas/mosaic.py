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


class MosaicCreate(BaseModel):
    name: str
    notes: str | None = None
    panels: list[MosaicPanelCreate] = []


class MosaicUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None


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
    object_pattern: str | None = None


class MosaicSummary(BaseModel):
    id: str
    name: str
    notes: str | None = None
    panel_count: int
    total_integration_seconds: float
    total_frames: int
    completion_pct: float


class MosaicDetailResponse(BaseModel):
    id: str
    name: str
    notes: str | None = None
    total_integration_seconds: float
    total_frames: int
    panels: list[PanelStats]


class SuggestionPanelSession(BaseModel):
    panel_label: str
    object_name: str
    date: str
    frames: int
    integration_seconds: float
    filter_used: str | None = None


class AcceptSuggestionRequest(BaseModel):
    selected_panels: list[str] | None = None  # subset of panel_labels to accept; None = all


class MosaicSuggestionResponse(BaseModel):
    id: str
    suggested_name: str
    target_ids: list[str]
    panel_labels: list[str]
    target_names: dict[str, str]
    sessions: list[SuggestionPanelSession]
    status: str
