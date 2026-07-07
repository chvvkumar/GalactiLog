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

type Schemas = components["schemas"];

// === Target Aggregation ===
export type SessionSummary = Schemas["SessionSummary"];
export type TargetAggregation = Schemas["TargetAggregation"];
export type AggregateStats = Schemas["AggregateStats"];
export type TargetAggregationResponse = Schemas["TargetAggregationResponse"];

// === Session Detail === (generated name: SessionDetailResponse)
export type SessionDetail = Schemas["SessionDetailResponse"];
export type FilterMedian = Schemas["FilterMedian"];
export type SessionOverview = Schemas["SessionOverview"];
export type TargetDetailResponse = Schemas["TargetDetailResponse"];
export type RigDetail = Schemas["RigDetail"];
export type FilterDetail = Schemas["FilterDetail"];
export type SessionInsight = Schemas["SessionInsight"];
export type FrameRecord = Schemas["FrameRecord"];

// === Equipment === (generated name: EquipmentResponse)
export type EquipmentOption = Schemas["EquipmentOption"];
export type EquipmentList = Schemas["EquipmentResponse"];

// === Scan ===
// generated name: ScanQueueResponse (POST /scan, /scan/reset, /scan/stop, etc.)
export type ScanResult = Schemas["ScanQueueResponse"];
// generated name: ScanStateResponse (GET /scan/status) -- see discrepancy note above.
export type ScanStatus = Schemas["ScanStateResponse"];

// === Activity === (generated name: ActivityItem)
export type ActivityEvent = Schemas["ActivityItem"];
// generated name: PaginatedActivityResponse
export type ActivityPageResponse = Schemas["PaginatedActivityResponse"];
// generated name: RebuildStatusResponse
export type RebuildStatus = Schemas["RebuildStatusResponse"];
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
export type GeneralSettings = Schemas["GeneralSettings"];
export type FilterConfig = Schemas["FilterConfig"];
export type EquipmentAliases = Schemas["EquipmentAliases"];
export type EquipmentConfig = Schemas["EquipmentConfig"];
export type GraphSettings = Schemas["GraphSettings"];
export type SettingsResponse = Schemas["SettingsResponse"];

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
export type CorrelationPoint = Schemas["CorrelationPoint"];
export type ConfidenceBandPoint = Schemas["ConfidenceBandPoint"];
export type TrendLine = Schemas["TrendLine"];
export type CorrelationResponse = Schemas["CorrelationResponse"];
export type HistogramBin = Schemas["HistogramBin"];
export type DistributionResponse = Schemas["DistributionResponse"];
export type BoxPlotGroup = Schemas["BoxPlotGroup"];
export type BoxPlotResponse = Schemas["BoxPlotResponse"];
export type TimeSeriesPoint = Schemas["TimeSeriesPoint"];
export type MovingAveragePoint = Schemas["MovingAveragePoint"];
export type TimeSeriesResponse = Schemas["TimeSeriesResponse"];
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

// === Custom Columns === (generated name: CustomColumnResponse)
export type CustomColumn = Schemas["CustomColumnResponse"];
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
