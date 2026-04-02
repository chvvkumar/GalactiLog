from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_integration_seconds: float
    target_count: int
    total_frames: int
    disk_usage_bytes: int


class EquipmentItem(BaseModel):
    name: str
    frame_count: int
    grouped: bool = False


class EquipmentStats(BaseModel):
    cameras: list[EquipmentItem]
    telescopes: list[EquipmentItem]


class TimelineEntry(BaseModel):
    month: str
    integration_seconds: float


class TimelineDetailEntry(BaseModel):
    period: str
    integration_seconds: float
    efficiency_pct: float | None = None


class SiteCoords(BaseModel):
    latitude: float
    longitude: float


class TopTarget(BaseModel):
    name: str
    integration_seconds: float


class HfrBucket(BaseModel):
    bucket: str
    count: int


class DataQualityStats(BaseModel):
    avg_hfr: float | None
    avg_eccentricity: float | None
    best_hfr: float | None
    hfr_distribution: list[HfrBucket]


class StorageStats(BaseModel):
    fits_bytes: int
    thumbnail_bytes: int
    database_bytes: int


class IngestEntry(BaseModel):
    date: str
    files_added: int


class EquipmentFilterMetrics(BaseModel):
    filter_name: str
    frame_count: int
    total_integration_seconds: float
    median_hfr: float | None
    best_hfr: float | None
    median_eccentricity: float | None
    median_fwhm: float | None


class EquipmentComboMetrics(BaseModel):
    telescope: str
    camera: str
    frame_count: int
    total_integration_seconds: float
    median_hfr: float | None
    best_hfr: float | None
    median_eccentricity: float | None
    median_fwhm: float | None
    grouped: bool
    filters: list[str]
    filter_breakdown: list[EquipmentFilterMetrics]


class CalendarEntry(BaseModel):
    date: str
    integration_seconds: float
    target_count: int
    frame_count: int


class StatsResponse(BaseModel):
    overview: OverviewStats
    equipment: EquipmentStats
    equipment_performance: list[EquipmentComboMetrics]
    filter_usage: dict[str, float]
    timeline: list[TimelineEntry]
    timeline_monthly: list[TimelineDetailEntry]
    timeline_weekly: list[TimelineDetailEntry]
    timeline_daily: list[TimelineDetailEntry]
    site_coords: SiteCoords | None
    top_targets: list[TopTarget]
    data_quality: DataQualityStats
    storage: StorageStats
    ingest_history: list[IngestEntry]
