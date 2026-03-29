import { createResource } from "solid-js";
import { api } from "../api/client";
import type { SettingsResponse, GeneralSettings, FilterConfig, EquipmentConfig, DisplaySettings } from "../types";

const [settingsData, { refetch: refetchSettings }] = createResource(() => api.getSettings());

export function useSettings() {
  return {
    settings: settingsData,
    refetchSettings,

    async saveGeneral(general: GeneralSettings) {
      const result = await api.updateGeneral(general);
      refetchSettings();
      return result;
    },

    async saveFilters(filters: Record<string, FilterConfig>) {
      const result = await api.updateFilters(filters);
      refetchSettings();
      return result;
    },

    async saveEquipment(equipment: EquipmentConfig) {
      const result = await api.updateEquipment(equipment);
      refetchSettings();
      return result;
    },

    async saveDisplay(display: DisplaySettings) {
      await api.updateDisplay(display);
      refetchSettings();
    },

    getFilterSuggestions: () => api.getFilterSuggestions(),
    getEquipmentSuggestions: () => api.getEquipmentSuggestions(),
  };
}

export function getFilterColorMap(settings: SettingsResponse | undefined): Record<string, string> {
  const defaults: Record<string, string> = {
    Ha: "#c44040", OIII: "#3a8fd4", SII: "#d4a43a",
    L: "#e0e0e0", R: "#e05050", G: "#50b050", B: "#5070e0",
  };
  if (!settings) return defaults;
  const map: Record<string, string> = { ...defaults };
  for (const [name, conf] of Object.entries(settings.filters)) {
    map[name] = conf.color;
  }
  return map;
}

export function getFilterAliasMap(settings: SettingsResponse | undefined): Record<string, string> {
  if (!settings) return {};
  const map: Record<string, string> = {};
  for (const [canonical, conf] of Object.entries(settings.filters)) {
    for (const alias of conf.aliases) {
      map[alias] = canonical;
    }
  }
  return map;
}
