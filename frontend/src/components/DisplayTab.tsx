import { createSignal, createEffect, For, Show } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import type { DisplaySettings, MetricGroupSettings } from "../types";
import { THEMES, TEXT_SIZES, type ThemeMeta } from "../themes";

const GROUP_META: { key: keyof DisplaySettings; label: string; fieldLabels: Record<string, string> }[] = [
  { key: "quality", label: "Quality Metrics", fieldLabels: { hfr: "HFR", hfr_stdev: "HFR StDev", fwhm: "FWHM", eccentricity: "Eccentricity", detected_stars: "Detected Stars" } },
  { key: "guiding", label: "Guiding", fieldLabels: { rms_total: "RMS Total", rms_ra: "RMS RA", rms_dec: "RMS Dec" } },
  { key: "adu", label: "ADU Statistics", fieldLabels: { mean: "Mean", median: "Median", stdev: "StDev", min: "Min", max: "Max" } },
  { key: "focuser", label: "Focuser", fieldLabels: { position: "Position", temp: "Temperature" } },
  { key: "weather", label: "Weather", fieldLabels: { ambient_temp: "Temperature", dew_point: "Dew Point", humidity: "Humidity", pressure: "Pressure", wind_speed: "Wind Speed", wind_direction: "Wind Direction", wind_gust: "Wind Gust", cloud_cover: "Cloud Cover", sky_quality: "Sky Quality" } },
  { key: "mount", label: "Mount", fieldLabels: { airmass: "Airmass", pier_side: "Pier Side", rotator_position: "Rotator Position" } },
];

export default function DisplayTab() {
  const ctx = useSettingsContext();
  const [local, setLocal] = createSignal<DisplaySettings | null>(null);
  const [saving, setSaving] = createSignal(false);
  const [collapsed, setCollapsed] = createSignal<Record<string, boolean>>({});
  const [selectedTheme, setSelectedTheme] = createSignal<string>("default-dark");
  const [selectedTextSize, setSelectedTextSize] = createSignal<string>("medium");
  const [themeSaving, setThemeSaving] = createSignal(false);

  createEffect(() => {
    const ds = ctx.settings()?.display;
    if (ds && !local()) setLocal(structuredClone(ds));
  });

  createEffect(() => {
    const theme = ctx.settings()?.general.theme;
    if (theme) setSelectedTheme(theme);
  });

  createEffect(() => {
    const size = ctx.settings()?.general.text_size;
    if (size) setSelectedTextSize(size);
  });

  const toggleCollapsed = (key: string) => setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));

  const toggleGroupEnabled = (key: keyof DisplaySettings) => {
    setLocal((prev) => {
      if (!prev) return prev;
      const clone = structuredClone(prev);
      clone[key].enabled = !clone[key].enabled;
      return clone;
    });
  };

  const toggleField = (groupKey: keyof DisplaySettings, fieldKey: string) => {
    setLocal((prev) => {
      if (!prev) return prev;
      const clone = structuredClone(prev);
      clone[groupKey].fields[fieldKey] = !clone[groupKey].fields[fieldKey];
      return clone;
    });
  };

  const handleSave = async () => {
    const data = local();
    if (!data) return;
    setSaving(true);
    try { await ctx.saveDisplay(data); } finally { setSaving(false); }
  };

  const handleThemeChange = async (themeId: string) => {
    setSelectedTheme(themeId);
    setThemeSaving(true);
    try {
      const current = ctx.settings()?.general;
      if (current) {
        await ctx.saveGeneral({ ...current, theme: themeId });
      }
    } finally {
      setThemeSaving(false);
    }
  };

  const handleTextSizeChange = async (sizeId: string) => {
    setSelectedTextSize(sizeId);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, text_size: sizeId });
    }
  };

  return (
    <div class="space-y-6">
      {/* Theme Chooser */}
      <Show when={THEMES.length > 1}>
        <div class="space-y-3">
          <h3 class="text-sm font-medium text-theme-text-primary">Theme</h3>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <For each={THEMES}>
              {(theme: ThemeMeta) => (
                <button
                  type="button"
                  class={`rounded-[var(--radius-md)] p-3 text-left border-2 transition-colors ${
                    selectedTheme() === theme.id
                      ? "border-theme-accent"
                      : "border-theme-border hover:border-theme-border-em"
                  }`}
                  style={{ "background-color": theme.tokens["bg-surface"] }}
                  onClick={() => handleThemeChange(theme.id)}
                  disabled={themeSaving()}
                >
                  <div class="flex gap-1 mb-2">
                    <span class="w-4 h-4 rounded-full" style={{ "background-color": theme.tokens["accent"] }} />
                    <span class="w-4 h-4 rounded-full" style={{ "background-color": theme.tokens["success"] }} />
                    <span class="w-4 h-4 rounded-full" style={{ "background-color": theme.tokens["warning"] }} />
                    <span class="w-4 h-4 rounded-full" style={{ "background-color": theme.tokens["error"] }} />
                  </div>
                  <div class="text-xs font-medium" style={{ color: theme.tokens["text-primary"] }}>
                    {theme.name}
                  </div>
                  <div class="text-[10px] mt-0.5" style={{ color: theme.tokens["text-secondary"] }}>
                    {theme.description}
                  </div>
                </button>
              )}
            </For>
          </div>
        </div>
      </Show>

      {/* Text Size */}
      <div class="space-y-3">
        <h3 class="text-sm font-medium text-theme-text-primary">Text Size</h3>
        <div class="flex gap-2">
          <For each={TEXT_SIZES}>
            {(size) => (
              <button
                type="button"
                class={`px-4 py-2 rounded-[var(--radius-sm)] text-sm transition-colors duration-150 border ${
                  selectedTextSize() === size.id
                    ? "border-theme-accent bg-theme-accent text-white"
                    : "border-theme-border bg-theme-surface text-theme-text-secondary hover:border-theme-border-em"
                }`}
                onClick={() => handleTextSizeChange(size.id)}
              >
                {size.label}
              </button>
            )}
          </For>
        </div>
      </div>

      {/* Divider */}
      <hr class="border-theme-border" />

      {/* Metric visibility */}
      <div class="space-y-4">
        <p class="text-sm text-theme-text-secondary">Choose which metric groups and individual fields appear on target detail pages.</p>
        <Show when={local()} fallback={<p class="text-theme-text-secondary">Loading...</p>}>
          {(settings) => (
            <>
              <For each={GROUP_META}>
                {(group) => {
                  const gs = (): MetricGroupSettings => settings()[group.key];
                  const isCollapsed = () => !!collapsed()[group.key];
                  return (
                    <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border">
                      <div class="flex items-center justify-between px-4 py-3">
                        <button type="button" class="flex items-center gap-2 text-sm font-medium text-theme-text-primary hover:text-theme-text-secondary" onClick={() => toggleCollapsed(group.key)}>
                          <svg class={`w-4 h-4 transition-transform ${isCollapsed() ? "-rotate-90" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
                          {group.label}
                        </button>
                        <button type="button" role="switch" aria-checked={gs().enabled} class={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${gs().enabled ? "bg-theme-accent" : "bg-theme-text-tertiary"}`} onClick={() => toggleGroupEnabled(group.key)}>
                          <span class={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${gs().enabled ? "translate-x-4" : "translate-x-0"}`} />
                        </button>
                      </div>
                      <Show when={!isCollapsed()}>
                        <div class={`px-4 pb-3 grid grid-cols-2 sm:grid-cols-3 gap-2 ${!gs().enabled ? "opacity-40" : ""}`}>
                          <For each={Object.entries(group.fieldLabels)}>
                            {([fieldKey, fieldLabel]) => (
                              <label class="flex items-center gap-2 text-sm text-theme-text-primary cursor-pointer">
                                <input type="checkbox" checked={gs().fields[fieldKey] ?? false} disabled={!gs().enabled} onChange={() => toggleField(group.key, fieldKey)} class="rounded border-theme-border bg-theme-base text-theme-accent focus:ring-theme-accent focus:ring-offset-0 h-4 w-4" />
                                {fieldLabel}
                              </label>
                            )}
                          </For>
                        </div>
                      </Show>
                    </div>
                  );
                }}
              </For>
              <div class="flex justify-end pt-2">
                <button type="button" class="px-3 py-1.5 text-sm font-medium rounded-[var(--radius-sm)] bg-theme-accent hover:bg-theme-accent-hover text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors duration-150" disabled={saving()} onClick={handleSave}>
                  {saving() ? "Saving..." : "Save"}
                </button>
              </div>
            </>
          )}
        </Show>
      </div>
    </div>
  );
}
