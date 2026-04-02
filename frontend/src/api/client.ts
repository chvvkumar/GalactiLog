import type {
  TargetAggregationResponse,
  SessionDetail,
  EquipmentList,
  TargetSearchResult,
  TargetSearchResultFuzzy,
  ObjectTypeCount,
  MergeCandidateResponse,
  MergedTargetResponse,
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
} from "../types";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

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

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
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
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Session expired");
  }

  if (!resp.ok) {
    throw new ApiError(resp.status, `API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

function buildTargetQuery(filters: ActiveFilters, page?: number, pageSize?: number): string {
  const params = new URLSearchParams();
  if (page != null) params.set("page", String(page));
  if (pageSize != null) params.set("page_size", String(pageSize));
  if (filters.searchQuery) params.set("search", filters.searchQuery);
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
  return params.toString();
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    fetchJson<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
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

  getTargets: (filters: ActiveFilters, page?: number, pageSize?: number) =>
    fetchJson<TargetAggregationResponse>(`/targets?${buildTargetQuery(filters, page, pageSize)}`),

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

  regenerateThumbnails: () =>
    fetchJson<ScanResult>("/scan/regenerate-thumbnails", { method: "POST" }),

  resetScan: () =>
    fetchJson<{ status: string }>("/scan/reset", { method: "POST" }),

  stopScan: () =>
    fetchJson<{ status: string; message?: string }>("/scan/stop", { method: "POST" }),

  getActivity: () =>
    fetchJson<import("../types").ActivityEntry[]>("/scan/activity"),

  clearActivity: () =>
    fetchJson<{ status: string }>("/scan/activity", { method: "DELETE" }),

  rebuildTargets: () =>
    fetchJson<{ status: string; message: string }>("/scan/rebuild-targets", { method: "POST" }),

  smartRebuildTargets: () =>
    fetchJson<{ status: string; message: string }>("/scan/smart-rebuild-targets", { method: "POST" }),

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

  triggerDuplicateDetection: () =>
    fetchJson<{ status: string; task_id: string }>("/targets/detect-duplicates", {
      method: "POST",
    }),

  getCorrelation: (params: {
    x_metric: string;
    y_metric: string;
    telescope?: string;
    camera?: string;
    granularity?: "frame" | "session";
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("x_metric", params.x_metric);
    qs.set("y_metric", params.y_metric);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.granularity) qs.set("granularity", params.granularity);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").CorrelationResponse>(`/analysis/correlation?${qs}`);
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

  updateMosaic: (id: string, data: { name?: string; notes?: string }) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteMosaic: (id: string) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, { method: "DELETE" }),

  addMosaicPanel: (mosaicId: string, targetId: string, label: string) =>
    fetchJson<{ status: string; panel_id: string }>(`/mosaics/${mosaicId}/panels`, {
      method: "POST",
      body: JSON.stringify({ target_id: targetId, panel_label: label }),
    }),

  updateMosaicPanel: (mosaicId: string, panelId: string, data: { panel_label?: string; sort_order?: number }) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  removeMosaicPanel: (mosaicId: string, panelId: string) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, { method: "DELETE" }),

  getMosaicSuggestions: () =>
    fetchJson<import("../types").MosaicSuggestionResponse[]>("/mosaics/suggestions"),

  triggerMosaicDetection: () =>
    fetchJson<{ status: string; new_suggestions: number }>("/mosaics/detect", { method: "POST" }),

  acceptMosaicSuggestion: (id: string) =>
    fetchJson<import("../types").MosaicSummary>(`/mosaics/suggestions/${id}/accept`, { method: "POST" }),

  dismissMosaicSuggestion: (id: string) =>
    fetchJson<{ status: string }>(`/mosaics/suggestions/${id}/dismiss`, { method: "POST" }),
};
