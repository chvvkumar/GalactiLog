from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


# The six metrics a WBPP raw quality constraint can target. Mirrors RAW_METRICS
# in frontend/src/lib/wbppQualityFilter.ts; the names are FrameRecord fields, so
# a constraint indexes a frame directly on the client.
WbppRawMetric = Literal[
    "median_hfr",
    "fwhm",
    "eccentricity",
    "detected_stars",
    "guiding_rms_arcsec",
    "adu_median",
]


class WbppRawConstraint(BaseModel):
    """One raw-metric threshold in the WBPP export's quality filter.

    Direction is not stored: it is a property of the metric (only detected_stars
    is higher-is-better) and is derived on the client from HIGHER_IS_BETTER. A
    stored direction could contradict the metric.
    """

    metric: WbppRawMetric
    value: float


class GeneralSettings(BaseModel):
    auto_scan_enabled: bool = True
    auto_scan_interval: int = 240
    thumbnail_width: int = 800
    default_page_size: int = 50
    include_calibration: bool = False
    filter_style: str = "text-only"
    theme: str = "glass-void"
    text_size: str = "large"
    timezone: str = "UTC"
    use_24h_time: bool = False
    astrobin_filter_ids: dict[str, int] = {}
    astrobin_bortle: int | None = None
    content_width: str = "extra-wide"
    mosaic_keywords: list[str] = ["Panel", "P"]
    mosaic_campaign_gap_days: int = 0
    # Position tolerance for mosaic panel grouping, in arcmin.
    # 0 = derive adaptively from per-rig FOV (fallback ~12 arcmin).
    mosaic_position_tolerance_arcmin: float = 0
    observer_latitude: float | None = None
    observer_longitude: float | None = None
    observer_name: str | None = None
    use_imaging_night: bool = True
    # IANA zone name (e.g. "America/New_York") for interpreting PHD2 guide-log
    # timestamps, which are local wall-clock with no zone marker. Not the same
    # thing as `timezone` above: that one only formats already-absolute
    # instants for display and can be changed at will, while this one decides
    # which absolute instant a guide-log row is stored at, so a wrong value is
    # a data error rather than a display preference. Empty means "use the
    # server's local zone", which is correct for the common single-machine
    # install and is the only answer available before the user configures
    # anything.
    observer_timezone: str = ""
    # PHD2 guide-log discovery during the library scan. Cheap (a filename test
    # inside the existing walk) and on by default; the toggle exists for users
    # whose library happens to contain guide logs they do not want catalogued.
    phd2_scan_enabled: bool = True
    # Raw PHD2 equipment-profile name -> images.telescope value. Several
    # profile names may map to the same telescope; that is how two names for
    # one physical rig (a re-created profile, a renamed one) get merged
    # without touching the stored logs.
    phd2_profile_map: dict[str, str] = {}
    preview_resolution: int = 2400  # 0 means native full resolution
    preview_cache_mb: int = 2048
    activity_retention_days: int = Field(default=90, ge=1, le=3650)
    app_log_capture_level: str = Field(default="warning", pattern="^(debug|info|warning|error)$")
    app_log_retention_days: int = Field(default=14, ge=1, le=3650)
    app_log_max_rows: int = Field(default=50000, ge=1000, le=5000000)
    nina_instances: list[dict] = Field(default_factory=list)
    stellarium_instances: list[dict] = Field(default_factory=list)
    # WBPP export preferences
    wbpp_library_root: str | None = None
    wbpp_default_os: str | None = None          # "windows" | "posix" | None (auto-detect)
    wbpp_staging_path: str | None = None
    wbpp_exclusions: list[str] = Field(
        default_factory=lambda: [
            "WBPP", "PixInsight", "finals", "WORK_AREA",
            "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
        ]
    )
    # WBPP export quality filter. Persisted so tuning survives a modal close and
    # a reload, rather than being redone by hand on every export. The defaults
    # below are the modal's own starting state, so a user who has never touched
    # the filter reads back exactly what they would have seen before it was
    # stored.
    wbpp_quality_enabled: bool = False
    wbpp_quality_mode: str = Field(default="score", pattern="^(score|raw)$")
    wbpp_quality_score_threshold: int = Field(default=60, ge=0, le=100)
    wbpp_quality_baseline: str = Field(default="session", pattern="^(session|rig)$")
    wbpp_quality_raw_constraints: list[WbppRawConstraint] = Field(default_factory=list)

    @field_validator("observer_timezone")
    @classmethod
    def _validate_observer_timezone(cls, value: str) -> str:
        """Reject a zone name ZoneInfo cannot load.

        The ingest degrades an unknown zone to the server's local zone, which
        is a silent multi-hour error on every guide session it then stores, so
        the typo has to be refused while the user is still looking at it.
        """
        if not value:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"'{value}' is not a known IANA time zone") from exc
        return value


class ActivitySettingsResponse(BaseModel):
    activity_retention_days: int
    app_log_capture_level: str
    app_log_retention_days: int
    app_log_max_rows: int


class ActivitySettingsUpdate(BaseModel):
    # `retention_days` is the legacy key the frontend currently sends for the
    # activity-event retention; `activity_retention_days` is accepted too.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    activity_retention_days: int | None = Field(default=None, ge=1, le=3650)
    app_log_capture_level: str | None = Field(default=None, pattern="^(debug|info|warning|error)$")
    app_log_retention_days: int | None = Field(default=None, ge=1, le=3650)
    app_log_max_rows: int | None = Field(default=None, ge=1000, le=5000000)


class FilterConfig(BaseModel):
    color: str = "#808080"
    aliases: list[str] = Field(default_factory=list)


class EquipmentAliases(BaseModel):
    aliases: list[str] = Field(default_factory=list)


class EquipmentConfig(BaseModel):
    cameras: dict[str, EquipmentAliases] = Field(default_factory=dict)
    telescopes: dict[str, EquipmentAliases] = Field(default_factory=dict)


class MetricGroupSettings(BaseModel):
    enabled: bool
    fields: dict[str, bool]


class DisplaySettings(BaseModel):
    quality: MetricGroupSettings
    guiding: MetricGroupSettings
    adu: MetricGroupSettings
    focuser: MetricGroupSettings
    weather: MetricGroupSettings
    mount: MetricGroupSettings


class TableColumnVisibility(BaseModel):
    builtin: dict[str, bool] = {}
    custom: dict[str, bool] = {}


class ColumnVisibility(BaseModel):
    dashboard: TableColumnVisibility = TableColumnVisibility()
    session_table: TableColumnVisibility = TableColumnVisibility()
    session_detail: TableColumnVisibility = TableColumnVisibility()
    mosaic_table: TableColumnVisibility = TableColumnVisibility()


class GraphSettings(BaseModel):
    enabled_metrics: list[str] = Field(
        default_factory=lambda: ["hfr", "eccentricity", "fwhm", "guiding_rms"]
    )
    enabled_filters: list[str] = Field(default_factory=lambda: ["overall"])
    session_chart_expanded: bool = False
    target_chart_expanded: bool = False
    default_chart_sessions: int = 1


def default_graph_settings() -> GraphSettings:
    return GraphSettings()


def default_display_settings() -> DisplaySettings:
    return DisplaySettings(
        quality=MetricGroupSettings(
            enabled=True,
            fields={"hfr": True, "hfr_stdev": True, "fwhm": True, "eccentricity": True, "detected_stars": True},
        ),
        guiding=MetricGroupSettings(
            enabled=True,
            fields={"rms_total": True, "rms_ra": True, "rms_dec": True},
        ),
        adu=MetricGroupSettings(
            enabled=False,
            fields={"mean": True, "median": True, "stdev": True, "min": True, "max": True},
        ),
        focuser=MetricGroupSettings(
            enabled=False,
            fields={"position": True, "temp": True},
        ),
        weather=MetricGroupSettings(
            enabled=False,
            fields={"ambient_temp": True, "dew_point": True, "humidity": True, "pressure": True, "wind_speed": True, "wind_direction": True, "wind_gust": True, "cloud_cover": True, "sky_quality": True},
        ),
        mount=MetricGroupSettings(
            enabled=False,
            fields={"airmass": True, "pier_side": True, "rotator_position": True},
        ),
    )


class SettingsResponse(BaseModel):
    general: GeneralSettings
    filters: dict[str, FilterConfig]
    equipment: EquipmentConfig
    dismissed_suggestions: list[list[str]] = Field(default_factory=list)
    display: DisplaySettings = Field(default_factory=default_display_settings)
    graph: GraphSettings = Field(default_factory=default_graph_settings)


class SuggestionGroup(BaseModel):
    group: list[str]
    counts: dict[str, int]
    section: str | None = None  # "cameras" or "telescopes" for equipment suggestions


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionGroup]


class DiscoveredItem(BaseModel):
    name: str
    count: int


class DiscoveredResponse(BaseModel):
    items: list[DiscoveredItem]

