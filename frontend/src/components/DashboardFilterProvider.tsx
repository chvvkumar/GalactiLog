import { Component, JSX, createContext, createEffect, createMemo, createSignal, useContext } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { useQuery } from "@tanstack/solid-query";
import { apiClient } from "../api/generated/client";
import type { paths } from "../api/generated/schema";
import { unwrap } from "../api/unwrap";
import { queryKeys } from "../api/queryKeys";
import { useSettingsContext } from "./SettingsProvider";
import type { ActiveFilters } from "../api/types";
// TargetAggregationResponse is the hand-written definition in `../api/types`
// (nested `TargetAggregation.catalog_id` is required), rather than the
// generated schema, which omits `catalog_id` entirely (a real
// backend/OpenAPI schema gap -- the field IS returned by GET /api/targets,
// it's just missing from the Pydantic response model's declared fields).
// `targetData` is consumed by TargetFeed -> TargetTable (and by
// Sidebar/DateRangePicker) against this shape: cast the apiClient result to
// this type at the fetch boundary below.
import type { TargetAggregationResponse } from "../api/types";

export type SortKey = "name" | "integration" | "lastSession" | "equipment";
export type SortDir = "asc" | "desc";

// Resource-shaped accessor kept for source compatibility with out-of-scope
// consumers (Slice 5's TargetTable/TargetFeed, plus Sidebar/DateRangePicker)
// that call `targetData()` and read `.loading`/`.latest` the way Solid's
// `createResource` exposes them. See the "Query shape" comment on
// `targetsQuery` below for how this is built on top of `useQuery`.
export interface TargetDataResource {
  (): TargetAggregationResponse | undefined;
  readonly loading: boolean;
  readonly latest: TargetAggregationResponse | undefined;
}

interface DashboardFilterAPI {
  filters: () => ActiveFilters;
  targetData: TargetDataResource;
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
  "fits_key", "fits_op", "fits_val", "cc_filters", "catalog",
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

// Ports the old client.ts `buildTargetQuery` URLSearchParams logic (client.ts:196-235)
// into a typed query object for openapi-fetch's `params: { query: {...} } }`,
// preserving today's exact param names/encoding. `fits_key`/`fits_op`/`fits_val`
// stay as parallel arrays (openapi-fetch's default "form"/explode serializer
// emits repeated `key=a&key=b` query params, matching the old `.append()` calls
// and the backend's `List[str]` query params) instead of the old comma-joined
// strings used for `filters`/`object_type`.
type TargetQueryParams = NonNullable<paths["/api/targets"]["get"]["parameters"]["query"]>;

function buildTargetQueryParams(
  filters: ActiveFilters,
  page?: number,
  pageSize?: number,
  sortBy?: string,
  sortDir?: string,
  includeCustom?: boolean,
): TargetQueryParams {
  const params: TargetQueryParams = {};
  if (page != null) params.page = page;
  if (pageSize != null) params.page_size = pageSize;
  if (sortBy) params.sort_by = sortBy;
  if (sortDir) params.sort_dir = sortDir;
  if (filters.selectedTargetId) params.target_id = filters.selectedTargetId;
  else if (filters.searchQuery) params.search = filters.searchQuery;
  if (filters.camera) params.camera = filters.camera;
  if (filters.telescope) params.telescope = filters.telescope;
  if (filters.opticalFilters.length > 0) params.filters = filters.opticalFilters.join(",");
  if (filters.objectTypes.length > 0) params.object_type = filters.objectTypes.join(",");
  if (filters.dateRange.start) params.date_from = filters.dateRange.start;
  if (filters.dateRange.end) params.date_to = filters.dateRange.end;
  if (filters.qualityFilters.hfrMin != null) params.hfr_min = filters.qualityFilters.hfrMin;
  if (filters.qualityFilters.hfrMax != null) params.hfr_max = filters.qualityFilters.hfrMax;
  if (filters.fitsQueries.length > 0) {
    params.fits_key = filters.fitsQueries.map((q) => q.key);
    params.fits_op = filters.fitsQueries.map((q) => q.operator);
    params.fits_val = filters.fitsQueries.map((q) => q.value);
  }
  const loose = params as Record<string, unknown>;
  for (const [metric, range] of Object.entries(filters.metricFilters)) {
    if (range.min != null) loose[`${metric}_min`] = range.min;
    if (range.max != null) loose[`${metric}_max`] = range.max;
  }
  if (filters.customColumnFilters.length > 0) {
    params.custom_filters = JSON.stringify(filters.customColumnFilters);
  }
  if (filters.catalog) params.catalog = filters.catalog;
  if (includeCustom) params.include_custom = true;
  return params;
}

type RawSearchParams = Record<string, string | string[] | undefined>;

function firstValue(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

function hasFilterParams(sp: RawSearchParams): boolean {
  return ALL_PARAM_KEYS.some((k) => {
    const v = firstValue(sp[k]);
    return v !== undefined && v !== "";
  });
}

function deriveFilters(rawSp: RawSearchParams): ActiveFilters {
  const sp: Record<string, string | undefined> = {};
  for (const k in rawSp) sp[k] = firstValue(rawSp[k]);
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
    catalog: sp.catalog || null,
  };
}

const DashboardFilterProvider: Component<{ children: JSX.Element }> = (props) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const settingsCtx = useSettingsContext();

  const filters = createMemo(() => deriveFilters(searchParams));

  // Sort state - persisted to localStorage
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

  // Map frontend sort keys to backend API values. All sort keys, including
  // "equipment", are handled server-side (see targets.py sort_by).
  const apiSortBy = createMemo(() => sortKey());

  const currentPage = createMemo(() => {
    const raw = searchParams.page;
    const p = parseInt(typeof raw === "string" ? raw : "1");
    return isNaN(p) || p < 1 ? 1 : p;
  });

  // Page size: an explicit user choice takes precedence; otherwise derive from the saved
  // default. This is a lazy memo, NOT a Suspense-deferred createEffect: when this provider
  // mounts while settings are still pending under a suspended boundary (cold login, issue
  // #264), an init effect would be held by Suspense and never flip the gate, deadlocking the
  // dashboard on "Loading...". A memo recomputes on read once settings resolve, so the first
  // /api/targets fetch still uses the correct saved page size without an effect.
  const [userPageSize, setUserPageSize] = createSignal<number | null>(null);
  const currentPageSize = createMemo(
    () => userPageSize() ?? settingsCtx.settings()?.general.default_page_size ?? 25,
  );

  // Resource key combines filters + pagination + sort so changes to any trigger a refetch
  const hasCustomColumns = createMemo(() => {
    const cols = settingsCtx.customColumns();
    return Array.isArray(cols) && cols.length > 0;
  });

  // Gate the initial /api/targets fetch until the saved settings (page size) and the
  // custom-columns flag have both resolved. Without this, the resource fires once at the
  // default page size (25) before settings load, then settings/customColumns arrive and
  // flip pageSize / includeCustom, cancelling (net::ERR_ABORTED) and re-issuing the request.
  // createResource skips fetching while its source returns null/undefined/false, so by
  // returning null here until both resources are ready we guarantee exactly one request
  // for the default view, at the correct saved page size. currentPageSize derives from
  // settings() directly, so once settings resolve the memo below flips and the first fetch
  // already carries the saved page size.
  const settingsReady = createMemo(() =>
    settingsCtx.settings() !== undefined && settingsCtx.customColumns() !== undefined,
  );

  // Query shape depended on by Slice 5 (TargetTable/TargetFeed) and by
  // Sidebar/DateRangePicker: `useQuery` (via TanStack Query, replacing the
  // old `createResource`) drives the actual fetch, wrapped in `apiClient` +
  // `unwrap` per the migration convention. `enabled` replicates the old
  // `fetchKey` null-skip -- the query does not fire until settings +
  // custom-columns have both resolved (see settingsReady's comment above),
  // avoiding the double-fetch/cancel race described there. `queryFn`'s
  // `signal` is TanStack's own AbortSignal (cancelled automatically on
  // query-key change or unmount), replacing the old hand-rolled
  // `AbortController` -- do not reintroduce manual abort tracking here.
  const targetsQuery = useQuery(() => ({
    queryKey: queryKeys.targets(filters(), currentPage(), currentPageSize(), apiSortBy(), sortDir(), hasCustomColumns()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient
        .GET("/api/targets", {
          params: { query: buildTargetQueryParams(filters(), currentPage(), currentPageSize(), apiSortBy(), sortDir(), hasCustomColumns()) },
          signal,
        })
        .then(unwrap) as Promise<TargetAggregationResponse>,
    enabled: settingsReady(),
  }));

  // `.latest` mirrors Solid `createResource`'s behavior of retaining the last
  // successfully-resolved value across a refetch (TargetFeed/Sidebar's
  // `targetData() ?? targetData.latest` fallback relies on this so the table
  // doesn't flash empty while a filter-driven refetch is in flight).
  const [latestTargetData, setLatestTargetData] = createSignal<TargetAggregationResponse | undefined>(undefined);
  createEffect(() => {
    const d = targetsQuery.data;
    if (d !== undefined) setLatestTargetData(() => d);
  });

  const targetData = (() => targetsQuery.data) as TargetDataResource;
  Object.defineProperty(targetData, "loading", { enumerable: true, get: () => targetsQuery.isFetching });
  Object.defineProperty(targetData, "latest", { enumerable: true, get: () => latestTargetData() });

  const refetchTargets = () => {
    void targetsQuery.refetch();
  };

  const fetchError = (): Error | null => {
    const e = targetsQuery.error;
    if (!e) return null;
    return e instanceof Error ? e : new Error(String(e));
  };

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
    setUserPageSize(size);
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
      case "catalog":
        set({ catalog: value || undefined });
        break;
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
    try {
      sessionStorage.removeItem("dashboard_params");
    } catch { /* ignore */ }
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
