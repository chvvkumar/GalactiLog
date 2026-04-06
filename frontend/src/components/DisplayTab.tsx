import { createSignal, createEffect, For, Show } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import { useAuth } from "./AuthProvider";
import { showToast } from "./Toast";
import type { DisplaySettings, MetricGroupSettings } from "../types";
import { THEMES_SORTED, TEXT_SIZES, type ThemeMeta } from "../themes";
import { FILTER_STYLE_OPTIONS, getFilterBadgeStyle, type FilterBadgeStyle } from "../utils/filterStyles";
import { timezoneLabel } from "../utils/dateTime";

const PREVIEW_FILTERS: { name: string; color: string }[] = [
  { name: "L", color: "#e0e0e0" },
  { name: "R", color: "#e05050" },
  { name: "G", color: "#50b050" },
  { name: "B", color: "#5070e0" },
  { name: "Sii", color: "#d4a43a" },
  { name: "H", color: "#c44040" },
  { name: "O", color: "#3a8fd4" },
];

const CONTENT_WIDTH_OPTIONS: { value: string; label: string; desc: string }[] = [
  { value: "full", label: "Full", desc: "100%" },
  { value: "ultra-wide", label: "Ultra Wide", desc: "1536px" },
  { value: "wide", label: "Wide", desc: "1280px" },
  { value: "standard", label: "Standard", desc: "1152px" },
  { value: "compact", label: "Compact", desc: "1024px" },
  { value: "narrow", label: "Narrow", desc: "896px" },
];

const TIMEZONE_OPTIONS: { value: string; label: string }[] = [
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "Eastern Time (US)" },
  { value: "America/Chicago", label: "Central Time (US)" },
  { value: "America/Denver", label: "Mountain Time (US)" },
  { value: "America/Los_Angeles", label: "Pacific Time (US)" },
  { value: "America/Anchorage", label: "Alaska" },
  { value: "Pacific/Honolulu", label: "Hawaii" },
  { value: "America/Toronto", label: "Eastern Time (Canada)" },
  { value: "America/Vancouver", label: "Pacific Time (Canada)" },
  { value: "Europe/London", label: "London" },
  { value: "Europe/Paris", label: "Central Europe" },
  { value: "Europe/Helsinki", label: "Eastern Europe" },
  { value: "Asia/Kolkata", label: "India" },
  { value: "Asia/Tokyo", label: "Japan" },
  { value: "Asia/Shanghai", label: "China" },
  { value: "Asia/Dubai", label: "Gulf" },
  { value: "Australia/Sydney", label: "Sydney" },
  { value: "Australia/Perth", label: "Perth" },
  { value: "Pacific/Auckland", label: "New Zealand" },
];

const GROUP_META: { key: keyof DisplaySettings; label: string; fieldLabels: Record<string, string> }[] = [
  { key: "quality", label: "Quality Metrics", fieldLabels: { hfr: "HFR", hfr_stdev: "HFR StDev", fwhm: "FWHM", eccentricity: "Eccentricity", detected_stars: "Detected Stars" } },
  { key: "guiding", label: "Guiding", fieldLabels: { rms_total: "RMS Total", rms_ra: "RMS RA", rms_dec: "RMS Dec" } },
  { key: "adu", label: "ADU Statistics", fieldLabels: { mean: "Mean", median: "Median", stdev: "StDev", min: "Min", max: "Max" } },
  { key: "focuser", label: "Focuser", fieldLabels: { position: "Position", temp: "Temperature" } },
  { key: "weather", label: "Weather", fieldLabels: { ambient_temp: "Temperature", dew_point: "Dew Point", humidity: "Humidity", pressure: "Pressure", wind_speed: "Wind Speed", wind_direction: "Wind Direction", wind_gust: "Wind Gust", cloud_cover: "Cloud Cover", sky_quality: "Sky Quality" } },
  { key: "mount", label: "Mount", fieldLabels: { airmass: "Airmass", pier_side: "Pier Side", rotator_position: "Rotator Position" } },
];

export default function DisplayTab() {
  const { isAdmin } = useAuth();
  const ctx = useSettingsContext();
  const [local, setLocal] = createSignal<DisplaySettings | null>(null);
  const [saving, setSaving] = createSignal(false);
  const [collapsed, setCollapsed] = createSignal<Record<string, boolean>>({});
  const [selectedTheme, setSelectedTheme] = createSignal<string>("default-dark");
  const [selectedTextSize, setSelectedTextSize] = createSignal<string>("medium");
  const [themeSaving, setThemeSaving] = createSignal(false);
  const [filterStyle, setFilterStyle] = createSignal<string>("solid");
  createEffect(() => {
    const style = ctx.settings()?.general.filter_style;
    if (style) setFilterStyle(style);
  });

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

  const [selectedTimezone, setSelectedTimezone] = createSignal<string>("UTC");

  createEffect(() => {
    const tz = ctx.settings()?.general.timezone;
    if (tz) setSelectedTimezone(tz);
  });

  const handleTimezoneChange = async (tz: string) => {
    setSelectedTimezone(tz);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, timezone: tz });
    }
  };

  const [selectedContentWidth, setSelectedContentWidth] = createSignal<string>("full");

  createEffect(() => {
    const w = ctx.settings()?.general.content_width;
    if (w) setSelectedContentWidth(w);
  });

  const handleContentWidthChange = async (width: string) => {
    setSelectedContentWidth(width);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, content_width: width });
    }
  };

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
    try {
      await ctx.saveDisplay(data);
      showToast("Display settings saved");
    } catch {
      showToast("Failed to save display settings", "error");
    } finally {
      setSaving(false);
    }
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

  const handleFilterStyleChange = async (style: string) => {
    setFilterStyle(style);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, filter_style: style });
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
    <div class="space-y-4">
      {/* Theme */}
      <Show when={THEMES_SORTED.length > 1}>
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
          <h3 class="text-theme-text-primary font-medium">Theme</h3>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <For each={THEMES_SORTED}>
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
                    {theme.name.replace(/\s*Glass\s*/i, " ").trim()}
                  </div>
                </button>
              )}
            </For>
          </div>
        </div>
      </Show>

      {/* Appearance */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-4">
        <h3 class="text-theme-text-primary font-medium">Appearance</h3>

        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Text Size</span>
          <div class="flex gap-2">
            <For each={TEXT_SIZES}>
              {(size) => (
                <button
                  type="button"
                  class={`px-3 py-1.5 rounded-[var(--radius-sm)] text-sm transition-colors duration-150 border ${
                    selectedTextSize() === size.id
                      ? "border-theme-accent bg-theme-accent text-white"
                      : "border-theme-border text-theme-text-secondary hover:border-theme-border-em"
                  }`}
                  onClick={() => handleTextSizeChange(size.id)}
                >
                  {size.label}
                </button>
              )}
            </For>
          </div>
        </div>

        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Filter Badge Style</span>
          <div class="flex items-center gap-3">
            <select
              value={filterStyle()}
              onChange={(e) => handleFilterStyleChange(e.currentTarget.value)}
              class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
            >
              <For each={FILTER_STYLE_OPTIONS}>
                {(opt) => <option value={opt.value}>{opt.label}</option>}
              </For>
            </select>
            <div class="flex gap-1.5 items-center">
              <For each={PREVIEW_FILTERS}>
                {(f) => {
                  const badgeStyle = () => getFilterBadgeStyle(filterStyle() as FilterBadgeStyle, f.color);
                  return (
                    <span
                      class="h-6 rounded text-caption font-bold flex items-center justify-center gap-0.5 px-1.5"
                      style={badgeStyle().style}
                    >
                      <Show when={badgeStyle().dot}>
                        <span class="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ "background-color": badgeStyle().dot }} />
                      </Show>
                      {f.name}
                    </span>
                  );
                }}
              </For>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Timezone</span>
          <div class="flex items-center gap-2">
            <select
              value={selectedTimezone()}
              onChange={(e) => handleTimezoneChange(e.currentTarget.value)}
              class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
            >
              <For each={TIMEZONE_OPTIONS}>
                {(opt) => <option value={opt.value}>{opt.label}</option>}
              </For>
            </select>
            <span class="text-xs text-theme-text-tertiary">{timezoneLabel(selectedTimezone())}</span>
          </div>
        </div>

        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Content Width</span>
          <div class="flex gap-1">
            <For each={CONTENT_WIDTH_OPTIONS}>
              {(opt) => (
                <button
                  type="button"
                  class={`px-2.5 py-1.5 rounded-[var(--radius-sm)] text-xs transition-colors duration-150 border ${
                    selectedContentWidth() === opt.value
                      ? "border-theme-accent bg-theme-accent text-white"
                      : "border-theme-border text-theme-text-secondary hover:border-theme-border-em"
                  }`}
                  onClick={() => handleContentWidthChange(opt.value)}
                  title={opt.desc}
                >
                  {opt.label}
                </button>
              )}
            </For>
          </div>
        </div>

      </div>

      {/* Metric Visibility */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">Metric Visibility</h3>
        <p class="text-sm text-theme-text-secondary">Choose which metric groups and individual fields appear on target detail pages.</p>
        <Show when={local()} fallback={<p class="text-theme-text-secondary text-sm">Loading...</p>}>
          {(settings) => (
            <div class="space-y-2">
              <For each={GROUP_META}>
                {(group) => {
                  const gs = (): MetricGroupSettings => settings()[group.key];
                  const isCollapsed = () => !!collapsed()[group.key];
                  return (
                    <div class="rounded-[var(--radius-md)] bg-theme-base/50 border border-theme-border">
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
            </div>
          )}
        </Show>
      </div>

      <Show when={local() && isAdmin()}>
        <div class="flex justify-end">
          <button type="button" class="px-3 py-1.5 text-sm rounded-[var(--radius-sm)] bg-theme-accent text-white disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity" disabled={saving()} onClick={handleSave}>
            {saving() ? "Saving..." : "Save"}
          </button>
        </div>
      </Show>
    </div>
  );
}
