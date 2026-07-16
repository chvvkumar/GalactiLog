// Thin alias layer over the generated OpenAPI schema (./generated/schema.ts).
// This is the small replacement for the 1115-line hand-written
// `frontend/src/types/index.ts` -- every later T3/T5 slice repoints its
// `../types` imports here, mechanically, one file at a time. Do NOT add new
// hand-written server-DTO interfaces here; if a name is missing, add the
// alias (or, for the small set of client-only types below, extend that
// section) rather than redefining a server shape by hand.
//
// Two kinds of exports:
//   1. Aliases: `export type X = components["schemas"]["Y"]` -- one per
//      server DTO. Where the generated schema's name differs from the old
//      hand-written name (noted inline), the OLD name is kept as the export
//      so call-site repoints are a pure import-path change, not a rename.
//   2. Client-only types: interfaces with no server-schema equivalent
//      (frontend-only state shapes, or convenience request-param bags that
//      the OpenAPI spec expresses as flattened query parameters rather than
//      a named schema). These are moved here verbatim from the old
//      `types/index.ts` / `client.ts`.
//
// KNOWN DISCREPANCIES vs. the old hand-written types (flagged for slices that
// consume them -- see slice-0-report.md for detail):
//   - BootstrapResponse: the generated schema types `settings` as a loose
//     `Record<string, unknown>` and `equipment` as `BootstrapEquipment`
//     (cameras/telescopes of `{name, grouped}`), not the full `SettingsResponse`/
//     `EquipmentList` the hand-written type claimed. Slice 3 (SettingsProvider)
//     must account for this when consuming `getBootstrap`.
//   - ScanStatus (-> ScanStateResponse): `failed_files` is `string[]` in the
//     generated schema, not `FailedFile[]` ({file, error}) as hand-written.
//     `FailedFile` is kept below as a client-only type in case a slice still
//     needs the richer shape from a different endpoint.

import type { components } from "./generated/schema";
import type { Baselines } from "../utils/frameQuality";

type Schemas = components["schemas"];

// === Target Aggregation ===
// SessionSummary/TargetAggregation/AggregateStats/TargetAggregationResponse are
// hand-written (not `Schemas[...]` aliases) -- the generated schema loosens
// `TargetAggregation.catalog_id`/`user_defined` optionality vs. what
// DashboardFilterProvider.tsx (the sole fetch boundary), TargetRow.tsx, and
// TargetTable.tsx have always assumed. Moved verbatim from the old
// `types/index.ts` in Slice 15 (formerly cast at the fetch boundary via
// `as Promise<TargetAggregationResponse>`); the backend always populates the
// full shape, so this is not a runtime behavior change.
export interface SessionSummary {
  session_date: string;
  integration_seconds: number;
  frame_count: number;
  filters_used: string[];
  median_hfr: number | null;
  median_eccentricity: number | null;
}

export interface TargetAggregation {
  target_id: string;
  primary_name: string;
  catalog_id: string | null;
  aliases: string[];
  total_integration_seconds: number;
  total_frames: number;
  filter_distribution: Record<string, number>;
  equipment: string[];
  sessions: SessionSummary[];
  matched_sessions?: number | null;
  total_sessions?: number | null;
  mosaic_id: string | null;
  mosaic_name: string | null;
  custom_values?: Record<string, string> | null;
  user_defined?: boolean;
}

export interface AggregateStats {
  total_integration_seconds: number;
  target_count: number;
  total_frames: number;
  disk_usage_bytes: number;
  oldest_date: string | null;
  newest_date: string | null;
}

export interface TargetAggregationResponse {
  targets: TargetAggregation[];
  aggregates: AggregateStats;
  total_count: number;
  page: number;
  page_size: number;
}

// === Session Detail ===
// Hand-written (not `Schemas[...]` aliases): the generated schema types many
// numeric baseline fields as `number | null | undefined` (vs. the required
// `number | null` these interfaces have always declared) and
// `session_baselines`/`rig_baselines` as untyped records rather than
// `Baselines` (utils/frameQuality.ts). SessionAccordionCard.tsx's
// frame-quality math and TargetDetailPage.tsx's formatting helpers depend on
// the stricter shape. Moved verbatim from the old `types/index.ts` in
// Slice 15; the backend always populates the full shape.
export interface SessionDetail {
  target_name: string;
  session_date: string;
  thumbnail_url: string | null;
  frame_count: number;
  integration_seconds: number;
  median_hfr: number | null;
  median_eccentricity: number | null;
  filters_used: Record<string, number>;
  equipment: { camera: string | null; telescope: string | null };
  raw_reference_header: Record<string, unknown> | null;
  min_hfr: number | null;
  max_hfr: number | null;
  min_eccentricity: number | null;
  max_eccentricity: number | null;
  sensor_temp: number | null;
  sensor_temp_min: number | null;
  sensor_temp_max: number | null;
  gain: number | null;
  offset: number | null;
  exposure_times: number[];
  first_frame_time: string | null;
  last_frame_time: string | null;
  filter_details: FilterDetail[];
  insights: SessionInsight[];
  frames: FrameRecord[];
  median_fwhm: number | null;
  min_fwhm: number | null;
  max_fwhm: number | null;
  median_guiding_rms: number | null;
  min_guiding_rms: number | null;
  max_guiding_rms: number | null;
  median_detected_stars: number | null;
  median_airmass: number | null;
  median_ambient_temp: number | null;
  median_humidity: number | null;
  median_cloud_cover: number | null;
  notes: string | null;
  rigs: RigDetail[];
  custom_values?: CustomColumnValue[] | null;
  session_baselines: Baselines;
  rig_baselines: Baselines;
}

export interface FilterMedian {
  filter_name: string;
  median_hfr: number | null;
  median_eccentricity: number | null;
  median_fwhm: number | null;
  median_guiding_rms: number | null;
  median_detected_stars: number | null;
}

export interface SessionOverview {
  session_date: string;
  integration_seconds: number;
  frame_count: number;
  median_hfr: number | null;
  median_eccentricity: number | null;
  filters_used: string[];
  camera: string | null;
  telescope: string | null;
  median_fwhm: number | null;
  median_detected_stars: number | null;
  median_guiding_rms_arcsec: number | null;
  filter_medians: FilterMedian[];
  has_notes: boolean;
  rig_count: number;
  custom_values?: Record<string, string> | null;
  ra: number | null;
  dec: number | null;
  position_angle: number | null;
}

export interface TargetDetailResponse {
  target_id: string;
  primary_name: string;
  aliases: string[];
  object_type: string | null;
  object_category: string | null;
  constellation: string | null;
  ra: number | null;
  dec: number | null;
  position_angle: number | null;
  size_major: number | null;
  size_minor: number | null;
  v_mag: number | null;
  surface_brightness: number | null;
  total_integration_seconds: number;
  total_frames: number;
  avg_hfr: number | null;
  avg_eccentricity: number | null;
  filters_used: string[];
  equipment: string[];
  first_session_date: string;
  last_session_date: string;
  session_count: number;
  sessions: SessionOverview[];
  avg_fwhm: number | null;
  avg_guiding_rms_arcsec: number | null;
  avg_detected_stars: number | null;
  notes: string | null;
  sac_description: string | null;
  sac_notes: string | null;
  reference_thumbnail_path: string | null;
  distance_pc: number | null;
  catalog_memberships: CatalogMembershipEntry[];
  name_locked: boolean;
  user_defined: boolean;
}

export interface RigDetail {
  rig_label: string;
  telescope: string | null;
  camera: string | null;
  frame_count: number;
  integration_seconds: number;
  median_hfr: number | null;
  median_eccentricity: number | null;
  median_fwhm: number | null;
  median_guiding_rms: number | null;
  median_detected_stars: number | null;
  gain: number | null;
  offset: number | null;
  exposure_times: number[];
  filter_details: FilterDetail[];
  frames: FrameRecord[];
  thumbnail_url: string | null;
}

export interface FilterDetail {
  filter_name: string;
  frame_count: number;
  integration_seconds: number;
  median_hfr: number | null;
  median_eccentricity: number | null;
  exposure_time: number | null;
}

export interface SessionInsight {
  level: "good" | "warning" | "info";
  message: string;
}

export interface FrameRecord {
  timestamp: string;
  filter_used: string | null;
  exposure_time: number | null;
  median_hfr: number | null;
  eccentricity: number | null;
  sensor_temp: number | null;
  gain: number | null;
  file_name: string;
  image_id: string;
  file_path: string;
  source_relative: string;
  thumbnail_url?: string | null;
  hfr_stdev: number | null;
  fwhm: number | null;
  detected_stars: number | null;
  guiding_rms_arcsec: number | null;
  guiding_rms_ra_arcsec: number | null;
  guiding_rms_dec_arcsec: number | null;
  adu_stdev: number | null;
  adu_mean: number | null;
  adu_median: number | null;
  adu_min: number | null;
  adu_max: number | null;
  focuser_position: number | null;
  focuser_temp: number | null;
  rotator_position: number | null;
  pier_side: string | null;
  airmass: number | null;
  ambient_temp: number | null;
  dew_point: number | null;
  humidity: number | null;
  pressure: number | null;
  wind_speed: number | null;
  wind_direction: number | null;
  wind_gust: number | null;
  cloud_cover: number | null;
  sky_quality: number | null;
  rig: string | null;
}

// === Equipment === (generated name: EquipmentResponse)
export type EquipmentOption = Schemas["EquipmentOption"];
export type EquipmentList = Schemas["EquipmentResponse"];

// === Scan ===
// generated name: ScanQueueResponse (POST /scan, /scan/reset, /scan/stop, etc.)
export type ScanResult = Schemas["ScanQueueResponse"];
// Hand-written (not a `Schemas[...]` alias): the generated ScanStateResponse
// flattens `failed_files` to `string[]` and drops the narrow `state` literal
// union. Moved verbatim from the old `types/index.ts` in Slice 15 (formerly
// cast at the store/scan.ts fetch boundary); the backend always populates
// the full shape.
export interface ScanStatus {
  state: "idle" | "scanning" | "ingesting" | "complete" | "stalled";
  total: number;
  completed: number;
  failed: number;
  csv_enriched: number;
  discovered: number;
  started_at: number | null;
  completed_at: number | null;
  new_files: number;
  changed_files: number;
  removed: number;
  skipped_calibration: number;
  failed_files?: FailedFile[];
  task?: string;
  step?: number;
  total_steps?: number;
  percent?: number;
  message?: string;
}

// === Activity === (generated name: ActivityItem)
export type ActivityEvent = Schemas["ActivityItem"];
// generated name: PaginatedActivityResponse
export type ActivityPageResponse = Schemas["PaginatedActivityResponse"];
// Hand-written (not `Schemas["RebuildStatusResponse"]`): the generated
// schema marks `percent`/`step`/`total_steps` as `number | null` (vs. the
// required-absent `number | undefined` this interface has always declared)
// and drops the narrow `state` literal union. store/activeJobs.ts depends
// on the stricter shape. Moved verbatim from the old `types/index.ts` in
// Slice 15; the backend always populates the full shape.
export interface RebuildStatus {
  state: "idle" | "running" | "complete" | "error";
  mode: string;
  message: string;
  started_at: number | null;
  completed_at: number | null;
  details: Record<string, number>;
  step?: number;
  total_steps?: number;
  percent?: number;
}
// generated name: DbSummaryResponse
export type DbSummary = Schemas["DbSummaryResponse"];

// === Search ===
export type TargetSearchResultFuzzy = Schemas["TargetSearchResultFuzzy"];
export type ObjectTypeCount = Schemas["ObjectTypeCount"];

// === Bootstrap === (see discrepancy note above)
export type BootstrapResponse = Schemas["BootstrapResponse"];

export type MergeCandidateResponse = Schemas["MergeCandidateResponse"];
export type MergePreviewResponse = Schemas["MergePreviewResponse"];
export type MergePreviewSide = Schemas["MergePreviewSide"];
export type OrphanPreviewResponse = Schemas["OrphanPreviewResponse"];
export type OrphanCreateRequest = Schemas["OrphanCreateRequest"];
export type CustomTargetCreateRequest = Schemas["CustomTargetCreateRequest"];
export type CustomTargetCreateResponse = Schemas["CustomTargetCreateResponse"];
export type MergedTargetResponse = Schemas["MergedTargetResponse"];
export type FilenameCandidateResponse = Schemas["FilenameCandidateResponse"];

// === Stats (Admin) ===
export type EquipmentItem = Schemas["EquipmentItem"];
export type TimelineEntry = Schemas["TimelineEntry"];
export type TimelineDetailEntry = Schemas["TimelineDetailEntry"];
export type SiteCoords = Schemas["SiteCoords"];
export type TopTarget = Schemas["TopTarget"];
export type HfrBucket = Schemas["HfrBucket"];
export type EquipmentFilterMetrics = Schemas["EquipmentFilterMetrics"];
export type EquipmentComboMetrics = Schemas["EquipmentComboMetrics"];
export type OverviewStats = Schemas["OverviewStats"];
export type StatsResponse = Schemas["StatsResponse"];

// === Calendar ===
export type CalendarEntry = Schemas["CalendarEntry"];

// === Catalog Memberships ===
export type CatalogMembershipEntry = Schemas["CatalogMembershipEntry"];

// === Settings ===
export type MetricGroupSettings = Schemas["MetricGroupSettings"];
export type DisplaySettings = Schemas["DisplaySettings"];
// GeneralSettings/FilterConfig/EquipmentAliases/EquipmentConfig/GraphSettings/
// SettingsResponse below are hand-written (not `Schemas[...]` aliases): the
// generated schema loosens `GeneralSettings.nina_instances`/
// `stellarium_instances` to untyped arrays, `FilterConfig.aliases` and
// `GraphSettings.enabled_metrics`/`enabled_filters` to optional, and
// `CustomColumnResponse.column_type`/`applies_to` to plain `string`.
// SettingsProvider.tsx (consumed by nearly every page),
// CustomColumnsTab/CustomColumnFilters/TargetRow/TargetTable/MosaicsTab/
// MosaicDetailPage/EquipmentTab/FiltersTab/SessionAccordionCard depend on
// the stricter shape. Moved verbatim from the old `types/index.ts` in
// Slice 15; the backend always populates the full shape.
export interface GeneralSettings {
  auto_scan_enabled: boolean;
  auto_scan_interval: number;
  thumbnail_width: number;
  default_page_size: number;
  include_calibration: boolean;
  filter_style: string;
  theme: string;
  text_size: string;
  timezone: string;
  use_24h_time: boolean;
  astrobin_filter_ids?: Record<string, number>;
  astrobin_bortle?: number | null;
  content_width: string;
  mosaic_keywords?: string[];
  mosaic_campaign_gap_days?: number;
  observer_latitude?: number | null;
  observer_longitude?: number | null;
  observer_name?: string | null;
  use_imaging_night?: boolean;
  preview_resolution?: number;
  preview_cache_mb?: number;
  nina_instances?: IntegrationInstance[];
  stellarium_instances?: IntegrationInstance[];
  wbpp_library_root?: string | null;
  wbpp_default_os?: string | null;
  wbpp_staging_path?: string | null;
  wbpp_exclusions?: string[];
}

export interface FilterConfig {
  color: string;
  aliases: string[];
}

export interface EquipmentAliases {
  aliases: string[];
}

export interface EquipmentConfig {
  cameras: Record<string, EquipmentAliases>;
  telescopes: Record<string, EquipmentAliases>;
}

export interface GraphSettings {
  enabled_metrics: string[];
  enabled_filters: string[];
  session_chart_expanded: boolean;
  target_chart_expanded: boolean;
  default_chart_sessions: number;
}

export interface SettingsResponse {
  general: GeneralSettings;
  filters: Record<string, FilterConfig>;
  equipment: EquipmentConfig;
  dismissed_suggestions: string[][];
  display: DisplaySettings;
  graph: GraphSettings;
}

// Loose generated-schema counterpart of `GeneralSettings` above, used only to
// cast the PUT /api/settings/general request body (store/settings.ts). The
// generated schema marks several Pydantic-default fields
// (activity_retention_days, app_log_*, mosaic_position_tolerance_arcmin) as
// required on the request type even though the backend supplies defaults and
// tolerates a body that omits them -- the hand-written `GeneralSettings`
// above (and every caller of saveGeneral) has never included these fields.
export type GeneratedGeneralSettings = Schemas["GeneralSettings"];

// === Auth === (generated name: MeResponse / UserResponse)
export type AuthUser = Schemas["MeResponse"];
export type LoginResponse = Schemas["LoginResponse"];
export type UserAccount = Schemas["UserResponse"];
export type SuggestionGroup = Schemas["SuggestionGroup"];
export type SuggestionsResponse = Schemas["SuggestionsResponse"];
export type DiscoveredItem = Schemas["DiscoveredItem"];
export type DiscoveredResponse = Schemas["DiscoveredResponse"];

// === Analysis ===
export type SummaryStats = Schemas["SummaryStats"];
// CorrelationPoint/CorrelationResponse and TimeSeriesPoint/TimeSeriesResponse
// below are hand-written (not `Schemas[...]` aliases): the generated schema
// marks `CorrelationPoint.target_id`/`TimeSeriesPoint.target_name` as
// `string | null | undefined` (an OpenAPI-optionality gap) where these have
// always been `string | null`. CorrelationChart.tsx/TimeSeriesChart.tsx
// depend on the stricter shape. Moved verbatim from the old
// `types/index.ts` in Slice 15 (formerly cast at the CorrelationTab.tsx /
// TimeSeriesTab.tsx fetch boundary); the backend always populates the field.
export interface CorrelationPoint {
  x: number;
  y: number;
  date: string;
  target_id: string | null;
  outlier: boolean;
}

export interface ConfidenceBandPoint {
  x: number;
  y: number;
}

export interface TrendLine {
  slope: number;
  intercept: number;
  r_squared: number;
  pearson_r: number;
  spearman_rho: number;
  confidence_upper: ConfidenceBandPoint[];
  confidence_lower: ConfidenceBandPoint[];
}

export interface CorrelationResponse {
  points: CorrelationPoint[];
  trend: TrendLine | null;
  x_metric: string;
  y_metric: string;
  granularity: string;
  x_stats: SummaryStats | null;
  y_stats: SummaryStats | null;
  target_names: Record<string, string>;
  total_count?: number;
  sampled_count?: number;
}

export type HistogramBin = Schemas["HistogramBin"];
export type DistributionResponse = Schemas["DistributionResponse"];
export type BoxPlotGroup = Schemas["BoxPlotGroup"];
export type BoxPlotResponse = Schemas["BoxPlotResponse"];

export interface TimeSeriesPoint {
  date: string;
  value: number;
  target_name: string | null;
  frame_count: number;
}

export interface MovingAveragePoint {
  date: string;
  value: number;
}

export interface TimeSeriesResponse {
  points: TimeSeriesPoint[];
  ma_7: MovingAveragePoint[];
  ma_30: MovingAveragePoint[];
  metric: string;
  month_boundaries: string[];
}

export type MatrixCell = Schemas["MatrixCell"];
export type MatrixResponse = Schemas["MatrixResponse"];
export type CompareGroupStats = Schemas["CompareGroupStats"];
export type CompareResponse = Schemas["CompareResponse"];

// === AstroBin Export ===
export type ExportFilterRow = Schemas["ExportFilterRow"];
export type ExportEquipment = Schemas["ExportEquipment"];
export type ExportCalibration = Schemas["ExportCalibration"];
export type ExportResponse = Schemas["ExportResponse"];

// === Mosaics ===
export type PanelStats = Schemas["PanelStats"];
export type MosaicSummary = Schemas["MosaicSummary"];
export type MosaicDetailResponse = Schemas["MosaicDetailResponse"];
export type AvailablePanelLabel = Schemas["AvailablePanelLabel"];
// generated name: PanelThumbnail
export type PanelThumbnailResponse = Schemas["PanelThumbnail"];
export type SuggestionPanelSession = Schemas["SuggestionPanelSession"];
export type SuggestionPreviewPanel = Schemas["SuggestionPreviewPanel"];
export type MosaicSuggestionResponse = Schemas["MosaicSuggestionResponse"];
export type PanelSessionInfo = Schemas["PanelSessionInfo"];
export type PanelSessionsResponse = Schemas["PanelSessionsResponse"];

// === Custom Columns ===
// CustomColumn is hand-written (not `Schemas["CustomColumnResponse"]`): the
// generated schema loosens `column_type`/`applies_to` to plain `string` and
// `dropdown_options` to optional. See the Settings-section note above.
export interface CustomColumn {
  id: string;
  name: string;
  slug: string;
  column_type: "boolean" | "text" | "dropdown";
  applies_to: "target" | "session" | "rig" | "mosaic";
  dropdown_options: string[] | null;
  display_order: number;
  created_by: string;
  created_at: string;
}

export type TableColumnVisibility = Schemas["TableColumnVisibility"];
export type ColumnVisibility = Schemas["ColumnVisibility"];

// === WBPP Export ===
export type WbppFolderLevel = Schemas["WbppFolderLevel"];
export type WbppSessionPreview = Schemas["WbppSessionPreview"];
export type WbppPreviewResponse = Schemas["WbppPreviewResponse"];
export type WbppPreviewRequest = Schemas["WbppPreviewRequest"];
export type WbppGenerateRequest = Schemas["WbppGenerateRequest"];
export type WbppCopyOperation = Schemas["WbppCopyOperation"];
export type WbppGenerateResponse = Schemas["WbppGenerateResponse"];

// === Backup / Restore ===
export type BackupMeta = Schemas["BackupMeta"];
export type SectionPreview = Schemas["SectionPreview"];
export type ValidateResponse = Schemas["ValidateResponse"];
export type RestoreResponse = Schemas["RestoreResponse"];

// === App Logs === (generated name: PaginatedAppLogResponse)
export type AppLogItem = Schemas["AppLogItem"];
export type AppLogPageResponse = Schemas["PaginatedAppLogResponse"];

// ---------------------------------------------------------------------------
// Client-only types: no server-schema equivalent (frontend-only state, or a
// convenience bag for query params the OpenAPI spec expresses as individual
// flattened parameters rather than a named schema). Moved verbatim from the
// old `frontend/src/types/index.ts` / `frontend/src/api/client.ts`.
// ---------------------------------------------------------------------------

// Client-side dashboard filter state (never sent as a single JSON body --
// buildTargetQuery-equivalent logic serializes these into individual query
// params via ActiveFilters, so there is no matching generated schema type).
export interface ActiveFilters {
  searchQuery: string;
  selectedTargetId: string | null;
  camera: string | null;
  telescope: string | null;
  opticalFilters: string[];
  objectTypes: string[];
  dateRange: { start: string | null; end: string | null };
  fitsQueries: { key: string; operator: string; value: string }[];
  qualityFilters: { hfrMin?: number; hfrMax?: number };
  metricFilters: Record<string, { min?: number; max?: number }>;
  customColumnFilters: { slug: string; value: string }[];
  catalog: string | null;
}

// Non-fuzzy search result shape kept for source compatibility; current search
// endpoints return TargetSearchResultFuzzy.
export interface TargetSearchResult {
  id: string;
  primary_name: string;
  object_type: string | null;
}

export type ActivitySeverity = "info" | "warning" | "error";

export type ActivityCategory =
  | "scan"
  | "rebuild"
  | "thumbnail"
  | "enrichment"
  | "mosaic"
  | "migration"
  | "user_action"
  | "system";

// UI-only representation of an in-flight background job (dashboard activity
// widget); not a server response shape.
export interface ActiveJob {
  id: string;
  category: "scan" | "rebuild" | "thumbnail" | "enrichment" | "mosaic";
  label: string;
  subLabel?: string;
  progress?: number;
  startedAt: number;
  detail?: string;
  cancelable: boolean;
  onCancel?: () => Promise<void>;
}

// Query-param bag for GET /activity -- the OpenAPI spec flattens these into
// individual query parameters rather than a named request schema.
export interface ActivityQueryParams {
  severity?: ActivitySeverity | ActivitySeverity[];
  category?: ActivityCategory | ActivityCategory[];
  limit?: number;
  cursor?: string;
  since?: string;
}

// Richer failed-file shape ({file, error}) than the generated ScanStateResponse's
// flattened `failed_files: string[]` -- see the discrepancy note at the top of
// this file. Kept in case a slice needs it for a differently-shaped endpoint.
export interface FailedFile {
  file: string;
  error: string;
}

export type AppLogLevel = "debug" | "info" | "warning" | "error" | "critical";
export type AppLogSource = "api" | "worker" | "beat";

// Query-param bag for GET /logs -- flattened query parameters, no named
// request schema in the OpenAPI spec.
export interface LogQueryParams {
  level?: AppLogLevel | AppLogLevel[];
  source?: AppLogSource | AppLogSource[];
  q?: string;
  since?: string;
  limit?: number;
  cursor?: string;
}

// nina_instances / stellarium_instances entries inside GeneralSettings --
// generated schema types these fields structurally inline; kept as a named
// convenience type for call sites that build/read individual instances.
export interface IntegrationInstance {
  name: string;
  url: string;
  enabled: boolean;
}

// custom_values entries inside SessionDetail -- generated schema types
// `custom_values` as a loose `Record<string, unknown>[]`; kept as a named
// convenience type for call sites that need the richer shape.
export interface CustomColumnValue {
  column_slug: string;
  session_date: string | null;
  rig_label: string | null;
  value: string;
}

// Per-filter entry inside PanelSessionInfo.filters -- generated schema types
// the map's value structurally inline.
export interface PanelSessionFilter {
  frames: number;
  integration: number;
}
