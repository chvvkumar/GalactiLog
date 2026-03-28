// frontend/src/components/settings/GeneralTab.tsx
import { createSignal, createEffect, Show, For, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import type { GeneralSettings } from "../../types";
import { FILTER_STYLE_OPTIONS, getFilterBadgeStyle, type FilterBadgeStyle } from "../../utils/filterStyles";

const INTERVALS = [
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 480, label: "8 hours" },
  { value: 720, label: "12 hours" },
  { value: 1440, label: "24 hours" },
];

const PAGE_SIZES = [25, 50, 100];

const PREVIEW_FILTERS: { name: string; color: string }[] = [
  { name: "L", color: "#e0e0e0" },
  { name: "R", color: "#e05050" },
  { name: "G", color: "#50b050" },
  { name: "B", color: "#5070e0" },
  { name: "Sii", color: "#d4a43a" },
  { name: "H", color: "#c44040" },
  { name: "O", color: "#3a8fd4" },
];

export const GeneralTab: Component = () => {
  const { settings, saveGeneral } = useSettingsContext();
  const [local, setLocal] = createSignal<GeneralSettings>({
    auto_scan_enabled: true,
    auto_scan_interval: 240,
    thumbnail_width: 800,
    default_page_size: 50,
    include_calibration: true,
    filter_style: "solid",
    theme: "deep-space",
    text_size: "medium",
  });
  const [saving, setSaving] = createSignal(false);

  createEffect(() => {
    const s = settings();
    if (s) setLocal({ ...s.general });
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveGeneral(local());
      showToast("General settings saved");
    } catch {
      showToast("Failed to save settings", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="space-y-6 max-w-lg">
      {/* Auto-scan toggle */}
      <div class="flex justify-between items-center">
        <label class="text-sm text-theme-text-primary">Auto-scan enabled</label>
        <button
          onClick={() => setLocal((p) => ({ ...p, auto_scan_enabled: !p.auto_scan_enabled }))}
          class={`relative w-10 h-5 rounded-full transition-colors ${
            local().auto_scan_enabled ? "bg-theme-accent" : "bg-theme-text-tertiary"
          }`}
        >
          <span
            class={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
              local().auto_scan_enabled ? "translate-x-5" : ""
            }`}
          />
        </button>
      </div>

      {/* Auto-scan interval */}
      <div class="space-y-1">
        <label class="text-sm text-theme-text-primary">Scan interval</label>
        <select
          value={local().auto_scan_interval}
          onChange={(e) =>
            setLocal((p) => ({ ...p, auto_scan_interval: parseInt(e.currentTarget.value) }))
          }
          class="w-full px-3 py-2 bg-theme-base border border-theme-border rounded text-sm text-theme-text-primary focus:outline-none focus:border-theme-accent"
        >
          {INTERVALS.map((opt) => (
            <option value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Thumbnail width */}
      <div class="space-y-1">
        <label class="text-sm text-theme-text-primary">Thumbnail max width (px)</label>
        <input
          type="number"
          min={200}
          max={2000}
          step={100}
          value={local().thumbnail_width}
          onInput={(e) =>
            setLocal((p) => ({ ...p, thumbnail_width: parseInt(e.currentTarget.value) || 800 }))
          }
          class="w-full px-3 py-2 bg-theme-base border border-theme-border rounded text-sm text-theme-text-primary focus:outline-none focus:border-theme-accent"
        />
      </div>

      {/* Default page size */}
      <div class="space-y-1">
        <label class="text-sm text-theme-text-primary">Default page size</label>
        <select
          value={local().default_page_size}
          onChange={(e) =>
            setLocal((p) => ({ ...p, default_page_size: parseInt(e.currentTarget.value) }))
          }
          class="w-full px-3 py-2 bg-theme-base border border-theme-border rounded text-sm text-theme-text-primary focus:outline-none focus:border-theme-accent"
        >
          {PAGE_SIZES.map((s) => (
            <option value={s}>{s}</option>
          ))}
        </select>
      </div>

      {/* Filter badge style */}
      <div class="space-y-1">
        <label class="text-sm text-theme-text-primary">Filter badge style</label>
        <div class="flex items-center gap-4">
          <select
            value={local().filter_style || "solid"}
            onChange={(e) =>
              setLocal((p) => ({ ...p, filter_style: e.currentTarget.value }))
            }
            class="px-3 py-2 bg-theme-base border border-theme-border rounded text-sm text-theme-text-primary focus:outline-none focus:border-theme-accent"
          >
            <For each={FILTER_STYLE_OPTIONS}>
              {(opt) => <option value={opt.value}>{opt.label}</option>}
            </For>
          </select>
          <div class="flex gap-1.5 items-center">
            <For each={PREVIEW_FILTERS}>
              {(f) => {
                const badgeStyle = () => getFilterBadgeStyle((local().filter_style || "solid") as FilterBadgeStyle, f.color);
                return (
                  <span
                    class="h-6 rounded text-[10px] font-bold flex items-center justify-center gap-0.5 px-1.5"
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

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saving()}
        class="px-4 py-2 bg-theme-accent text-theme-text-primary rounded text-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        {saving() ? "Saving..." : "Save"}
      </button>
    </div>
  );
};
