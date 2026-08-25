// Single query-key factory for every TanStack Query hook migrated in T3.
// Every migrated read site must build its key through one of these
// functions -- never an ad hoc inline array -- so `queryClient.invalidateQueries`
// can target consistent, predictable prefixes across slices.
//
// Convention: every tuple's first element is a resource-name string so
// prefix-matching invalidation (e.g. invalidating everything under
// `["targets", ...]`) works without needing an exact key. Each factory
// function returns a readonly tuple via `as const` so TanStack Query can
// infer a stable, literal key type.
import type { ActiveFilters } from "./types";

// The prefix every phd2 key starts with. store/scan.ts invalidates through
// this constant when a guide-log pass settles, so the invalidation and the
// key factories cannot drift apart; queryKeys.test.ts asserts the relation.
export const PHD2_QUERY_PREFIX = ["phd2"] as const;

export const queryKeys = {
  // Auth
  me: () => ["me"] as const,

  // Single startup call returning settings/equipment/fits-keys/object-types/
  // custom-columns together (see BootstrapResponse in ./types.ts).
  bootstrap: () => ["bootstrap"] as const,

  // Targets
  targets: (
    filters: ActiveFilters,
    page?: number,
    pageSize?: number,
    sortBy?: string,
    sortDir?: string,
    includeCustom?: boolean,
  ) => ["targets", filters, page, pageSize, sortBy, sortDir, includeCustom] as const,
  targetDetail: (targetId: string) => ["targets", targetId, "detail"] as const,
  targetSearch: (query: string, includeUnresolved?: boolean) =>
    ["targets", "search", query, includeUnresolved] as const,
  targetExport: (targetId: string, sessions?: string[]) =>
    ["targets", targetId, "export", sessions ?? null] as const,
  targetMergeHistory: (targetId: string) => ["targets", targetId, "merge-history"] as const,
  objectTypes: () => ["targets", "object-types"] as const,
  equipment: () => ["targets", "equipment"] as const,
  fitsKeys: () => ["targets", "fits-keys"] as const,
  mergeCandidates: (status: string = "pending") => ["targets", "merge-candidates", status] as const,
  mergePreview: (winnerId: string, loserId?: string, loserName?: string) =>
    ["targets", "merge-preview", winnerId, loserId ?? null, loserName ?? null] as const,
  referenceThumbnail: (targetId: string) => ["targets", targetId, "reference-thumbnail"] as const,

  // Sessions
  sessionDetail: (targetId: string, date: string) => ["targets", targetId, "sessions", date] as const,

  // Stats / calendar
  stats: () => ["stats"] as const,
  calendar: (year?: number) => ["stats", "calendar", year ?? null] as const,
  guidingStats: () => ["stats", "guiding"] as const,

  // Scan
  scanStatus: () => ["scan", "status"] as const,
  scanSummary: () => ["scan", "summary"] as const,
  rebuildStatus: () => ["scan", "rebuild-status"] as const,
  dbSummary: () => ["scan", "db-summary"] as const,

  // Activity / app logs
  activity: (params?: unknown) => ["activity", params ?? null] as const,
  activitySettings: () => ["settings", "activity"] as const,
  logs: (params?: unknown) => ["logs", params ?? null] as const,

  // Tasks (imperative pollers; keys used only if wrapped in a query)
  taskStatus: (taskId: string) => ["tasks", taskId, "status"] as const,

  // Settings
  settings: () => ["settings"] as const,
  filterSuggestions: () => ["settings", "suggestions", "filters"] as const,
  equipmentSuggestions: () => ["settings", "suggestions", "equipment"] as const,
  discovered: (section: "filters" | "cameras" | "telescopes") =>
    ["settings", "discovered", section] as const,
  columnVisibility: (userId: string) => ["settings", "column-visibility", userId] as const,

  // Custom columns
  customColumns: () => ["custom-columns"] as const,

  // Users
  users: () => ["users"] as const,

  // Filename resolution
  filenameCandidates: (status: string = "pending") =>
    ["filename-resolution", "candidates", status] as const,

  // Mosaics
  mosaics: () => ["mosaics"] as const,
  mosaicDetail: (id: string) => ["mosaics", id, "detail"] as const,
  mosaicSuggestions: () => ["mosaics", "suggestions"] as const,
  mosaicPanelThumbnails: (mosaicId: string, filter: string) =>
    ["mosaics", mosaicId, "panels", "thumbnails", filter] as const,
  mosaicComposite: (mosaicId: string, filter?: string | null) =>
    ["mosaics", mosaicId, "composite", filter ?? null] as const,
  panelSessions: (mosaicId: string, panelId: string) =>
    ["mosaics", mosaicId, "panels", panelId, "sessions"] as const,

  // Analysis
  analysisFilters: () => ["analysis", "filters"] as const,
  correlation: (params: unknown) => ["analysis", "correlation", params] as const,
  distribution: (params: unknown) => ["analysis", "distribution", params] as const,
  boxplot: (params: unknown) => ["analysis", "boxplot", params] as const,
  timeseries: (params: unknown) => ["analysis", "timeseries", params] as const,
  matrix: (params: unknown) => ["analysis", "matrix", params] as const,
  compare: (params: unknown) => ["analysis", "compare", params] as const,

  // PHD2 guiding
  phd2Profiles: () => ["phd2", "profiles"] as const,
  phd2Sessions: (sessionDate: string, telescope?: string | null) =>
    ["phd2", "sessions", "list", sessionDate, telescope ?? null] as const,
  phd2Frames: (sessionId: string) => ["phd2", "sessions", sessionId, "frames"] as const,
};
