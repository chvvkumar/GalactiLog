import type {
  TargetAggregationResponse,
  SessionDetail,
  EquipmentList,
  TargetSearchResult,
  TargetSearchResultFuzzy,
  ObjectTypeCount,
  MergeCandidateResponse,
  MergedTargetResponse,
  OrphanPreviewResponse,
  OrphanCreateRequest,
  FilenameCandidateResponse,
  ScanResult,
  ScanStatus,
  ActiveFilters,
  StatsResponse,
  TargetDetailResponse,
  SettingsResponse,
  GeneralSettings,
  FilterConfig,
  EquipmentConfig,
  SuggestionsResponse,
  DiscoveredResponse,
  DisplaySettings,
  GraphSettings,
  AuthUser,
  LoginResponse,
  CustomColumn,
  CustomColumnValue,
  ColumnVisibility,
  ActivityEvent,
  ActivityQueryParams,
  ActivityPageResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export interface BackupMeta {
  schema_version: number;
  app_version: string;
  exported_at: string;
}

export interface SectionPreview {
  add: number;
  update: number;
  skip: number;
  unchanged: number;
}

export interface ValidateResponse {
  valid: boolean;
  meta: BackupMeta | null;
  preview: Record<string, SectionPreview>;
  warnings: string[];
  error: string | null;
}

export interface RestoreResponse {
  success: boolean;
  applied: Record<string, SectionPreview>;
  temporary_passwords: Record<string, string>;
  warnings: string[];
  error: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
    });
    return resp.ok;
  } catch {
    return false;
  }
}

async function fetchWithRefresh(path: string, init: RequestInit): Promise<Response> {
  let resp = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
  });

  if (
    resp.status === 401 &&
    !path.startsWith("/auth/refresh") &&
    !path.startsWith("/auth/login")
  ) {
    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => { refreshPromise = null; });
    }
    const ok = await refreshPromise;
    if (ok) {
      resp = await fetch(`${API_BASE}${path}`, {
        credentials: "same-origin",
        ...init,
      });
    } else {
      window.dispatchEvent(new CustomEvent("auth:expired"));
      throw new Error("Session expired");
    }
  }

  return resp;
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: "Invalid request",
  403: "Permission denied",
  404: "Not found",
  409: "Conflict - resource already exists",
  422: "Validation error",
  500: "Server error - please try again later",
};

async function extractApiError(resp: Response, fallback: string): Promise<ApiError> {
  let message: string;
  try {
    const body = await resp.json();
    message = typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    message = FALLBACK_MESSAGES[resp.status] ?? fallback;
  }
  return new ApiError(resp.status, message);
}

export async function fetchJson<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    signal: signal ?? init?.signal,
  });

  if (
    resp.status === 401 &&
    !path.startsWith("/auth/refresh") &&
    !path.startsWith("/auth/login")
  ) {
    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => { refreshPromise = null; });
    }
    const ok = await refreshPromise;
    if (ok) {
      return fetchJson<T>(path, init);
    }
    window.dispatchEvent(new CustomEvent("auth:expired"));
    throw new Error("Session expired");
  }

  if (!resp.ok) {
    let message: string;
    try {
      const body = await resp.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      const fallback: Record<number, string> = {
        400: "Invalid request",
        403: "Permission denied",
        404: "Not found",
        409: "Conflict - resource already exists",
        422: "Validation error",
        500: "Server error - please try again later",
      };
      message = fallback[resp.status] || "Something went wrong";
    }
    throw new ApiError(resp.status, message);
  }
  return resp.json();
}

function buildTargetQuery(filters: ActiveFilters, page?: number, pageSize?: number, sortBy?: string, sortDir?: string): string {
  const params = new URLSearchParams();
  if (page != null) params.set("page", String(page));
  if (pageSize != null) params.set("page_size", String(pageSize));
  if (sortBy) params.set("sort_by", sortBy);
  if (sortDir) params.set("sort_dir", sortDir);
  if (filters.selectedTargetId) params.set("target_id", filters.selectedTargetId);
  else if (filters.searchQuery) params.set("search", filters.searchQuery);
  if (filters.camera) params.set("camera", filters.camera);
  if (filters.telescope) params.set("telescope", filters.telescope);
  if (filters.opticalFilters.length > 0) {
    params.set("filters", filters.opticalFilters.join(","));
  }
  if (filters.objectTypes.length > 0) {
    params.set("object_type", filters.objectTypes.join(","));
  }
  if (filters.dateRange.start) params.set("date_from", filters.dateRange.start);
  if (filters.dateRange.end) params.set("date_to", filters.dateRange.end);
  if (filters.qualityFilters.hfrMin != null) {
    params.set("hfr_min", String(filters.qualityFilters.hfrMin));
  }
  if (filters.qualityFilters.hfrMax != null) {
    params.set("hfr_max", String(filters.qualityFilters.hfrMax));
  }
  for (const fq of filters.fitsQueries) {
    params.append("fits_key", fq.key);
    params.append("fits_op", fq.operator);
    params.append("fits_val", fq.value);
  }
  for (const [metric, range] of Object.entries(filters.metricFilters)) {
    if (range.min != null) params.set(`${metric}_min`, String(range.min));
    if (range.max != null) params.set(`${metric}_max`, String(range.max));
  }
  if (filters.customColumnFilters.length > 0) {
    params.set("custom_filters", JSON.stringify(filters.customColumnFilters));
  }
  if (filters.catalog) params.set("catalog", filters.catalog);
  params.set("include_custom", "true");
  return params.toString();
}

export const api = {
  // Auth
  login: (username: string, password: string, remember: boolean = false) =>
    fetchJson<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, remember }),
    }),

  logout: () =>
    fetchJson<void>("/auth/logout", { method: "POST" }),

  getMe: () =>
    fetchJson<AuthUser>("/auth/me"),

  getUsers: () =>
    fetchJson<import("../types").UserAccount[]>("/auth/users"),

  createUser: (username: string, password: string, role: string) =>
    fetchJson<import("../types").UserAccount>("/auth/users", {
      method: "POST",
      body: JSON.stringify({ username, password, role }),
    }),

  updateUser: (id: string, data: { role?: string; is_active?: boolean }) =>
    fetchJson<import("../types").UserAccount>(`/auth/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteUser: (id: string) =>
    fetchJson<void>(`/auth/users/${id}`, { method: "DELETE" }),

  getTargets: (filters: ActiveFilters, page?: number, pageSize?: number, sortBy?: string, sortDir?: string, signal?: AbortSignal) =>
    fetchJson<TargetAggregationResponse>(`/targets?${buildTargetQuery(filters, page, pageSize, sortBy, sortDir)}`, undefined, signal),

  getSessionDetail: (targetId: string, date: string) =>
    fetchJson<SessionDetail>(`/targets/${encodeURIComponent(decodeURIComponent(targetId))}/sessions/${date}`),

  getTargetDetail: (targetId: string) =>
    fetchJson<TargetDetailResponse>(`/targets/${encodeURIComponent(decodeURIComponent(targetId))}/detail`),

  getExport: (targetId: string, sessions?: string[]) => {
    const params = sessions?.length ? `?sessions=${sessions.join(",")}` : "";
    return fetchJson<import("../types").ExportResponse>(
      `/targets/${encodeURIComponent(targetId)}/export${params}`
    );
  },

  getEquipment: () =>
    fetchJson<EquipmentList>("/targets/equipment"),

  getFitsKeys: () =>
    fetchJson<string[]>("/targets/fits-keys"),

  searchTargets: (query: string) =>
    fetchJson<TargetSearchResultFuzzy[]>(`/targets/search?q=${encodeURIComponent(query)}`),

  getStats: () =>
    fetchJson<StatsResponse>("/stats"),

  getCalendar: (year?: number) =>
    fetchJson<import("../types").CalendarEntry[]>(
      `/stats/calendar${year != null ? `?year=${year}` : ""}`
    ),

  triggerScan: (options?: { includeCalibration?: boolean }) => {
    const params = new URLSearchParams();
    if (options?.includeCalibration === false) {
      params.set("include_calibration", "false");
    }
    const qs = params.toString();
    return fetchJson<ScanResult>(`/scan${qs ? `?${qs}` : ""}`, { method: "POST" });
  },

  getScanStatus: () =>
    fetchJson<ScanStatus>("/scan/status"),

  regenerateThumbnails: (opts: { purge?: boolean } = {}) => {
    const qs = opts.purge ? "?purge=true" : "";
    return fetchJson<ScanResult & { task_id?: string }>(`/scan/regenerate-thumbnails${qs}`, { method: "POST" });
  },

  resetScan: () =>
    fetchJson<{ status: string }>("/scan/reset", { method: "POST" }),

  stopScan: () =>
    fetchJson<{ status: string; message?: string }>("/scan/stop", { method: "POST" }),

  fetchActivity: (params: ActivityQueryParams = {}) => {
    const qs = new URLSearchParams();
    const severities = Array.isArray(params.severity)
      ? params.severity
      : params.severity
      ? [params.severity]
      : [];
    severities.forEach((s) => qs.append("severity", s));
    const categories = Array.isArray(params.category)
      ? params.category
      : params.category
      ? [params.category]
      : [];
    categories.forEach((c) => qs.append("category", c));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.cursor) qs.set("cursor", params.cursor);
    if (params.since) qs.set("since", params.since);
    const q = qs.toString();
    return fetchJson<ActivityPageResponse>(`/activity${q ? `?${q}` : ""}`);
  },

  fetchActivityErrorsSince: (since: string) => {
    const qs = new URLSearchParams({ severity: "error", since });
    return fetchJson<ActivityPageResponse>(`/activity?${qs}`);
  },

  clearActivityLog: () =>
    fetchJson<{ status: string }>("/activity", { method: "DELETE" }),

  getActivitySettings: () =>
    fetchJson<{ activity_retention_days: number }>("/settings/activity"),

  setActivitySettings: (body: { retention_days: number }) =>
    fetchJson<{ activity_retention_days: number }>("/settings/activity", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  rebuildTargets: () =>
    fetchJson<{ status: string; message: string; task_id?: string }>("/scan/rebuild-targets", { method: "POST" }),

  smartRebuildTargets: () =>
    fetchJson<{ status: string; message: string; task_id?: string }>("/scan/smart-rebuild-targets", { method: "POST" }),

  retryUnresolved: () =>
    fetchJson<{ status: string; message: string; task_id?: string }>("/scan/retry-unresolved", { method: "POST" }),

  getRebuildStatus: () =>
    fetchJson<import("../types").RebuildStatus>("/scan/rebuild-status"),

  getDbSummary: () =>
    fetchJson<import("../types").DbSummary>("/scan/db-summary"),

  getAutoScan: () =>
    fetchJson<{ enabled: boolean; interval_minutes: number }>("/scan/autoscan"),

  setAutoScan: (enabled: boolean, interval_minutes: number) =>
    fetchJson<{ enabled: boolean; interval_minutes: number }>(
      `/scan/autoscan?enabled=${enabled}&interval_minutes=${interval_minutes}`,
      { method: "PUT" }
    ),

  thumbnailUrl: (path: string) => {
    const filename = path.split("/").pop();
    return `/thumbnails/${filename}`;
  },

  // Settings
  getSettings: () =>
    fetchJson<SettingsResponse>("/settings"),

  updateGeneral: (body: GeneralSettings) =>
    fetchJson<SettingsResponse>("/settings/general", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  updateFilters: (body: Record<string, FilterConfig>) =>
    fetchJson<SettingsResponse>("/settings/filters", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  updateEquipment: (body: EquipmentConfig) =>
    fetchJson<SettingsResponse>("/settings/equipment", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getFilterSuggestions: () =>
    fetchJson<SuggestionsResponse>("/settings/suggestions/filters"),

  getEquipmentSuggestions: () =>
    fetchJson<SuggestionsResponse>("/settings/suggestions/equipment"),

  getDiscovered: (section: "filters" | "cameras" | "telescopes") =>
    fetchJson<DiscoveredResponse>(`/settings/discovered/${section}`),

  updateDismissedSuggestions: (dismissed: string[][]) =>
    fetchJson<SettingsResponse>("/settings/dismissed-suggestions", {
      method: "PUT",
      body: JSON.stringify(dismissed),
    }),

  updateDisplay: (display: DisplaySettings) =>
    fetchJson<SettingsResponse>("/settings/display", {
      method: "PUT",
      body: JSON.stringify(display),
    }),

  updateGraph: (graph: GraphSettings) =>
    fetchJson<SettingsResponse>("/settings/graph", {
      method: "PUT",
      body: JSON.stringify(graph),
    }),

  getObjectTypes: () =>
    fetchJson<ObjectTypeCount[]>("/targets/object-types"),

  getMergeCandidates: (status = "pending") =>
    fetchJson<MergeCandidateResponse[]>(`/targets/merge-candidates?status=${status}`),

  getMergeCandidateCount: () =>
    fetchJson<{ count: number }>("/targets/merge-candidates/count"),

  getMergedTargets: () =>
    fetchJson<MergedTargetResponse[]>("/targets/merged-targets"),

  getMergeHistory: (targetId: string) =>
    fetchJson<MergedTargetResponse[]>(`/targets/${encodeURIComponent(targetId)}/merge-history`),

  mergeTargets: (winnerId: string, loserId?: string, loserName?: string) =>
    fetchJson<{ status: string }>("/targets/merge", {
      method: "POST",
      body: JSON.stringify({
        winner_id: winnerId,
        ...(loserId ? { loser_id: loserId } : {}),
        ...(loserName ? { loser_name: loserName } : {}),
      }),
    }),

  unmergeTarget: (targetId: string) =>
    fetchJson<{ status: string }>(`/targets/${encodeURIComponent(targetId)}/unmerge`, {
      method: "POST",
    }),

  dismissMergeCandidate: (candidateId: string) =>
    fetchJson<{ status: string }>(`/targets/merge-candidates/${candidateId}/dismiss`, {
      method: "POST",
    }),

  revertMergeCandidate: (candidateId: string) =>
    fetchJson<{ status: string }>(`/targets/merge-candidates/${candidateId}/revert`, {
      method: "POST",
    }),

  orphanPreview: (sourceName: string) =>
    fetchJson<OrphanPreviewResponse>("/targets/orphan-preview", {
      method: "POST",
      body: JSON.stringify({ source_name: sourceName }),
    }),

  orphanCreate: (body: OrphanCreateRequest) =>
    fetchJson<{ target_id: string }>("/targets/orphan-create", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  triggerDuplicateDetection: () =>
    fetchJson<{ status: string; task_id: string }>("/targets/detect-duplicates", {
      method: "POST",
    }),

  mergePreview: (winnerId: string, loserId?: string, loserName?: string) =>
    fetchJson<any>("/targets/merge-preview", {
      method: "POST",
      body: JSON.stringify({
        winner_id: winnerId,
        ...(loserId ? { loser_id: loserId } : {}),
        ...(loserName ? { loser_name: loserName } : {}),
      }),
    }),

  updateTargetIdentity: (targetId: string, body: {
    primary_name?: string;
    object_type?: string;
    re_resolve?: boolean;
  }) =>
    fetchJson<any>(`/targets/${targetId}/identity`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getScanSummary: () =>
    fetchJson<any>("/scan/summary"),

  // Filename resolution
  getFilenameCandidates: (status = "pending") =>
    fetchJson<FilenameCandidateResponse[]>(`/filename-resolution/candidates?status=${status}`),

  getFilenameCandidateCount: () =>
    fetchJson<{ count: number }>("/filename-resolution/candidates/count"),

  acceptFilenameCandidate: (id: string, targetId?: string, createNew = false) =>
    fetchJson<{ status: string }>(`/filename-resolution/candidates/${id}/accept`, {
      method: "POST",
      body: JSON.stringify({
        ...(targetId ? { target_id: targetId } : {}),
        create_new: createNew,
      }),
    }),

  dismissFilenameCandidate: (id: string) =>
    fetchJson<{ status: string }>(`/filename-resolution/candidates/${id}/dismiss`, {
      method: "POST",
    }),

  revertFilenameCandidate: (id: string) =>
    fetchJson<{ status: string }>(`/filename-resolution/candidates/${id}/revert`, {
      method: "POST",
    }),

  triggerFilenameDetection: () =>
    fetchJson<{ status: string; task_id: string }>("/filename-resolution/detect", {
      method: "POST",
    }),

  getTaskStatus: (taskId: string) =>
    fetchJson<{ task_id: string; state: string; result: any }>(`/tasks/${taskId}/status`),

  getCorrelation: (params: {
    x_metric: string;
    y_metric: string;
    telescope?: string;
    camera?: string;
    filter_used?: string;
    granularity?: "frame" | "session";
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("x_metric", params.x_metric);
    qs.set("y_metric", params.y_metric);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.filter_used) qs.set("filter_used", params.filter_used);
    if (params.granularity) qs.set("granularity", params.granularity);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").CorrelationResponse>(`/analysis/correlation?${qs}`);
  },

  getAnalysisFilters: () =>
    fetchJson<string[]>("/analysis/filters"),

  getDistribution: (params: {
    metric: string;
    telescope?: string;
    camera?: string;
    filter_used?: string;
    granularity?: "frame" | "session";
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("metric", params.metric);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.filter_used) qs.set("filter_used", params.filter_used);
    if (params.granularity) qs.set("granularity", params.granularity);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").DistributionResponse>(`/analysis/distribution?${qs}`);
  },

  getBoxPlot: (params: {
    metric: string;
    group_by: "filter" | "equipment" | "month" | "target";
    telescope?: string;
    camera?: string;
    filter_used?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("metric", params.metric);
    qs.set("group_by", params.group_by);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.filter_used) qs.set("filter_used", params.filter_used);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").BoxPlotResponse>(`/analysis/boxplot?${qs}`);
  },

  getTimeSeries: (params: {
    metric: string;
    telescope?: string;
    camera?: string;
    filter_used?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("metric", params.metric);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.filter_used) qs.set("filter_used", params.filter_used);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").TimeSeriesResponse>(`/analysis/timeseries?${qs}`);
  },

  getMatrix: (params: {
    telescope?: string;
    camera?: string;
    filter_used?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.filter_used) qs.set("filter_used", params.filter_used);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").MatrixResponse>(`/analysis/matrix?${qs}`);
  },

  getCompare: (params: {
    metric: string;
    mode: "equipment" | "filter";
    group_a: string;
    group_b: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("metric", params.metric);
    qs.set("mode", params.mode);
    qs.set("group_a", params.group_a);
    qs.set("group_b", params.group_b);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").CompareResponse>(`/analysis/compare?${qs}`);
  },

  updateTargetNotes: (targetId: string, notes: string | null) =>
    fetchJson<{ status: string }>(`/targets/${encodeURIComponent(targetId)}/notes`, {
      method: "PUT",
      body: JSON.stringify({ notes }),
    }),

  updateSessionNotes: (targetId: string, date: string, notes: string | null) =>
    fetchJson<{ status: string }>(`/targets/${encodeURIComponent(targetId)}/sessions/${date}/notes`, {
      method: "PUT",
      body: JSON.stringify({ notes }),
    }),

  // Mosaics
  getMosaics: () =>
    fetchJson<import("../types").MosaicSummary[]>("/mosaics"),

  createMosaic: (name: string, notes?: string, panels?: { target_id: string; panel_label: string }[]) =>
    fetchJson<import("../types").MosaicSummary>("/mosaics", {
      method: "POST",
      body: JSON.stringify({ name, notes, panels: panels || [] }),
    }),

  getMosaicDetail: (id: string) =>
    fetchJson<import("../types").MosaicDetailResponse>(`/mosaics/${id}`),

  getMosaicPanelThumbnails: (mosaicId: string, filter: string) =>
    fetchJson<import("../types").PanelThumbnailResponse[]>(
      `/mosaics/${mosaicId}/panels/thumbnails?filter=${encodeURIComponent(filter)}`
    ),

  updateMosaic: (id: string, data: { name?: string; notes?: string; rotation_angle?: number | null; pixel_coords?: boolean }) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteMosaic: (id: string) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, { method: "DELETE" }),

  addMosaicPanel: (mosaicId: string, targetId: string, label: string, objectPattern?: string | null) =>
    fetchJson<{ status: string; panel_id: string }>(`/mosaics/${mosaicId}/panels`, {
      method: "POST",
      body: JSON.stringify({ target_id: targetId, panel_label: label, object_pattern: objectPattern }),
    }),

  updateMosaicPanel: (
    mosaicId: string,
    panelId: string,
    data: {
      panel_label?: string;
      sort_order?: number;
      grid_row?: number | null;
      grid_col?: number | null;
      rotation?: number;
      flip_h?: boolean;
    },
  ) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  batchUpdateMosaicPanels: (
    mosaicId: string,
    panels: Array<{ panel_id: string; grid_row?: number; grid_col?: number; rotation?: number; flip_h?: boolean }>,
    rotationAngle?: number,
  ) =>
    fetchJson<import("../types").PanelStats[]>(`/mosaics/${mosaicId}/panels/batch`, {
      method: "PUT",
      body: JSON.stringify({ panels, rotation_angle: rotationAngle }),
    }),

  removeMosaicPanel: (mosaicId: string, panelId: string) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, { method: "DELETE" }),

  getMosaicSuggestions: () =>
    fetchJson<import("../types").MosaicSuggestionResponse[]>("/mosaics/suggestions"),

  triggerMosaicDetection: () =>
    fetchJson<{ status: string; new_suggestions?: number; task_id?: string }>("/mosaics/detect", { method: "POST" }),

  acceptMosaicSuggestion: (id: string, selectedPanels?: string[]) =>
    fetchJson<import("../types").MosaicSummary>(`/mosaics/suggestions/${id}/accept`, {
      method: "POST",
      body: JSON.stringify({ selected_panels: selectedPanels ?? null }),
    }),

  dismissMosaicSuggestion: (id: string) =>
    fetchJson<{ status: string }>(`/mosaics/suggestions/${id}/dismiss`, { method: "POST" }),

  getPanelSessions: (mosaicId: string, panelId: string) =>
    fetchJson<import("../types").PanelSessionsResponse>(
      `/mosaics/${mosaicId}/panels/${panelId}/sessions`
    ),

  updatePanelSessions: (mosaicId: string, panelId: string, include: string[], exclude: string[]) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}/sessions`, {
      method: "PUT",
      body: JSON.stringify({ include, exclude }),
    }),

  // Custom Columns
  getCustomColumns: () =>
    fetchJson<CustomColumn[]>("/custom-columns"),

  createCustomColumn: (body: {
    name: string;
    column_type: string;
    applies_to: string;
    dropdown_options?: string[];
  }) =>
    fetchJson<CustomColumn>("/custom-columns", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateCustomColumn: (id: string, body: {
    name?: string;
    dropdown_options?: string[];
    display_order?: number;
  }) =>
    fetchJson<CustomColumn>(`/custom-columns/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteCustomColumn: (id: string) =>
    fetchJson<void>(`/custom-columns/${id}`, { method: "DELETE" }),

  getCustomValues: (targetId: string) =>
    fetchJson<CustomColumnValue[]>(`/custom-columns/values/${targetId}`),

  setCustomValue: (body: {
    column_id: string;
    target_id?: string | null;
    mosaic_id?: string | null;
    session_date?: string | null;
    rig_label?: string | null;
    value: string;
  }) =>
    fetchJson<void>("/custom-columns/values", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getColumnVisibility: (userId: string) =>
    fetchJson<ColumnVisibility>(`/settings/column-visibility/${userId}`),

  updateColumnVisibility: (body: ColumnVisibility) =>
    fetchJson<void>("/settings/column-visibility", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // Planning
  getNightEphemeris: (date: string) =>
    fetchJson<import("../types").NightEphemeris>(`/planning/night?date=${date}`),

  // Reference thumbnails
  getReferenceThumbnailUrl: (targetId: string) =>
    `${API_BASE}/targets/${encodeURIComponent(targetId)}/reference-thumbnail`,

  // Catalog enrichment tasks
  triggerReferenceThumbnails: (force = false) =>
    fetchJson<{ status: string; message: string; task_id?: string }>(`/scan/generate-reference-thumbnails${force ? "?force=true" : ""}`, { method: "POST" }),

  // Backup / Restore
  createBackup: async (): Promise<Blob> => {
    const resp = await fetchWithRefresh("/backup/create", { method: "POST" });
    if (!resp.ok) {
      throw await extractApiError(resp, "Failed to create backup");
    }
    return resp.blob();
  },

  validateBackup: async (
    file: File,
    mode: "merge" | "replace",
    sections: string[],
  ): Promise<ValidateResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("sections", sections.join(","));
    const resp = await fetchWithRefresh("/backup/validate", {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      throw await extractApiError(resp, "Failed to validate backup");
    }
    return resp.json();
  },

  restoreBackup: async (
    file: File,
    mode: "merge" | "replace",
    sections: string[],
  ): Promise<RestoreResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("sections", sections.join(","));
    const resp = await fetchWithRefresh("/backup/restore", {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      throw await extractApiError(resp, "Failed to restore backup");
    }
    return resp.json();
  },

  sendToNina: (url: string, ra: number, dec: number, position_angle?: number | null) =>
    fetchJson<{ ok: boolean; error?: string }>("/integrations/nina/send-coordinates", {
      method: "POST",
      body: JSON.stringify({ url, ra, dec, position_angle }),
    }),

  sendToStellarium: (url: string, ra: number, dec: number, targetName: string | null) =>
    fetchJson<{ ok: boolean; error?: string }>("/integrations/stellarium/send-coordinates", {
      method: "POST",
      body: JSON.stringify({ url, ra, dec, target_name: targetName }),
    }),
};
