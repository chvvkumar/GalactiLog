import { Component, For, Show, createSignal, createEffect } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { debounce } from "../utils/debounce";

// Metric field definitions: key -> { label, step, isInt? }
const METRIC_FIELDS: Record<string, { label: string; step: number; isInt?: boolean }> = {
  fwhm: { label: "FWHM", step: 0.1 },
  eccentricity: { label: "Eccentricity", step: 0.01 },
  stars: { label: "Detected Stars", step: 1, isInt: true },
  guiding_rms: { label: "Guide RMS", step: 0.01 },
  adu_mean: { label: "ADU Mean", step: 1, isInt: true },
  focuser_temp: { label: "Focuser Temp", step: 0.1 },
  ambient_temp: { label: "Ambient Temp", step: 0.1 },
  humidity: { label: "Humidity %", step: 1, isInt: true },
  airmass: { label: "Airmass", step: 0.01 },
};

// Group definitions: group key -> { label, fields (metric keys) }
const GROUPS: { key: string; label: string; fields: string[] }[] = [
  { key: "quality", label: "Quality", fields: ["fwhm", "eccentricity", "stars"] },
  { key: "guiding", label: "Guiding", fields: ["guiding_rms"] },
  { key: "adu", label: "ADU", fields: ["adu_mean"] },
  { key: "focuser", label: "Focuser", fields: ["focuser_temp"] },
  { key: "weather", label: "Weather", fields: ["ambient_temp", "humidity"] },
  { key: "mount", label: "Mount", fields: ["airmass"] },
];

interface MetricRowProps {
  metricKey: string;
  label: string;
  step: number;
  isInt?: boolean;
  initialMin?: number;
  initialMax?: number;
  onChange: (min?: number, max?: number) => void;
}

const MetricRow: Component<MetricRowProps> = (props) => {
  const [minVal, setMinVal] = createSignal<string>(
    props.initialMin != null ? String(props.initialMin) : ""
  );
  const [maxVal, setMaxVal] = createSignal<string>(
    props.initialMax != null ? String(props.initialMax) : ""
  );

  const apply = debounce((min: string, max: string) => {
    const parseFn = props.isInt ? parseInt : parseFloat;
    const minNum = min ? parseFn(min) : undefined;
    const maxNum = max ? parseFn(max) : undefined;
    props.onChange(
      minNum != null && !isNaN(minNum) ? minNum : undefined,
      maxNum != null && !isNaN(maxNum) ? maxNum : undefined
    );
  }, 500);

  return (
    <div class="space-y-1">
      <span class="text-xs text-theme-text-secondary">{props.label}</span>
      <div class="flex gap-2 items-center">
        <input
          type="number"
          step={props.step}
          value={minVal()}
          onInput={(e) => {
            setMinVal(e.currentTarget.value);
            apply(e.currentTarget.value, maxVal());
          }}
          placeholder="Min"
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
        <span class="text-theme-text-secondary text-xs">&ndash;</span>
        <input
          type="number"
          step={props.step}
          value={maxVal()}
          onInput={(e) => {
            setMaxVal(e.currentTarget.value);
            apply(minVal(), e.currentTarget.value);
          }}
          placeholder="Max"
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
      </div>
    </div>
  );
};

const MetricFilters: Component = () => {
  const { filters, updateMetricFilter } = useDashboardFilters();
  const { displaySettings } = useSettingsContext();

  const [groupOpen, setGroupOpen] = createSignal<Record<string, boolean>>({});

  const toggleGroup = (key: string) => {
    setGroupOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const visibleGroups = () => {
    const ds = displaySettings();
    if (!ds) return [];
    return GROUPS.filter((g) => {
      const groupSettings = ds[g.key as keyof typeof ds];
      if (!groupSettings || !groupSettings.enabled) return false;
      // Only include if at least one matching field is enabled
      return g.fields.some((fieldKey) => {
        // Map metric key to display settings field key (stars -> detected_stars, guiding_rms -> guiding_rms_arcsec, etc.)
        const dsFieldKey = metricToDisplayField(fieldKey);
        return groupSettings.fields[dsFieldKey] === true || groupSettings.fields[fieldKey] === true;
      });
    });
  };

  const visibleFields = (group: { key: string; fields: string[] }) => {
    const ds = displaySettings();
    if (!ds) return [];
    const groupSettings = ds[group.key as keyof typeof ds];
    if (!groupSettings) return [];
    return group.fields.filter((fieldKey) => {
      const dsFieldKey = metricToDisplayField(fieldKey);
      return groupSettings.fields[dsFieldKey] === true || groupSettings.fields[fieldKey] === true;
    });
  };

  return (
    <Show when={visibleGroups().length > 0}>
      <div class="space-y-3">
            <For each={visibleGroups()}>
              {(group) => {
                const fields = visibleFields(group);
                if (fields.length === 0) return null;
                return (
                  <div class="space-y-2">
                    {/* Sub-section header */}
                    <button
                      class="w-full flex items-center justify-between text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                      onClick={() => toggleGroup(group.key)}
                    >
                      <span>{group.label}</span>
                      <svg
                        class={`w-3 h-3 transition-transform ${groupOpen()[group.key] ? "rotate-180" : ""}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    <Show when={groupOpen()[group.key]}>
                      <div class="space-y-2 pl-1">
                        <For each={fields}>
                          {(fieldKey) => {
                            const def = METRIC_FIELDS[fieldKey];
                            if (!def) return null;
                            const current = () => filters().metricFilters[fieldKey];
                            return (
                              <MetricRow
                                metricKey={fieldKey}
                                label={def.label}
                                step={def.step}
                                isInt={def.isInt}
                                initialMin={current()?.min}
                                initialMax={current()?.max}
                                onChange={(min, max) =>
                                  updateMetricFilter(fieldKey, { min, max })
                                }
                              />
                            );
                          }}
                        </For>
                      </div>
                    </Show>
                  </div>
                );
              }}
            </For>
      </div>
    </Show>
  );
};

/**
 * Maps metric filter keys to the corresponding key used in DisplaySettings fields.
 * Most are identical; a few differ.
 */
function metricToDisplayField(metricKey: string): string {
  const map: Record<string, string> = {
    stars: "detected_stars",
    guiding_rms: "guiding_rms_arcsec",
  };
  return map[metricKey] ?? metricKey;
}

export default MetricFilters;
