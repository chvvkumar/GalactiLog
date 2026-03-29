// frontend/src/components/settings/GeneralTab.tsx
import { createSignal, createEffect, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import type { GeneralSettings } from "../../types";
const INTERVALS = [
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 480, label: "8 hours" },
  { value: 720, label: "12 hours" },
  { value: 1440, label: "24 hours" },
];

const PAGE_SIZES = [25, 50, 100];

export const GeneralTab: Component = () => {
  const { settings, saveGeneral } = useSettingsContext();
  const [local, setLocal] = createSignal<GeneralSettings>({
    auto_scan_enabled: true,
    auto_scan_interval: 240,
    thumbnail_width: 800,
    default_page_size: 50,
    include_calibration: true,
    filter_style: "solid",
    theme: "default-dark",
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
          class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
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
          class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
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
          class="w-full px-3 py-2 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        >
          {PAGE_SIZES.map((s) => (
            <option value={s}>{s}</option>
          ))}
        </select>
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
