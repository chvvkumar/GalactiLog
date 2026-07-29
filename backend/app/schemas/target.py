import uuid
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.phd2 import Phd2NightSummary


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
    median_hfr: float | None = None
    median_eccentricity: float | None = None


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
    # Plate-scale-converted quality metrics (arcsec). None when the session's
    # frames carry no usable XPIXSZ/FOCALLEN headers.
    hfr_arcsec: float | None = None
    fwhm_arcsec: float | None = None
    filter_medians: list[FilterMedian] = []
    has_notes: bool = False
    rig_count: int = 1
    custom_values: dict[str, str] | None = None
    ra: float | None = None
    dec: float | None = None
    position_angle: float | None = None


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


# Severity of an insight. This is the whole domain the backend has ever
# emitted; the frontend keys its colour/icon maps off it, so an unconstrained
# `str` here silently rendered an undefined class for any typo.
InsightLevel = Literal["info", "good", "warning"]

# What the insight is *about*. Previously this existed only as free text inside
# `message`, so nothing downstream could filter, count, or test a category
# without matching on English prose.
InsightKind = Literal[
    "session_duration",
    "hfr_vs_target",
    "sensor_temp",
    "hfr_outliers",
    "eccentricity_outliers",
    "eccentricity_vs_rig",
]


class SessionInsight(BaseModel):
    level: InsightLevel
    kind: InsightKind
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
    file_size: int | None = None  # bytes; None for older ingests that predate the column
    source_relative: str = ""
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
    user_defined: bool = False


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
    # avg_hfr converted to arcsec, pooled only over frames whose headers yield
    # a plate scale (XPIXSZ + FOCALLEN). None when no frame is plate-scaled.
    avg_hfr_arcsec: float | None = None
    avg_eccentricity: float | None = None
    # Frames excluded from avg_eccentricity because their eccentricity_source
    # differs from the modal (most common) source for this target. The three
    # provenance sources measure eccentricity by different methods and are not
    # poolable. None when no eccentricity values exist.
    ecc_excluded_count: int | None = None
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
    # HyperLEDA
    hubble_t_type: float | None = None
    inclination: float | None = None
    # Catalog memberships
    catalog_memberships: list[CatalogMembershipEntry] = []
    name_locked: bool = False
    user_defined: bool = False


class MetricBaseline(BaseModel):
    median: float | None = None
    mad: float | None = None
    n: int = 0


class GroupBaseline(BaseModel):
    median_hfr: MetricBaseline
    fwhm: MetricBaseline
    eccentricity: MetricBaseline
    detected_stars: MetricBaseline
    adu_median: MetricBaseline
    guiding_rms_arcsec: MetricBaseline


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
    # Plate-scale-converted session medians (arcsec); None without XPIXSZ/FOCALLEN.
    hfr_arcsec: float | None = None
    fwhm_arcsec: float | None = None
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
    session_baselines: dict[str, GroupBaseline] = {}
    rig_baselines: dict[str, GroupBaseline] = {}
    # Night+rig PHD2 guiding rollup, or None when no guide log covers this
    # night for this rig. Optional rather than an empty object so the client
    # can tell "no PHD2 data" from "PHD2 data showing zero problems".
    phd2: Phd2NightSummary | None = None


class EquipmentOption(BaseModel):
    name: str
    grouped: bool = False


class EquipmentResponse(BaseModel):
    cameras: list[EquipmentOption]
    telescopes: list[EquipmentOption]


class TargetSearchResultFuzzy(BaseModel):
    # Real targets carry their UUID; unresolved OBJECT-name groups (no target
    # row) carry the "obj:<name>" pseudo id used by the dashboard.
    id: uuid.UUID | str
    primary_name: str
    object_type: str | None = None
    aliases: list[str] = []
    match_source: str | None = None
    similarity_score: float = 1.0
    unresolved: bool = False
    image_count: int | None = None


class ObjectTypeCount(BaseModel):
    object_type: str
    count: int


class MergeCandidateResponse(BaseModel):
    id: uuid.UUID
    source_name: str
    source_image_count: int
    suggested_target_id: uuid.UUID | None = None
    suggested_target_name: str | None = None
    similarity_score: float
    method: str
    status: str
    created_at: str
    resolved_at: str | None = None
    reason_text: str | None = None


class OrphanPreviewRequest(BaseModel):
    source_name: str


class OrphanPreviewResponse(BaseModel):
    source_name: str
    resolved: bool
    primary_name: str
    catalog_id: str | None = None
    ra: float | None = None
    dec: float | None = None
    object_type: str | None = None
    constellation: str | None = None
    size_major: float | None = None
    size_minor: float | None = None
    position_angle: float | None = None
    v_mag: float | None = None


class OrphanCreateRequest(BaseModel):
    candidate_id: uuid.UUID
    primary_name: str
    ra: float | None = Field(default=None, ge=0, le=360)
    dec: float | None = Field(default=None, ge=-90, le=90)
    object_type: str | None = None
    catalog_id: str | None = None
    user_defined: bool = False
    aliases: list[str] = []


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


class MergePreviewRequest(BaseModel):
    winner_id: uuid.UUID
    loser_id: uuid.UUID | None = None
    loser_name: str | None = None


class MergePreviewSide(BaseModel):
    id: uuid.UUID | None = None
    primary_name: str
    object_type: str | None = None
    constellation: str | None = None
    image_count: int = 0
    session_count: int = 0
    integration_seconds: float = 0.0
    aliases: list[str] = []


class MergePreviewResponse(BaseModel):
    winner: MergePreviewSide
    loser: MergePreviewSide
    images_to_move: int = 0
    mosaic_panels_to_move: int = 0
    aliases_to_add: list[str] = []


class TargetIdentityRequest(BaseModel):
    primary_name: str | None = None
    object_type: str | None = None
    re_resolve: bool = False


class TargetIdentityResponse(BaseModel):
    id: UUID
    primary_name: str
    catalog_id: str | None
    common_name: str | None
    object_type: str | None
    name_locked: bool


class StatusResponse(BaseModel):
    status: str


class DuplicateDetectionResponse(BaseModel):
    status: str
    task_id: str


class OrphanCreateResponse(BaseModel):
    target_id: str


class CustomTargetCreateRequest(BaseModel):
    primary_name: str
    ra: float | None = Field(default=None, ge=0, le=360)
    dec: float | None = Field(default=None, ge=-90, le=90)
    object_type: str | None = None
    catalog_id: str | None = None
    user_defined: bool = True
    aliases: list[str] = []


class CustomTargetCreateResponse(BaseModel):
    target_id: str
    linked_candidates: int = 0
    linked_images: int = 0
