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
  camera: string | null;
  telescope: string | null;
  opticalFilters: string[];
  objectTypes: string[];
  dateRange: { start: string | null; end: string | null };
  fitsQueries: { key: string; operator: string; value: string }[];
  qualityFilters: { hfrMin?: number; hfrMax?: number };
  metricFilters: Record<string, { min?: number; max?: number }>;
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
  failed_files?: FailedFile[];
}

export interface ActivityEntry {
  type: "scan_complete" | "scan_stopped" | "scan_stalled"
    | "rebuild_complete" | "rebuild_failed" | "regen_complete"
    | "delta_scan" | "orphan_cleanup" | "orphan_warning"
    | "migration_applied" | "migration_initialized" | "migration_ok" | "migration_failed"
    | "data_upgrade_started" | "data_upgrade_complete" | "data_upgrade_failed";
  message: string;
  details: Record<string, any>;
  timestamp: number;
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
  suggested_target_id: string;
  suggested_target_name: string;
  similarity_score: number;
  method: string;
  status: string;
  created_at: string;
}

export interface MergedTargetResponse {
  id: string;
  primary_name: string;
  merged_into_id: string;
  merged_into_name: string;
  merged_at: string;
  image_count: number;
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
  astrobin_filter_ids?: Record<string, number>;
  astrobin_bortle?: number | null;
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

// === Correlation Analysis ===

export interface CorrelationPoint {
  x: number;
  y: number;
  date: string;
  target_name: string | null;
}

export interface TrendLine {
  slope: number;
  intercept: number;
  r_squared: number;
}

export interface CorrelationResponse {
  points: CorrelationPoint[];
  trend: TrendLine | null;
  x_metric: string;
  y_metric: string;
  granularity: string;
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
}

export interface MosaicSummary {
  id: string;
  name: string;
  notes: string | null;
  panel_count: number;
  total_integration_seconds: number;
  total_frames: number;
  completion_pct: number;
}

export interface MosaicDetailResponse {
  id: string;
  name: string;
  notes: string | null;
  total_integration_seconds: number;
  total_frames: number;
  panels: PanelStats[];
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
  status: string;
}
