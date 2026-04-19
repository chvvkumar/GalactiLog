import uuid

from pydantic import BaseModel


class NotesUpdate(BaseModel):
    notes: str | None = None


class TargetBase(BaseModel):
    primary_name: str
    aliases: list[str] = []
    ra: float | None = None
    dec: float | None = None
    object_type: str | None = None


class TargetRead(TargetBase):
    id: uuid.UUID
    catalog_id: str | None = None
    common_name: str | None = None

    model_config = {"from_attributes": True}


class TargetSearchResult(BaseModel):
    id: uuid.UUID
    primary_name: str
    object_type: str | None = None


class SessionSummary(BaseModel):
    session_date: str
    integration_seconds: float
    frame_count: int
    filters_used: list[str]


class FilterMedian(BaseModel):
    filter_name: str
    median_hfr: float | None = None
    median_eccentricity: float | None = None
    median_fwhm: float | None = None
    median_guiding_rms: float | None = None
    median_detected_stars: float | None = None


class SessionOverview(BaseModel):
    session_date: str
    integration_seconds: float
    frame_count: int
    median_hfr: float | None = None
    median_eccentricity: float | None = None
    filters_used: list[str]
    camera: str | None = None
    telescope: str | None = None
    median_fwhm: float | None = None
    median_detected_stars: float | None = None
    median_guiding_rms_arcsec: float | None = None
    filter_medians: list[FilterMedian] = []
    has_notes: bool = False
    rig_count: int = 1
    custom_values: dict[str, str] | None = None


class FrameHighlight(BaseModel):
    file_name: str
    median_hfr: float | None = None
    eccentricity: float | None = None


class FilterDetail(BaseModel):
    filter_name: str
    frame_count: int
    integration_seconds: float
    median_hfr: float | None = None
    median_eccentricity: float | None = None
    exposure_time: float | None = None


class RigDetail(BaseModel):
    rig_label: str
    telescope: str | None = None
    camera: str | None = None
    frame_count: int
    integration_seconds: float
    median_hfr: float | None = None
    median_eccentricity: float | None = None
    median_fwhm: float | None = None
    median_guiding_rms: float | None = None
    median_detected_stars: float | None = None
    gain: int | None = None
    offset: int | None = None
    exposure_times: list[float] = []
    filter_details: list[FilterDetail] = []
    frames: list["FrameRecord"] = []
    thumbnail_url: str | None = None


class SessionInsight(BaseModel):
    level: str
    message: str


class FrameRecord(BaseModel):
    timestamp: str
    filter_used: str | None = None
    exposure_time: float | None = None
    median_hfr: float | None = None
    eccentricity: float | None = None
    sensor_temp: float | None = None
    gain: int | None = None
    file_name: str
    image_id: str
    file_path: str
    thumbnail_url: str | None = None
    hfr_stdev: float | None = None
    fwhm: float | None = None
    detected_stars: int | None = None
    guiding_rms_arcsec: float | None = None
    guiding_rms_ra_arcsec: float | None = None
    guiding_rms_dec_arcsec: float | None = None
    adu_stdev: float | None = None
    adu_mean: float | None = None
    adu_median: float | None = None
    adu_min: int | None = None
    adu_max: int | None = None
    focuser_position: int | None = None
    focuser_temp: float | None = None
    rotator_position: float | None = None
    pier_side: str | None = None
    airmass: float | None = None
    ambient_temp: float | None = None
    dew_point: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    wind_gust: float | None = None
    cloud_cover: float | None = None
    sky_quality: float | None = None
    rig: str | None = None


RigDetail.model_rebuild()


class TargetAggregation(BaseModel):
    target_id: str
    primary_name: str
    aliases: list[str] = []
    total_integration_seconds: float
    total_frames: int
    filter_distribution: dict[str, float]
    equipment: list[str]
    sessions: list[SessionSummary]
    matched_sessions: int | None = None
    total_sessions: int | None = None
    mosaic_id: str | None = None
    mosaic_name: str | None = None
    custom_values: dict[str, str] | None = None


class AggregateStats(BaseModel):
    total_integration_seconds: float
    target_count: int
    total_frames: int
    disk_usage_bytes: int
    oldest_date: str | None = None
    newest_date: str | None = None


class TargetAggregationResponse(BaseModel):
    targets: list[TargetAggregation]
    aggregates: AggregateStats
    total_count: int
    page: int
    page_size: int


class CatalogMembershipEntry(BaseModel):
    catalog_name: str
    catalog_number: str
    metadata: dict | None = None


class TargetDetailResponse(BaseModel):
    target_id: str
    primary_name: str
    aliases: list[str] = []
    object_type: str | None = None
    object_category: str | None = None
    constellation: str | None = None
    ra: float | None = None
    dec: float | None = None
    size_major: float | None = None
    size_minor: float | None = None
    position_angle: float | None = None
    v_mag: float | None = None
    surface_brightness: float | None = None
    total_integration_seconds: float
    total_frames: int
    avg_hfr: float | None = None
    avg_eccentricity: float | None = None
    filters_used: list[str]
    equipment: list[str]
    first_session_date: str
    last_session_date: str
    session_count: int
    sessions: list[SessionOverview]
    avg_fwhm: float | None = None
    avg_guiding_rms_arcsec: float | None = None
    avg_detected_stars: float | None = None
    notes: str | None = None
    # SAC
    sac_description: str | None = None
    sac_notes: str | None = None
    # SkyView
    reference_thumbnail_path: str | None = None
    # Gaia DR3
    distance_pc: float | None = None
    # Catalog memberships
    catalog_memberships: list[CatalogMembershipEntry] = []


class SessionDetailResponse(BaseModel):
    target_name: str
    session_date: str
    thumbnail_url: str | None = None
    frame_count: int
    integration_seconds: float
    median_hfr: float | None = None
    median_eccentricity: float | None = None
    filters_used: dict[str, int]
    equipment: dict[str, str | None]
    raw_reference_header: dict | None = None
    min_hfr: float | None = None
    max_hfr: float | None = None
    min_eccentricity: float | None = None
    max_eccentricity: float | None = None
    sensor_temp: float | None = None
    sensor_temp_min: float | None = None
    sensor_temp_max: float | None = None
    gain: int | None = None
    offset: int | None = None
    exposure_times: list[float] = []
    first_frame_time: str | None = None
    last_frame_time: str | None = None
    filter_details: list[FilterDetail] = []
    insights: list[SessionInsight] = []
    frames: list[FrameRecord] = []
    median_fwhm: float | None = None
    min_fwhm: float | None = None
    max_fwhm: float | None = None
    median_guiding_rms: float | None = None
    min_guiding_rms: float | None = None
    max_guiding_rms: float | None = None
    median_detected_stars: float | None = None
    median_airmass: float | None = None
    median_ambient_temp: float | None = None
    median_humidity: float | None = None
    median_cloud_cover: float | None = None
    notes: str | None = None
    rigs: list[RigDetail] = []
    custom_values: list[dict] | None = None


class EquipmentOption(BaseModel):
    name: str
    grouped: bool = False


class EquipmentResponse(BaseModel):
    cameras: list[EquipmentOption]
    telescopes: list[EquipmentOption]


class TargetSearchResultFuzzy(BaseModel):
    id: uuid.UUID
    primary_name: str
    object_type: str | None = None
    aliases: list[str] = []
    match_source: str | None = None
    similarity_score: float = 1.0


class ObjectTypeCount(BaseModel):
    object_type: str
    count: int


class MergeCandidateResponse(BaseModel):
    id: uuid.UUID
    source_name: str
    source_image_count: int
    suggested_target_id: uuid.UUID
    suggested_target_name: str
    similarity_score: float
    method: str
    status: str
    created_at: str


class MergedTargetResponse(BaseModel):
    id: uuid.UUID
    primary_name: str
    merged_into_id: uuid.UUID
    merged_into_name: str
    merged_at: str
    image_count: int


class MergeRequest(BaseModel):
    winner_id: uuid.UUID
    loser_id: uuid.UUID | None = None
    loser_name: str | None = None
