from pydantic import BaseModel, Field


class GeneralSettings(BaseModel):
    auto_scan_enabled: bool = True
    auto_scan_interval: int = 240
    thumbnail_width: int = 800
    default_page_size: int = 50
    include_calibration: bool = True
    filter_style: str = "text-only"
    theme: str = "deep-neutral"
    text_size: str = "medium"
    timezone: str = "UTC"
    astrobin_filter_ids: dict[str, int] = {}
    astrobin_bortle: int | None = None
    content_width: str = "full"
    mosaic_keywords: list[str] = ["Panel", "P"]
    mosaic_campaign_gap_days: int = 0


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


class GraphSettings(BaseModel):
    enabled_metrics: list[str] = Field(
        default_factory=lambda: ["hfr", "eccentricity", "fwhm", "guiding_rms"]
    )
    enabled_filters: list[str] = Field(default_factory=lambda: ["overall"])
    session_chart_expanded: bool = False
    target_chart_expanded: bool = False


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

