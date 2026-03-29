import { createContext, useContext, createEffect, type ParentComponent } from "solid-js";
import { useSettings, getFilterColorMap, getFilterAliasMap } from "../store/settings";
import { useGraphSettings } from "../store/graphSettings";
import type { SettingsResponse, GeneralSettings, FilterConfig, EquipmentConfig, DisplaySettings, GraphSettings } from "../types";
import type { Resource } from "solid-js";
import type { FilterBadgeStyle } from "../utils/filterStyles";
import { applyTheme, applyTextSize, DEFAULT_THEME_ID, DEFAULT_TEXT_SIZE } from "../themes";

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
}

const SettingsContext = createContext<SettingsContextValue>();

export const SettingsProvider: ParentComponent = (props) => {
  const store = useSettings();
  const graphStore = useGraphSettings();

  graphStore.loadGraphSettings();

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
    filterBadgeStyle: () => (store.settings()?.general.filter_style as FilterBadgeStyle) || "solid",
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
