from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.services import phd2_profiles


def _validated_zone_name(value: str) -> str:
    """One IANA zone name, or a ValueError naming the one that is not.

    Shared by the global `observer_timezone` and by a profile's own timezone so
    the two cannot drift. Both decide which absolute instant a guide-log row is
    stored at, so the same typo does the same multi-hour damage whichever field
    carries it, and it has to be refused while the user is still looking at it.
    Empty is not a typo: it means "not configured" globally and "inherit the
    global" on a profile.
    """
    if not value:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"'{value}' is not a known IANA time zone") from exc
    return value


class Phd2ProfileMapping(BaseModel):
    """What one PHD2 equipment profile is mapped to.

    A guide log names the equipment profile that produced it and nothing else
    about the rig, so which telescope it is, which zone its wall-clock
    timestamps are in and where on Earth it stands are all user configuration.
    `app.services.phd2_profiles` owns this shape and every reader goes through
    it; this model is the same shape at the API boundary.

    `telescope: None` means the profile is not mapped to a telescope, and an
    entry survives without one so that unmapping a rig does not discard its
    zone and site. `timezone: ""` means inherit `observer_timezone`.
    `latitude: None` and `longitude: None` mean inherit the global observer
    coordinates. THE INHERIT MARKER FOR THE COORDINATES IS null, NEVER 0: zero
    is a legal longitude (Greenwich) and a legal latitude (the equator), so a
    falsy test on either field would move such a rig to the user's own site.

    The range bounds are the declared contract for a coordinate a client
    writes, and they reach the generated OpenAPI so the settings UI can bound
    its own inputs. They are not the whole story on the way in: the map's
    `mode="before"` normalizer on `GeneralSettings` runs first and degrades an
    unusable stored coordinate to None, because that same model is rebuilt from
    stored JSON on every settings read and no stored value may raise there.
    """

    telescope: str | None = None
    timezone: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        return _validated_zone_name(value)


# The six metrics a WBPP raw quality constraint can target. The names are
# FrameRecord fields, so a constraint indexes a frame directly on the client.
# The frontend counterpart is MetricKey + METRIC_DEFS in
# frontend/src/lib/wbppQualityFilter.ts, which speaks short keys ("hfr",
# "rms", ...) and maps each to the FrameRecord field named here; the older
# RAW_METRICS constant this comment used to name no longer exists.
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
    # a data error rather than a display preference. Empty means NOT
    # CONFIGURED, not "use the server's local zone": the correlation guard
    # treats an empty value as a configuration gap and declines to write
    # correlations rather than guess, and the server's own zone was never the
    # answer it looked like anyway, since inside the container it is UTC
    # whatever the host is set to. A profile may override this with a zone of
    # its own; see `phd2_profile_map` below.
    observer_timezone: str = ""
    # PHD2 guide-log discovery during the library scan. Cheap (a filename test
    # inside the existing walk) and on by default; the toggle exists for users
    # whose library happens to contain guide logs they do not want catalogued.
    phd2_scan_enabled: bool = True
    # Raw PHD2 equipment-profile name -> everything GalactiLog needs to read
    # that rig's logs: its telescope, its own timezone and its own site.
    # Several profile names may map to the same telescope; that is how two
    # names for one physical rig (a re-created profile, a renamed one) get
    # merged without touching the stored logs. An entry needs no telescope: one
    # carrying only a timezone or a coordinate is how a rig at another site
    # gets its clock and its night boundary right whether or not the user has
    # told GalactiLog which scope is on it.
    phd2_profile_map: dict[str, Phd2ProfileMapping] = {}
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

        An unknown zone reaching the ingest is a silent multi-hour error on
        every guide session it then stores, so the typo has to be refused while
        the user is still looking at it.
        """
        return _validated_zone_name(value)

    @field_validator("phd2_profile_map", mode="before")
    @classmethod
    def _normalize_phd2_profile_map(cls, value: Any) -> Any:
        """Every stored form of the profile map, in the one canonical form.

        Runs before the per-entry model, so the legacy `{"Rig A": "Askar 120"}`
        that every install stored before per-rig timezones existed loads here
        without waiting for a data migration, and the next save writes the new
        shape (`update_general` persists `payload.model_dump()`).

        The coercion is `phd2_profiles.normalize_profile_map`, which is where
        the shape is defined and where every non-API reader gets it from, so
        the boundary cannot drift from the storage. It degrades rather than
        raises, which is required of this field: `GeneralSettings` is rebuilt
        from the stored JSON on every settings read and on every PHD2 pass, so
        a junk map value must not be able to take the response down.
        """
        return phd2_profiles.normalize_profile_map(value)


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

