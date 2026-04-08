import { Component, JSX, createContext, createMemo, createSignal, useContext } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { createResource } from "solid-js";
import { api } from "../api/client";
import { useSettingsContext } from "./SettingsProvider";
import type { ActiveFilters, TargetAggregationResponse } from "../types";

export type SortKey = "name" | "integration" | "lastSession" | "equipment";
export type SortDir = "asc" | "desc";

interface DashboardFilterAPI {
  filters: () => ActiveFilters;
  targetData: ReturnType<typeof createResource<TargetAggregationResponse | undefined>>[0];
  refetchTargets: () => void;
  fetchError: () => Error | null;
  updateFilter: (key: string, value: any) => void;
  toggleOpticalFilter: (name: string) => void;
  toggleObjectType: (type: string) => void;
  updateQualityFilters: (qf: { hfrMin?: number; hfrMax?: number }) => void;
  updateMetricFilter: (metric: string, range: { min?: number; max?: number }) => void;
  addFitsQuery: (key: string, operator: string, value: string) => void;
  removeFitsQuery: (index: number) => void;
  setCustomColumnFilter: (slug: string, value: string | null) => void;
  customColumnFilters: () => { slug: string; value: string }[];
  resetFilters: () => void;
  page: () => number;
  pageSize: () => number;
  totalCount: () => number;
  totalPages: () => number;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  sortKey: () => SortKey;
  sortDir: () => SortDir;
  toggleSort: (key: SortKey) => void;
}

const DashboardFilterContext = createContext<DashboardFilterAPI>();

export function useDashboardFilters(): DashboardFilterAPI {
  const ctx = useContext(DashboardFilterContext);
  if (!ctx) throw new Error("useDashboardFilters must be used inside DashboardFilterProvider");
  return ctx;
}

const FILTER_KEYS = [
  "search", "target_id", "camera", "telescope", "filters", "object_type",
  "date_from", "date_to", "hfr_min", "hfr_max",
  "fits_key", "fits_op", "fits_val", "cc_filters",
];
const METRIC_KEYS = [
  "fwhm", "eccentricity", "stars", "guiding_rms", "adu_mean",
  "focuser_temp", "ambient_temp", "humidity", "airmass",
];
const ALL_PARAM_KEYS = [
  ...FILTER_KEYS,
  ...METRIC_KEYS.flatMap((k) => [`${k}_min`, `${k}_max`]),
  "page",
];

function hasFilterParams(sp: Record<string, string | undefined>): boolean {
  return ALL_PARAM_KEYS.some((k) => sp[k] !== undefined && sp[k] !== "");
}

function deriveFilters(sp: Record<string, string | undefined>): ActiveFilters {
  const fitsKeys = sp.fits_key?.split(",").filter(Boolean) ?? [];
  const fitsOps = sp.fits_op?.split(",").filter(Boolean) ?? [];
  const fitsVals = sp.fits_val?.split(",").filter(Boolean) ?? [];
  const fitsQueries = fitsKeys.map((key, i) => ({
    key,
    operator: fitsOps[i] ?? "eq",
    value: fitsVals[i] ?? "",
  }));

  const qualityFilters: { hfrMin?: number; hfrMax?: number } = {};
  if (sp.hfr_min) qualityFilters.hfrMin = parseFloat(sp.hfr_min);
  if (sp.hfr_max) qualityFilters.hfrMax = parseFloat(sp.hfr_max);

  const metricFilters: Record<string, { min?: number; max?: number }> = {};
  for (const key of METRIC_KEYS) {
    const min = sp[`${key}_min`];
    const max = sp[`${key}_max`];
    if (min != null || max != null) {
      metricFilters[key] = {};
      if (min != null) metricFilters[key].min = parseFloat(min);
      if (max != null) metricFilters[key].max = parseFloat(max);
    }
  }

  let customColumnFilters: { slug: string; value: string }[] = [];
  if (sp.cc_filters) {
    try {
      customColumnFilters = JSON.parse(sp.cc_filters);
    } catch { /* ignore malformed */ }
  }

  return {
    searchQuery: sp.search ?? "",
    selectedTargetId: sp.target_id || null,
    camera: sp.camera || null,
    telescope: sp.telescope || null,
    opticalFilters: sp.filters?.split(",").filter(Boolean) ?? [],
    objectTypes: sp.object_type?.split(",").filter(Boolean) ?? [],
    dateRange: {
      start: sp.date_from || null,
      end: sp.date_to || null,
    },
    fitsQueries,
    qualityFilters,
    metricFilters,
    customColumnFilters,
  };
}

const DashboardFilterProvider: Component<{ children: JSX.Element }> = (props) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const settingsCtx = useSettingsContext();

  const filters = createMemo(() => deriveFilters(searchParams));

  // Sort state — persisted to localStorage
  let initialSort: { key: SortKey; dir: SortDir } = { key: "integration", dir: "desc" };
  try {
    const stored = localStorage.getItem("dashboard_sort");
    if (stored) initialSort = JSON.parse(stored);
  } catch { /* ignore corrupt localStorage */ }

  const [sortKey, setSortKey] = createSignal<SortKey>(initialSort.key);
  const [sortDir, setSortDir] = createSignal<SortDir>(initialSort.dir);

  const persistSort = (key: SortKey, dir: SortDir) => {
    localStorage.setItem("dashboard_sort", JSON.stringify({ key, dir }));
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey() === key) {
      const newDir = sortDir() === "asc" ? "desc" : "asc";
      setSortDir(newDir);
      persistSort(key, newDir);
    } else {
      const newDir = key === "name" ? "asc" : "desc";
      setSortKey(key);
      setSortDir(newDir);
      persistSort(key, newDir);
    }
    // Reset to page 1 when sort changes
    setSearchParams({ page: undefined }, { replace: true });
  };

  // Map frontend sort keys to backend API values
  const apiSortBy = createMemo(() => {
    const key = sortKey();
    // "equipment" has no backend sort — fall back to integration
    if (key === "equipment") return "integration";
    return key;
  });

  const currentPage = createMemo(() => {
    const raw = searchParams.page;
    const p = parseInt(typeof raw === "string" ? raw : "1");
    return isNaN(p) || p < 1 ? 1 : p;
  });

  const currentPageSize = createMemo(() => {
    return settingsCtx.settings()?.general.default_page_size ?? 50;
  });

  // Resource key combines filters + pagination + sort so changes to any trigger a refetch
  const fetchKey = createMemo(() => ({
    filters: filters(), page: currentPage(), pageSize: currentPageSize(),
    sortBy: apiSortBy(), sortDir: sortDir(),
  }));

  let abortController: AbortController | undefined;
  const [fetchError, setFetchError] = createSignal<Error | null>(null);

  const [targetData, { refetch: refetchTargets }] = createResource(fetchKey, async (k) => {
    abortController?.abort();
    abortController = new AbortController();
    const signal = abortController.signal;
    try {
      const result = await api.getTargets(k.filters, k.page, k.pageSize, k.sortBy, k.sortDir, signal);
      setFetchError(null);
      return result;
    } catch (e) {
      if (signal.aborted) return undefined as unknown as TargetAggregationResponse;
      setFetchError(e instanceof Error ? e : new Error(String(e)));
      return undefined as unknown as TargetAggregationResponse;
    }
  });

  const set = (updates: Record<string, string | undefined>) => {
    // Reset to page 1 when any filter changes (but not when only page changes)
    if (!("page" in updates)) {
      updates.page = undefined;
    }
    setSearchParams(updates, { replace: true });
  };

  const setPage = (p: number) => {
    setSearchParams({ page: p > 1 ? String(p) : undefined }, { replace: true });
  };

  const setPageSize = (size: number) => {
    const current = settingsCtx.settings()?.general;
    if (current) {
      settingsCtx.saveGeneral({ ...current, default_page_size: size });
    }
    // Reset to page 1 when page size changes
    setSearchParams({ page: undefined }, { replace: true });
  };

  const updateFilter = (key: string, value: any) => {
    switch (key) {
      case "searchQuery":
        set({ search: value || undefined, target_id: undefined });
        break;
      case "selectedTargetId":
        set({ target_id: value || undefined, search: undefined });
        break;
      case "camera":
        set({ camera: value || undefined });
        break;
      case "telescope":
        set({ telescope: value || undefined });
        break;
      case "dateRange": {
        const dr = value as { start: string | null; end: string | null };
        set({ date_from: dr.start || undefined, date_to: dr.end || undefined });
        break;
      }
      default:
        break;
    }
  };

  const toggleOpticalFilter = (name: string) => {
    const current = filters().opticalFilters;
    const next = current.includes(name)
      ? current.filter((x) => x !== name)
      : [...current, name];
    set({ filters: next.length > 0 ? next.join(",") : undefined });
  };

  const toggleObjectType = (type: string) => {
    const current = filters().objectTypes;
    const next = current.includes(type)
      ? current.filter((x) => x !== type)
      : [...current, type];
    set({ object_type: next.length > 0 ? next.join(",") : undefined });
  };

  const updateQualityFilters = (qf: { hfrMin?: number; hfrMax?: number }) => {
    set({
      hfr_min: qf.hfrMin != null ? String(qf.hfrMin) : undefined,
      hfr_max: qf.hfrMax != null ? String(qf.hfrMax) : undefined,
    });
  };

  const updateMetricFilter = (metric: string, range: { min?: number; max?: number }) => {
    set({
      [`${metric}_min`]: range.min != null ? String(range.min) : undefined,
      [`${metric}_max`]: range.max != null ? String(range.max) : undefined,
    });
  };

  const addFitsQuery = (key: string, operator: string, value: string) => {
    const current = filters().fitsQueries;
    const next = [...current, { key, operator, value }];
    set({
      fits_key: next.map((q) => q.key).join(","),
      fits_op: next.map((q) => q.operator).join(","),
      fits_val: next.map((q) => q.value).join(","),
    });
  };

  const removeFitsQuery = (index: number) => {
    const next = filters().fitsQueries.filter((_, i) => i !== index);
    set({
      fits_key: next.length > 0 ? next.map((q) => q.key).join(",") : undefined,
      fits_op: next.length > 0 ? next.map((q) => q.operator).join(",") : undefined,
      fits_val: next.length > 0 ? next.map((q) => q.value).join(",") : undefined,
    });
  };

  const setCustomColumnFilter = (slug: string, value: string | null) => {
    const current = filters().customColumnFilters;
    let next: { slug: string; value: string }[];
    if (!value) {
      next = current.filter((f) => f.slug !== slug);
    } else {
      const exists = current.find((f) => f.slug === slug);
      if (exists) {
        next = current.map((f) => (f.slug === slug ? { slug, value } : f));
      } else {
        next = [...current, { slug, value }];
      }
    }
    set({
      cc_filters: next.length > 0 ? JSON.stringify(next) : undefined,
    });
  };

  const resetFilters = () => {
    const clear: Record<string, undefined> = {};
    for (const key of ALL_PARAM_KEYS) {
      clear[key] = undefined;
    }
    set(clear);
  };

  const value: DashboardFilterAPI = {
    filters,
    targetData,
    refetchTargets,
    fetchError,
    updateFilter,
    toggleOpticalFilter,
    toggleObjectType,
    updateQualityFilters,
    updateMetricFilter,
    addFitsQuery,
    removeFitsQuery,
    setCustomColumnFilter,
    customColumnFilters: () => filters().customColumnFilters,
    resetFilters,
    page: currentPage,
    pageSize: currentPageSize,
    totalCount: () => targetData()?.total_count ?? 0,
    totalPages: () => {
      const data = targetData();
      if (!data) return 1;
      return Math.max(1, Math.ceil(data.total_count / data.page_size));
    },
    setPage,
    setPageSize,
    sortKey,
    sortDir,
    toggleSort,
  };

  return (
    <DashboardFilterContext.Provider value={value}>
      {props.children}
    </DashboardFilterContext.Provider>
  );
};

export { hasFilterParams, ALL_PARAM_KEYS };
export default DashboardFilterProvider;
