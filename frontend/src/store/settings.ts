import { createSignal, createResource, startTransition } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
// Deliberately kept on the OLD hand-written settings types (required
// `FilterConfig.aliases`, `GeneralSettings.nina_instances`/
// `stellarium_instances` typed as `IntegrationInstance[]`, etc.) rather than
// the generated-schema aliases in `../api/types`, which loosen several of
// these fields to optional/untyped (backend Pydantic defaults collapsed by
// the OpenAPI dump). `store/graphSettings.ts` (Slice 2) already depends on
// `SettingsResponse.graph` carrying the old, required-field `GraphSettings`
// shape, and this store is consumed by nearly every page -- repointing here
// would ripple a required->optional break into files well outside this
// slice's scope. Same precedent as store/stats.ts and store/graphSettings.ts.
// The backend always populates the full shape, so the casts below reflect
// actual runtime data, not a behavior change.
import type { SettingsResponse, GeneralSettings, FilterConfig, EquipmentConfig, DisplaySettings } from "../types";
// The generated GeneralSettings schema marks several Pydantic-default fields
// (activity_retention_days, app_log_*, mosaic_position_tolerance_arcmin) as
// required, even though the backend model supplies defaults for them and
// tolerates a PUT body that omits them (the old hand-written GeneralSettings
// type -- and every caller of saveGeneral -- has never included these
// fields). Cast at the request boundary only; this preserves the exact
// request body the old fetchJson-based client sent.
import type { GeneralSettings as GeneratedGeneralSettings } from "../api/types";

const [settingsGate, setSettingsGate] = createSignal(false);
export function enableSettingsFetch() { setSettingsGate(true); }

// One-shot seed consumed by the resource's first run so that opening the gate
// after a bootstrap load does not fire a redundant GET /settings. Manual
// refetches still hit the API.
let pendingSettingsSeed: SettingsResponse | null = null;
const [settingsData, { refetch: refetchSettings, mutate: mutateSettings }] = createResource(
  settingsGate,
  async () => {
    if (pendingSettingsSeed) {
      const s = pendingSettingsSeed;
      pendingSettingsSeed = null;
      return s;
    }
    return apiClient.GET("/api/settings", {}).then(unwrap) as Promise<SettingsResponse>;
  },
);

export function seedSettings(data: SettingsResponse) {
  pendingSettingsSeed = data;
  mutateSettings(data);
  setSettingsGate(true);
}

/** Refetch settings without triggering the Suspense boundary */
const quietRefetch = () => startTransition(() => refetchSettings());

export function useSettings() {
  return {
    settings: settingsData,
    refetchSettings: quietRefetch,

    async saveGeneral(general: GeneralSettings) {
      const result = await apiClient
        .PUT("/api/settings/general", { body: general as unknown as GeneratedGeneralSettings })
        .then(unwrap) as SettingsResponse;
      quietRefetch();
      return result;
    },

    async saveFilters(filters: Record<string, FilterConfig>) {
      const result = await apiClient.PUT("/api/settings/filters", { body: filters }).then(unwrap) as SettingsResponse;
      quietRefetch();
      return result;
    },

    async saveEquipment(equipment: EquipmentConfig) {
      const result = await apiClient.PUT("/api/settings/equipment", { body: equipment }).then(unwrap) as SettingsResponse;
      quietRefetch();
      return result;
    },

    async saveDisplay(display: DisplaySettings) {
      await apiClient.PUT("/api/settings/display", { body: display }).then(unwrap);
      quietRefetch();
    },

    getFilterSuggestions: () => apiClient.GET("/api/settings/suggestions/filters", {}).then(unwrap),
    getEquipmentSuggestions: () => apiClient.GET("/api/settings/suggestions/equipment", {}).then(unwrap),
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
