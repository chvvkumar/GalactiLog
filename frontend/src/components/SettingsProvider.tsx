import { createContext, useContext, createEffect, createSignal, createResource, startTransition, type ParentComponent } from "solid-js";
import { useSettings, getFilterColorMap, getFilterAliasMap, enableSettingsFetch, seedSettings } from "../store/settings";
import { seedEquipment } from "../store/catalog";
import { seedFilterOptions } from "../store/filterOptions";
import { useGraphSettings } from "../store/graphSettings";
import type { ColumnVisibility } from "../api/types";
// Deliberately kept on the OLD hand-written settings/custom-column types
// (required `FilterConfig.aliases`, `GeneralSettings.nina_instances`/
// `stellarium_instances` typed as `IntegrationInstance[]`, literal-union
// `CustomColumn.column_type`/`applies_to`, etc.) rather than the
// generated-schema aliases in `../api/types`, which loosen these fields to
// optional/untyped (backend Pydantic defaults/enums collapsed by the OpenAPI
// dump). `store/settings.ts` and `store/graphSettings.ts` (Slice 2) already
// depend on this narrower shape, and SettingsContextValue is consumed by
// nearly every page (CustomColumnsTab/TargetTable/SessionTable/MosaicsTab/
// FiltersTab/EquipmentTab/AstroBinTab/...), none of which are in this
// slice's scope. Repointing here would ripple required->optional and
// string->literal-union breaks well outside this slice. Same precedent as
// store/stats.ts and store/graphSettings.ts. The backend always populates
// the full shape, so the casts at the apiClient call sites below reflect
// actual runtime data, not a behavior change.
import type { SettingsResponse, GeneralSettings, FilterConfig, EquipmentConfig, DisplaySettings, GraphSettings, CustomColumn } from "../types";
import type { Resource } from "solid-js";
import type { FilterBadgeStyle } from "../utils/filterStyles";
import { applyTheme, applyTextSize, DEFAULT_THEME_ID, DEFAULT_TEXT_SIZE } from "../themes";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { useAuth } from "./AuthProvider";

interface SettingsContextValue {
  settings: Resource<SettingsResponse | undefined>;
  filterColorMap: () => Record<string, string>;
  filterAliasMap: () => Record<string, string>;
  filterBadgeStyle: () => FilterBadgeStyle;
  saveGeneral: (g: GeneralSettings) => Promise<SettingsResponse>;
  saveFilters: (f: Record<string, FilterConfig>) => Promise<SettingsResponse>;
  saveEquipment: (e: EquipmentConfig) => Promise<SettingsResponse>;
  refetchSettings: () => void;
  displaySettings: () => DisplaySettings | undefined;
  saveDisplay: (display: DisplaySettings) => Promise<void>;
  graphSettings: () => GraphSettings;
  toggleMetric: (metric: string) => void;
  toggleFilter: (filter: string) => void;
  saveGraphSettings: (updates: Partial<GraphSettings>) => Promise<void>;
  timezone: () => string;
  use24hTime: () => boolean;
  contentWidth: () => string;
  customColumns: Resource<CustomColumn[] | undefined>;
  refetchCustomColumns: () => void;
  columnVisibility: () => ColumnVisibility | undefined;
  saveColumnVisibility: (vis: ColumnVisibility) => Promise<void>;
}

const SettingsContext = createContext<SettingsContextValue>();

export const SettingsProvider: ParentComponent = (props) => {
  const store = useSettings();
  const graphStore = useGraphSettings();
  const auth = useAuth();
  // Custom columns are gated so bootstrap can seed them without a redundant
  // fetch; the gate opens once bootstrap resolves (or falls back).
  const [ccGate, setCCGate] = createSignal(false);
  let pendingCustomColumnsSeed: CustomColumn[] | null = null;
  const [customColumns, { refetch: rawRefetchCustomColumns, mutate: mutateCustomColumns }] = createResource(
    ccGate,
    async () => {
      if (pendingCustomColumnsSeed) {
        const s = pendingCustomColumnsSeed;
        pendingCustomColumnsSeed = null;
        return s;
      }
      return apiClient.GET("/api/custom-columns", {}).then(unwrap) as Promise<CustomColumn[]>;
    },
  );
  const refetchCustomColumns = () => startTransition(() => rawRefetchCustomColumns());
  const [columnVisibility, setColumnVisibility] = createSignal<ColumnVisibility | undefined>(undefined);

  graphStore.loadGraphSettings();

  // One bootstrap request replaces the five separate startup calls (settings,
  // equipment, fits keys, object types, custom columns), seeding each store.
  // Individual endpoints remain for later refreshes; on failure, fall back to
  // fetching each store on demand.
  createEffect(() => {
    if (!auth.user()) return;
    apiClient
      .GET("/api/bootstrap", {})
      .then(unwrap)
      .then((b) => {
        // The generated BootstrapResponse types `settings` as a loose
        // Record<string, unknown> (FastAPI response model looseness) and
        // `custom_columns` as BootstrapCustomColumn[] with a few fields
        // optional (created_at, display_order) where SettingsResponse/
        // CustomColumn require them. The backend always populates the full
        // shape here (same endpoint the old hand-written client called), so
        // these casts reflect actual runtime data, not a behavior change --
        // see api/types.ts's discrepancy note.
        seedSettings(b.settings as unknown as SettingsResponse);
        seedEquipment(b.equipment);
        seedFilterOptions(b.fits_keys, b.object_types);
        const customColumns = b.custom_columns as unknown as CustomColumn[];
        pendingCustomColumnsSeed = customColumns;
        mutateCustomColumns(customColumns);
        setCCGate(true);
      })
      .catch(() => {
        enableSettingsFetch();
        setCCGate(true);
      });
  });

  // Load column visibility when user is authenticated
  createEffect(() => {
    const u = auth.user();
    if (u?.id) {
      apiClient
        .GET("/api/settings/column-visibility/{user_id}", { params: { path: { user_id: u.id } } })
        .then(unwrap)
        .then((vis) => setColumnVisibility(vis as ColumnVisibility))
        .catch(() => {});
    }
  });

  createEffect(() => {
    const themeId = store.settings()?.general.theme ?? DEFAULT_THEME_ID;
    applyTheme(themeId);
  });

  createEffect(() => {
    const sizeId = store.settings()?.general.text_size ?? DEFAULT_TEXT_SIZE;
    applyTextSize(sizeId);
  });

  const value: SettingsContextValue = {
    settings: store.settings,
    filterColorMap: () => getFilterColorMap(store.settings()),
    filterAliasMap: () => getFilterAliasMap(store.settings()),
    filterBadgeStyle: () => (store.settings()?.general.filter_style as FilterBadgeStyle) || "text-only",
    timezone: () => store.settings()?.general.timezone ?? "UTC",
    use24hTime: () => store.settings()?.general.use_24h_time ?? false,
    contentWidth: () => store.settings()?.general.content_width ?? "full",
    saveGeneral: store.saveGeneral,
    saveFilters: store.saveFilters,
    saveEquipment: store.saveEquipment,
    refetchSettings: store.refetchSettings,
    displaySettings: () => store.settings()?.display,
    saveDisplay: store.saveDisplay,
    graphSettings: graphStore.graphSettings,
    toggleMetric: graphStore.toggleMetric,
    toggleFilter: graphStore.toggleFilter,
    saveGraphSettings: graphStore.saveGraphSettings,
    customColumns,
    refetchCustomColumns,
    columnVisibility,
    saveColumnVisibility: async (vis: ColumnVisibility) => {
      await apiClient.PUT("/api/settings/column-visibility", { body: vis }).then(unwrap);
      setColumnVisibility(vis);
    },
  };

  return (
    <SettingsContext.Provider value={value}>
      {props.children}
    </SettingsContext.Provider>
  );
};

export function useSettingsContext() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettingsContext must be used within SettingsProvider");
  return ctx;
}
