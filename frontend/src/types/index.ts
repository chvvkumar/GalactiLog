// === Target Aggregation ===

export interface SessionSummary {
  session_date: string;
  integration_seconds: number;
  frame_count: number;
  filters_used: string[];
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
  // New fields
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
}

// === Target Detail (Deep Dive Page) ===

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
  // SAC
  sac_description: string | null;
  sac_notes: string | null;
  // SkyView
  reference_thumbnail_path: string | null;
  // Gaia DR3
  distance_pc: number | null;
  // Catalog memberships
  catalog_memberships: CatalogMembershipEntry[];
  name_locked: boolean;
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

// === Equipment ===

export interface EquipmentOption {
  name: string;
  grouped: boolean;
}

export interface EquipmentList {
  cameras: EquipmentOption[];
  telescopes: EquipmentOption[];
}

// === Filters ===

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

// === Scan (unchanged) ===

export interface ScanResult {
  status: string;
  new_files_queued: number;
  already_known: number;
  state?: string;
  total?: number;
  completed?: number;
  failed?: number;
}

export interface FailedFile {
  file: string;
  error: string;
}

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

export interface ActivityEvent {
  id: number;
  timestamp: string;
  severity: ActivitySeverity;
  category: ActivityCategory;
  event_type: string;
  message: string;
  details: Record<string, unknown> | null;
  target_id: number | null;
  actor: string | null;
  duration_ms: number | null;
  parent_id: number | null;
  children: ActivityEvent[] | null;
}

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

export interface ActivityQueryParams {
  severity?: ActivitySeverity | ActivitySeverity[];
  category?: ActivityCategory | ActivityCategory[];
  limit?: number;
  cursor?: string;
  since?: string;
}

export interface ActivityPageResponse {
  items: ActivityEvent[];
  next_cursor: string | null;
  total: number;
}

export interface RebuildStatus {
  state: "idle" | "running" | "complete" | "error";
  mode: string;
  message: string;
  started_at: number | null;
  completed_at: number | null;
  details: Record<string, number>;
}

export interface DbSummary {
  total_images: number;
  light_frames: number;
  resolved_targets: number;
  unresolved_images: number;
  cached_simbad: number;
  cached_negative: number;
  cached_vizier: number;
  cached_vizier_negative: number;
  cached_sesame: number;
  cached_sesame_negative: number;
  pending_merges: number;
  csv_enriched: number;
}

// === Search ===

export interface TargetSearchResult {
  id: string;
  primary_name: string;
  object_type: string | null;
}

export interface TargetSearchResultFuzzy {
  id: string;
  primary_name: string;
  object_type: string | null;
  aliases: string[];
  match_source: string | null;
  similarity_score: number;
}

export interface ObjectTypeCount {
  object_type: string;
  count: number;
}

export interface MergeCandidateResponse {
  id: string;
  source_name: string;
  source_image_count: number;
  suggested_target_id: string | null;
  suggested_target_name: string | null;
  similarity_score: number;
  method: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  reason_text: string | null;
}

export interface OrphanPreviewResponse {
  source_name: string;
  resolved: boolean;
  primary_name: string;
  catalog_id: string | null;
  ra: number | null;
  dec: number | null;
  object_type: string | null;
  constellation: string | null;
  size_major: number | null;
  size_minor: number | null;
  position_angle: number | null;
  v_mag: number | null;
}

export interface OrphanCreateRequest {
  candidate_id: string;
  primary_name: string;
  ra: number | null;
  dec: number | null;
  object_type: string | null;
  catalog_id: string | null;
}

export interface MergedTargetResponse {
  id: string;
  primary_name: string;
  merged_into_id: string;
  merged_into_name: string;
  merged_at: string;
  image_count: number;
}

export interface FilenameCandidateResponse {
  id: string;
  extracted_name: string | null;
  suggested_target_id: string | null;
  suggested_target_name: string | null;
  method: string;
  confidence: number;
  status: string;
  file_count: number;
  file_paths: string[];
  created_at: string;
  resolved_at: string | null;
}

// === Stats (Admin) ===

export interface EquipmentItem {
  name: string;
  frame_count: number;
  grouped: boolean;
}

export interface TimelineEntry {
  month: string;
  integration_seconds: number;
}

export interface TimelineDetailEntry {
  period: string;
  integration_seconds: number;
  efficiency_pct: number | null;
}

export interface SiteCoords {
  latitude: number;
  longitude: number;
}

export interface TopTarget {
  name: string;
  integration_seconds: number;
}

export interface HfrBucket {
  bucket: string;
  count: number;
}

export interface EquipmentFilterMetrics {
  filter_name: string;
  frame_count: number;
  total_integration_seconds: number;
  median_hfr: number | null;
  best_hfr: number | null;
  median_eccentricity: number | null;
  median_fwhm: number | null;
}

export interface EquipmentComboMetrics {
  telescope: string;
  camera: string;
  frame_count: number;
  total_integration_seconds: number;
  median_hfr: number | null;
  best_hfr: number | null;
  median_eccentricity: number | null;
  median_fwhm: number | null;
  grouped: boolean;
  filters: string[];
  filter_breakdown: EquipmentFilterMetrics[];
}

export interface OverviewStats {
  total_integration_seconds: number;
  target_count: number;
  total_frames: number;
  disk_usage_bytes: number;
  session_count: number;
  first_capture_date: string | null;
  last_capture_date: string | null;
}

export interface StatsResponse {
  overview: OverviewStats;
  equipment: {
    cameras: EquipmentItem[];
    telescopes: EquipmentItem[];
  };
  equipment_performance: EquipmentComboMetrics[];
  filter_usage: Record<string, number>;
  timeline: TimelineEntry[];
  timeline_monthly: TimelineDetailEntry[];
  timeline_weekly: TimelineDetailEntry[];
  timeline_daily: TimelineDetailEntry[];
  site_coords: SiteCoords | null;
  top_targets: TopTarget[];
  data_quality: {
    avg_hfr: number | null;
    avg_eccentricity: number | null;
    best_hfr: number | null;
    hfr_distribution: HfrBucket[];
  };
  storage: {
    fits_bytes: number;
    thumbnail_bytes: number;
    database_bytes: number;
  };
  ingest_history: { date: string; files_added: number }[];
}

// === Calendar ===

export interface CalendarEntry {
  date: string;
  integration_seconds: number;
  target_count: number;
  frame_count: number;
}

// === Catalog Memberships ===

export interface CatalogMembershipEntry {
  catalog_name: string;
  catalog_number: string;
  metadata: Record<string, any> | null;
}

// === Night Ephemeris (Planning) ===

export interface NightEphemeris {
  date: string;
  astro_dusk: string | null;
  astro_dawn: string | null;
  moon_phase: string | null;
  moon_illumination: number | null;
  moon_rise: string | null;
  moon_set: string | null;
  source_available: boolean;
}

// === Settings ===

export interface MetricGroupSettings {
  enabled: boolean;
  fields: Record<string, boolean>;
}

export interface DisplaySettings {
  quality: MetricGroupSettings;
  guiding: MetricGroupSettings;
  adu: MetricGroupSettings;
  focuser: MetricGroupSettings;
  weather: MetricGroupSettings;
  mount: MetricGroupSettings;
}

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
}

export interface IntegrationInstance {
  name: string;
  url: string;
  enabled: boolean;
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
}

export interface SettingsResponse {
  general: GeneralSettings;
  filters: Record<string, FilterConfig>;
  equipment: EquipmentConfig;
  dismissed_suggestions: string[][];
  display: DisplaySettings;
  graph: GraphSettings;
}

// === Auth ===

export interface AuthUser {
  id: string;
  username: string;
  role: "admin" | "viewer";
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  username: string;
  role: string;
}

export interface UserAccount {
  id: string;
  username: string;
  role: "admin" | "viewer";
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SuggestionGroup {
  group: string[];
  counts: Record<string, number>;
  section?: string;  // "cameras", "telescopes", or "filters"
}

export interface SuggestionsResponse {
  suggestions: SuggestionGroup[];
}

export interface DiscoveredItem {
  name: string;
  count: number;
}

export interface DiscoveredResponse {
  items: DiscoveredItem[];
}

// === Analysis ===

export interface SummaryStats {
  count: number;
  min: number;
  max: number;
  mean: number;
  median: number;
  std_dev: number;
}

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
}

export interface HistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface DistributionResponse {
  bins: HistogramBin[];
  stats: SummaryStats;
  metric: string;
  skewness: number;
}

export interface BoxPlotGroup {
  group_name: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  outliers: number[];
  count: number;
}

export interface BoxPlotResponse {
  groups: BoxPlotGroup[];
  metric: string;
  group_by: string;
}

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

export interface MatrixCell {
  x_metric: string;
  y_metric: string;
  pearson_r: number | null;
  n_points: number;
}

export interface MatrixResponse {
  cells: MatrixCell[];
  x_metrics: string[];
  y_metrics: string[];
}

export interface CompareGroupStats {
  name: string;
  box: BoxPlotGroup;
  stats: SummaryStats;
}

export interface CompareResponse {
  group_a: CompareGroupStats;
  group_b: CompareGroupStats;
  metric: string;
  mode: string;
  verdict: string;
}

// === AstroBin Export ===

export interface ExportFilterRow {
  date: string;
  filter_name: string;
  astrobin_filter_id: number | null;
  frames: number;
  exposure: number;
  total_seconds: number;
  gain: number | null;
  sensor_temp: number | null;
  fwhm: number | null;
  sky_quality: number | null;
  ambient_temp: number | null;
}

export interface ExportEquipment {
  telescope: string | null;
  camera: string | null;
}

export interface ExportCalibration {
  darks: number;
  flats: number;
  bias: number;
}

export interface ExportResponse {
  target_name: string;
  catalog_id: string | null;
  equipment: ExportEquipment[];
  dates: string[];
  rows: ExportFilterRow[];
  calibration: ExportCalibration;
  total_integration_seconds: number;
  bortle: number | null;
}

// === Mosaics ===

export interface PanelStats {
  panel_id: string;
  target_id: string;
  target_name: string;
  panel_label: string;
  sort_order: number;
  ra: number | null;
  dec: number | null;
  total_integration_seconds: number;
  total_frames: number;
  filter_distribution: Record<string, number>;
  last_session_date: string | null;
  thumbnail_url: string | null;
  thumbnail_pier_side: string | null;
  thumbnail_image_id?: string | null;
  thumbnail_file_path?: string | null;
  object_pattern?: string | null;
  grid_row: number | null;
  grid_col: number | null;
  rotation: number;
  flip_h: boolean;
  available_session_count?: number;
}

export interface MosaicSummary {
  id: string;
  name: string;
  notes: string | null;
  panel_count: number;
  total_integration_seconds: number;
  total_frames: number;
  completion_pct: number;
  first_session: string | null;
  last_session: string | null;
  needs_review?: boolean;
  custom_values?: Record<string, string> | null;
}

export interface MosaicDetailResponse {
  id: string;
  name: string;
  notes: string | null;
  rotation_angle: number | null;
  pixel_coords: boolean;
  total_integration_seconds: number;
  total_frames: number;
  panels: PanelStats[];
  available_filters: string[];
  default_filter: string | null;
  needs_review?: boolean;
}

export interface PanelThumbnailResponse {
  panel_id: string;
  thumbnail_url: string | null;
  frame_id: string | null;
  score: number | null;
  filter_used: string;
}

export interface SuggestionPanelSession {
  panel_label: string;
  object_name: string;
  date: string;
  frames: number;
  integration_seconds: number;
  filter_used: string | null;
}

export interface MosaicSuggestionResponse {
  id: string;
  suggested_name: string;
  target_ids: string[];
  panel_labels: string[];
  target_names: Record<string, string>;
  sessions: SuggestionPanelSession[];
  session_dates?: Record<string, string[]> | null;
  other_session_count?: number;
  status: string;
}

export interface PanelSessionFilter {
  frames: number;
  integration: number;
}

export interface PanelSessionInfo {
  session_date: string;
  status: "included" | "available";
  total_frames: number;
  total_integration_seconds: number;
  filters: Record<string, PanelSessionFilter>;
}

export interface PanelSessionsResponse {
  panel_id: string;
  panel_label: string;
  sessions: PanelSessionInfo[];
}

// Custom Columns

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

export interface CustomColumnValue {
  column_slug: string;
  session_date: string | null;
  rig_label: string | null;
  value: string;
}

export interface TableColumnVisibility {
  builtin: Record<string, boolean>;
  custom: Record<string, boolean>;
}

export interface ColumnVisibility {
  dashboard: TableColumnVisibility;
  session_table: TableColumnVisibility;
  session_detail: TableColumnVisibility;
  mosaic_table: TableColumnVisibility;
}
