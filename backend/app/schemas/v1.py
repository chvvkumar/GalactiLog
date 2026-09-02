"""Response models for the public /api/v1 surface.

Deliberately narrower than the SPA schemas in app/schemas/: nothing here
carries a filesystem path, a raw FITS header blob, merge bookkeeping
(matched_sessions / name_locked / needs_review), custom column values,
session insights or metric baselines. When a field is added to an internal
schema it does NOT appear here until it is added on purpose.

Class names must be unique across every module in app/schemas/: FastAPI keys
OpenAPI components off the bare class name, so a duplicate silently
overwrites the other model in the generated schema and client. Hence the
`V1` prefix on the three names that would otherwise collide with
schemas/mosaic.py, schemas/stats.py and schemas/target.py. New models here
take the prefix only when they actually collide -
tests/test_schema_name_collisions.py is the check.
"""

from pydantic import BaseModel


class Position(BaseModel):
    ra: float | None = None
    dec: float | None = None


# --- Targets ---------------------------------------------------------------

class TargetSummary(BaseModel):
    id: str
    name: str
    other_names: list[str] = []
    catalog_id: str | None = None
    common_name: str | None = None
    position: Position
    object_type: str | None = None
    total_integration_seconds: float
    total_frames: int
    # Seconds of integration per filter, as the aggregation service computes it.
    filter_totals: dict[str, float] = {}
    equipment: list[str] = []
    first_night: str | None = None
    last_night: str | None = None


class TargetPage(BaseModel):
    items: list[TargetSummary]
    page: int
    page_size: int
    total: int


class TargetDetail(TargetSummary):
    constellation: str | None = None
    v_mag: float | None = None
    surface_brightness: float | None = None
    distance_pc: float | None = None
    size_major: float | None = None
    size_minor: float | None = None
    position_angle: float | None = None
    session_count: int = 0
    filters_used: list[str] = []
    avg_hfr: float | None = None
    avg_hfr_arcsec: float | None = None
    avg_fwhm_arcsec: float | None = None
    avg_eccentricity: float | None = None
    avg_guiding_rms_arcsec: float | None = None
    avg_detected_stars: float | None = None
    catalog_description: str | None = None
    catalog_notes: str | None = None
    notes: str | None = None


# --- Sessions --------------------------------------------------------------

class V1SessionSummary(BaseModel):
    date: str
    frames: int
    integration_seconds: float
    filters: list[str] = []
    equipment: list[str] = []


class SessionFilter(BaseModel):
    filter: str
    frames: int
    integration_seconds: float
    exposure_seconds: float | None = None
    median_hfr: float | None = None
    median_eccentricity: float | None = None


class SessionDetail(BaseModel):
    target_name: str
    date: str
    frames: int
    integration_seconds: float
    equipment: dict[str, str | None] = {}
    filters: list[SessionFilter] = []
    gain: int | None = None
    offset: int | None = None
    sensor_temp: float | None = None
    exposure_seconds: list[float] = []
    first_frame_time: str | None = None
    last_frame_time: str | None = None
    median_hfr: float | None = None
    hfr_arcsec: float | None = None
    # Already arcseconds at rest; never plate-scaled.
    fwhm_arcsec: float | None = None
    median_eccentricity: float | None = None
    median_detected_stars: float | None = None
    median_guiding_rms_arcsec: float | None = None
    median_airmass: float | None = None
    median_ambient_temp: float | None = None
    median_humidity: float | None = None
    median_cloud_cover: float | None = None
    notes: str | None = None


# --- Frames ----------------------------------------------------------------

class Frame(BaseModel):
    id: str
    capture_time: str | None = None
    session_date: str | None = None
    filter: str | None = None
    exposure_seconds: float | None = None
    telescope: str | None = None
    camera: str | None = None
    hfr: float | None = None
    hfr_stdev: float | None = None
    # Arcseconds as stored (N.I.N.A. Session Metadata CSV). Never rescaled.
    fwhm_arcsec: float | None = None
    eccentricity: float | None = None
    eccentricity_source: str | None = None
    star_count: int | None = None
    guiding_rms_arcsec: float | None = None
    guiding_rms_ra_arcsec: float | None = None
    guiding_rms_dec_arcsec: float | None = None
    guiding_rms_source: str | None = None
    adu_mean: float | None = None
    adu_median: float | None = None
    adu_stdev: float | None = None
    sky_quality: float | None = None
    gain: int | None = None
    sensor_temp: float | None = None
    focuser_position: int | None = None
    focuser_temp: float | None = None
    altitude_deg: float | None = None
    airmass: float | None = None
    ambient_temp: float | None = None
    humidity: float | None = None
    cloud_cover: float | None = None


class FramePage(BaseModel):
    items: list[Frame]
    page: int
    page_size: int
    total: int


# --- Search / nights -------------------------------------------------------

class SearchHit(BaseModel):
    id: str
    name: str
    other_names: list[str] = []
    match: str | None = None
    score: float = 1.0


class Night(BaseModel):
    date: str
    integration_seconds: float
    targets: int
    frames: int


# --- Stats -----------------------------------------------------------------

class StatsTotals(BaseModel):
    targets: int
    frames: int
    integration_seconds: float
    nights: int


class StatsSite(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    bortle: int | None = None


class EquipmentCount(BaseModel):
    name: str
    frame_count: int
    integration_seconds: float = 0


class V1TopTarget(BaseModel):
    name: str
    integration_seconds: float


class StatsOverview(BaseModel):
    totals: StatsTotals
    top_targets: list[V1TopTarget] = []
    filter_usage: dict[str, float] = {}
    cameras: list[EquipmentCount] = []
    telescopes: list[EquipmentCount] = []
    site: StatsSite | None = None


# --- Mosaics ---------------------------------------------------------------

class V1MosaicSummary(BaseModel):
    id: str
    name: str
    notes: str | None = None
    panel_count: int
    total_integration_seconds: float
    total_frames: int
    completion_pct: float
    first_session: str | None = None
    last_session: str | None = None


class MosaicPanel(BaseModel):
    panel_id: str
    target_id: str
    target_name: str
    panel_label: str
    sort_order: int
    position: Position
    total_integration_seconds: float
    total_frames: int
    filter_totals: dict[str, float] = {}
    last_session_date: str | None = None


class MosaicDetail(BaseModel):
    id: str
    name: str
    notes: str | None = None
    total_integration_seconds: float
    total_frames: int
    available_filters: list[str] = []
    panels: list[MosaicPanel] = []


# --- Export ----------------------------------------------------------------
# Projected rather than reusing schemas/export.py: that model answers to the
# SPA's export tab, so a rename there would silently redefine this public
# contract.

class V1ExportRow(BaseModel):
    date: str
    filter: str
    astrobin_filter_id: int | None = None
    frames: int
    exposure_seconds: float
    total_seconds: float
    gain: int | None = None
    sensor_temp: int | None = None
    fwhm_arcsec: float | None = None
    sky_quality: float | None = None
    ambient_temp: float | None = None


class V1ExportEquipment(BaseModel):
    telescope: str | None = None
    camera: str | None = None


class V1ExportCalibration(BaseModel):
    darks: int
    flats: int
    bias: int


class V1Export(BaseModel):
    target_name: str
    catalog_id: str | None = None
    equipment: list[V1ExportEquipment] = []
    dates: list[str] = []
    rows: list[V1ExportRow] = []
    calibration: V1ExportCalibration
    total_integration_seconds: float
    bortle: int | None = None


# --- Guiding ---------------------------------------------------------------
# Projected rather than reusing schemas/stats_guiding.py for the same reason:
# that module's docstring calls its field names load-bearing for the frontend
# Guiding section, which is exactly what makes it unsafe to publish verbatim.

class V1GuidingRig(BaseModel):
    telescope: str
    session_count: int
    gated_session_count: int
    guided_hours: float
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None
    rms_total_filtered_arcsec: float | None = None
    ra_dec_ratio: float | None = None
    settle_median_s: float | None = None
    exposure_ms_values: list[int] = []


class V1GuidingAltitudeBand(BaseModel):
    telescope: str
    band: str
    session_count: int
    rms_total_arcsec: float | None = None
    rms_ra_arcsec: float | None = None
    rms_dec_arcsec: float | None = None


class V1Guiding(BaseModel):
    unmapped_session_count: int
    rigs: list[V1GuidingRig] = []
    altitude_bands: list[V1GuidingAltitudeBand] = []


# --- Scan ------------------------------------------------------------------

class ScanStatus(BaseModel):
    state: str
    running: bool
    pending_rescan: bool = False
    started_at: float | None = None
    completed_at: float | None = None
    discovered: int = 0
    total: int = 0
    completed: int = 0
    failed: int = 0
    percent: float = 0.0
    message: str = ""


class ScanAccepted(BaseModel):
    # "started" when this call dispatched a scan, "queued" when one was
    # already running and a rescan was recorded to follow it.
    status: str
