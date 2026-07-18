from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_integration_seconds: float
    target_count: int
    total_frames: int
    all_frames: int
    disk_usage_bytes: int
    # Distinct (imaging night, telescope, camera) combinations -- NOT distinct
    # imaging nights. A night shot with two rigs counts as two rig-sessions
    # here. Every other "session" surface in the app (the calendar, target
    # detail, the paginated target aggregation) counts distinct nights
    # instead; do not conflate the two. See AUD-019.
    rig_session_count: int
    first_capture_date: str | None
    last_capture_date: str | None


class EquipmentItem(BaseModel):
    name: str
    frame_count: int
    integration_seconds: float = 0
    avg_session_seconds: float | None = None
    grouped: bool = False
    nights: int = 0
    target_count: int = 0
    median_fwhm: float | None = None
    # median_fwhm converted to arcsec via each frame's plate scale
    # (XPIXSZ/FOCALLEN headers), so values pooled across optical trains share a
    # unit. None when no frame in the group is plate-scaled.
    median_fwhm_arcsec: float | None = None
    median_guiding_rms: float | None = None


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
    # Arcsec-domain equivalents, pooled only over frames whose raw headers
    # yield a plate scale (XPIXSZ + FOCALLEN). The px figures above pool
    # incompatible optical trains; these do not.
    avg_hfr_arcsec: float | None = None
    best_hfr_arcsec: float | None = None
    # LIGHT frames with an HFR but no derivable plate scale (excluded from the
    # arcsec aggregates above, so the UI can disclose the exclusion).
    unscaled_frame_count: int | None = None
    # HFR histogram in arcsec: 0 to 8 in 0.5 steps plus an 8.0+ overflow bucket.
    hfr_arcsec_hist: list[HfrBucket] = []
    # Frames excluded from avg_eccentricity because their eccentricity_source
    # differs from the library's modal source (sources are not poolable).
    ecc_excluded_count: int | None = None


class StorageStats(BaseModel):
    fits_bytes: int
    fits_disk_bytes: int
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
    avg_session_seconds: float | None = None
    median_hfr: float | None
    best_hfr: float | None
    median_eccentricity: float | None
    median_fwhm: float | None
    mad_hfr: float | None = None
    mad_eccentricity: float | None = None
    mad_fwhm: float | None = None
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
