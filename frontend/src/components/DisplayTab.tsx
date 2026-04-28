import { createSignal, createEffect, For, Show } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import { useAuth } from "./AuthProvider";
import { showToast } from "./Toast";
import HelpPopover from "./HelpPopover";
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
  { value: "wide", label: "Wide", desc: "1792px" },
  { value: "standard", label: "Standard", desc: "1536px" },
  { value: "compact", label: "Compact", desc: "1280px" },
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

  const [use24h, setUse24h] = createSignal(false);

  createEffect(() => {
    const v = ctx.settings()?.general.use_24h_time;
    if (v !== undefined) setUse24h(v);
  });

  const [useImagingNight, setUseImagingNight] = createSignal(false);

  createEffect(() => {
    const v = ctx.settings()?.general.use_imaging_night;
    if (v !== undefined) setUseImagingNight(v);
  });

  const handleTimezoneChange = async (tz: string) => {
    setSelectedTimezone(tz);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, timezone: tz });
    }
  };

  const handle24hChange = async (enabled: boolean) => {
    setUse24h(enabled);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, use_24h_time: enabled });
    }
  };

  const handleImagingNightChange = async (enabled: boolean) => {
    setUseImagingNight(enabled);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, use_imaging_night: enabled });
      showToast(
        enabled
          ? "Imaging night grouping enabled. Sessions are being recomputed..."
          : "Imaging night grouping disabled. Sessions are being recomputed...",
        "info"
      );
    }
  };

  const [defaultChartSessions, setDefaultChartSessions] = createSignal<number>(1);

  createEffect(() => {
    const v = ctx.graphSettings().default_chart_sessions;
    if (v !== undefined) setDefaultChartSessions(v);
  });

  const handleDefaultChartSessionsChange = async (value: number) => {
    const prev = defaultChartSessions();
    setDefaultChartSessions(value);
    try {
      await ctx.saveGraphSettings({ default_chart_sessions: value });
    } catch {
      setDefaultChartSessions(prev);
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

  const [previewResolution, setPreviewResolution] = createSignal<number>(2400);
  const [previewCacheMb, setPreviewCacheMb] = createSignal<number>(2048);

  createEffect(() => {
    const r = ctx.settings()?.general.preview_resolution;
    if (r !== undefined) setPreviewResolution(r);
  });

  createEffect(() => {
    const c = ctx.settings()?.general.preview_cache_mb;
    if (c !== undefined) setPreviewCacheMb(c);
  });

  const handlePreviewResolutionChange = async (value: number) => {
    setPreviewResolution(value);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, preview_resolution: value });
    }
  };

  const handlePreviewCacheMbChange = async (value: number) => {
    setPreviewCacheMb(value);
    const current = ctx.settings()?.general;
    if (current) {
      await ctx.saveGeneral({ ...current, preview_cache_mb: value });
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
    <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
      <Show when={THEMES_SORTED.length > 1}>
        <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold text-theme-text-primary">Theme</h2>
            <HelpPopover title="Theme">
              <p>Color palette used across every page. Themes include light and dark variants, each with distinct accent and surface colors.</p>
              <p>Example: pick a dark theme for night-time sessions at the scope and a light theme for planning during the day.</p>
            </HelpPopover>
          </div>
          <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
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

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Text Size</h2>
          <HelpPopover title="Text Size">
            <p>Scales the base font size used across the interface. All text, table cells, and chart labels scale together.</p>
            <p>Example: choose Large on a 4K monitor viewed from a distance, or Small to fit more rows in dashboard tables.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Size</span>
          <div class="flex gap-2">
            <For each={TEXT_SIZES}>
              {(size) => (
                <button
                  type="button"
                  class={`px-3 py-1.5 rounded-[var(--radius-sm)] text-sm transition-colors duration-150 border ${
                    selectedTextSize() === size.id
                      ? "border-theme-border-em bg-theme-elevated text-theme-text-primary font-medium"
                      : "border-theme-border text-theme-text-secondary hover:border-theme-border-em hover:bg-theme-hover"
                  }`}
                  onClick={() => handleTextSizeChange(size.id)}
                >
                  {size.label}
                </button>
              )}
            </For>
          </div>
        </div>
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Filter Badge Style</h2>
          <HelpPopover title="Filter Badge Style">
            <p>Controls how filter names render in session tables, dashboard rows, and charts.</p>
            <p>Example: a solid pill fills the badge with the filter color, while the dot style keeps text neutral and uses a small colored dot next to the name.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Style</span>
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
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Timezone</h2>
          <HelpPopover title="Timezone">
            <p>Timezone used to format session dates, capture timestamps, and date-range labels in the UI. The underlying FITS timestamps remain in UTC; only the display changes.</p>
            <p>Example: setting America/Denver shows a frame captured at 03:12 UTC as 21:12 the previous evening.</p>
            <p>The 24-hour clock toggle switches between 14:30 and 2:30 PM formatting. Imaging night grouping keeps sessions that cross midnight as a single night, using FITS-header coordinates or the observer location as a fallback.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Zone</span>
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
          <span class="text-sm text-theme-text-secondary">24-hour clock</span>
          <button
            type="button"
            role="switch"
            aria-checked={use24h()}
            class={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${use24h() ? "bg-theme-accent" : "bg-theme-text-tertiary"}`}
            onClick={() => handle24hChange(!use24h())}
          >
            <span class={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${use24h() ? "translate-x-4" : "translate-x-0"}`} />
          </button>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-theme-text-secondary">Imaging night grouping</span>
            <p class="text-xs text-theme-text-tertiary mt-0.5">
              Keep a full night of imaging together as one session, even when
              it crosses midnight. Uses your location from FITS headers to
              determine the boundary.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={useImagingNight()}
            class={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${useImagingNight() ? "bg-theme-accent" : "bg-theme-text-tertiary"}`}
            onClick={() => handleImagingNightChange(!useImagingNight())}
          >
            <span class={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${useImagingNight() ? "translate-x-4" : "translate-x-0"}`} />
          </button>
        </div>
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Target Chart</h2>
          <HelpPopover title="Target Chart">
            <p>Controls the default number of sessions pre-selected in the metrics chart when opening a target detail page. You can always select or deselect individual sessions manually.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Default sessions</span>
          <select
            value={defaultChartSessions()}
            onChange={(e) => handleDefaultChartSessionsChange(Number(e.currentTarget.value))}
            class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
          >
            <option value={1}>Latest session</option>
            <option value={3}>Latest 3 sessions</option>
            <option value={5}>Latest 5 sessions</option>
            <option value={10}>Latest 10 sessions</option>
            <option value={0}>All sessions</option>
          </select>
        </div>
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Content Width</h2>
          <HelpPopover title="Content Width">
            <p>Maximum width of the main content area. Narrower widths keep line lengths readable on large monitors; wider settings show more columns in dashboard tables.</p>
            <p>Example: on an ultrawide 3440px monitor, Wide caps content at 1280px, leaving blank margins, while Full uses the whole viewport.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-sm text-theme-text-secondary">Width</span>
          <div class="flex gap-1">
            <For each={CONTENT_WIDTH_OPTIONS}>
              {(opt) => (
                <button
                  type="button"
                  class={`px-2.5 py-1.5 rounded-[var(--radius-sm)] text-xs transition-colors duration-150 border ${
                    selectedContentWidth() === opt.value
                      ? "border-theme-border-em bg-theme-elevated text-theme-text-primary font-medium"
                      : "border-theme-border text-theme-text-secondary hover:border-theme-border-em hover:bg-theme-hover"
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

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">File Preview</h2>
          <HelpPopover title="File Preview">
            <p>These settings configure on-demand high-resolution preview rendering.</p>
            <p>To open a preview, click a file name in a session's image table on a target detail page, or click a thumbnail in the mosaic panel grid. Clicking opens a modal showing the existing thumbnail with a Zoom button that renders the higher-resolution preview on demand.</p>
          </HelpPopover>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-theme-text-secondary">Preview resolution</span>
            <p class="text-xs text-theme-text-tertiary mt-0.5">How large the zoomed-in preview image is. Native means it matches the camera's full resolution.</p>
          </div>
          <select
            value={previewResolution()}
            onChange={(e) => handlePreviewResolutionChange(Number(e.currentTarget.value))}
            class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
          >
            <option value={1600}>1600 px</option>
            <option value={2400}>2400 px</option>
            <option value={4000}>4000 px</option>
            <option value={0}>Native</option>
          </select>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <span class="text-sm text-theme-text-secondary">Preview cache size (MB)</span>
            <p class="text-xs text-theme-text-tertiary mt-0.5">How much disk space to use for cached previews. When this limit is reached, the oldest previews are removed to make room for new ones.</p>
          </div>
          <input
            type="number"
            value={previewCacheMb()}
            min={100}
            max={51200}
            onBlur={(e) => {
              const raw = e.currentTarget.value.trim();
              const parsed = Number(raw);
              if (!raw || Number.isNaN(parsed)) {
                e.currentTarget.value = String(previewCacheMb());
                return;
              }
              const v = Math.min(51200, Math.max(100, parsed));
              handlePreviewCacheMbChange(v);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const raw = e.currentTarget.value.trim();
                const parsed = Number(raw);
                if (!raw || Number.isNaN(parsed)) {
                  e.currentTarget.value = String(previewCacheMb());
                  return;
                }
                const v = Math.min(51200, Math.max(100, parsed));
                handlePreviewCacheMbChange(v);
              }
            }}
            class="w-28 px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none text-right"
          />
        </div>
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Metric Visibility</h2>
          <HelpPopover title="Metric Visibility">
            <p>Controls which metric groups and individual fields appear on target detail pages. Disable an entire group with the group toggle, or hide individual fields with the checkboxes.</p>
            <p>Example: hide Eccentricity under Quality Metrics if you do not track star shape, or disable the Weather group if your capture software does not log it.</p>
          </HelpPopover>
        </div>
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
                      <div class={`grid transition-[grid-template-rows] duration-200 ${isCollapsed() ? "grid-rows-[0fr]" : "grid-rows-[1fr]"}`}>
                        <div class="overflow-hidden">
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
                        </div>
                      </div>
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
          <button type="button" class="px-3 py-1.5 text-sm rounded-[var(--radius-sm)] bg-theme-accent/15 text-theme-accent border border-theme-accent/30 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-theme-accent/25 transition-colors font-medium" disabled={saving()} onClick={handleSave}>
            {saving() ? "Saving..." : "Save"}
          </button>
        </div>
      </Show>
    </div>
  );
}
