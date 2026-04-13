import { Component, For, Show, createSignal } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { debounce } from "../utils/debounce";

// Metric field definitions: key -> { label, step, isInt? }
const METRIC_FIELDS: Record<string, { label: string; step: number; isInt?: boolean }> = {
  hfr: { label: "HFR", step: 0.1 },
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
  { key: "quality", label: "Quality", fields: ["hfr", "fwhm", "eccentricity", "stars"] },
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
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:border-theme-accent outline-none"
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
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:border-theme-accent outline-none"
        />
      </div>
    </div>
  );
};

const MetricFilters: Component = () => {
  const { filters, updateMetricFilter, updateQualityFilters } = useDashboardFilters();
  const { displaySettings } = useSettingsContext();

  const allVisibleFields = () => {
    const ds = displaySettings();
    if (!ds) return [];
    const result: string[] = [];
    for (const group of GROUPS) {
      const groupSettings = ds[group.key as keyof typeof ds];
      if (!groupSettings || !groupSettings.enabled) continue;
      for (const fieldKey of group.fields) {
        const dsFieldKey = metricToDisplayField(fieldKey);
        if (groupSettings.fields[dsFieldKey] === true || groupSettings.fields[fieldKey] === true) {
          result.push(fieldKey);
        }
      }
    }
    return result;
  };

  return (
    <Show when={allVisibleFields().length > 0}>
      <div class="space-y-2">
        <For each={allVisibleFields()}>
          {(fieldKey) => {
            const def = METRIC_FIELDS[fieldKey];
            if (!def) return null;
            if (fieldKey === "hfr") {
              const qf = () => filters().qualityFilters;
              return (
                <MetricRow
                  metricKey={fieldKey}
                  label={def.label}
                  step={def.step}
                  initialMin={qf().hfrMin ?? undefined}
                  initialMax={qf().hfrMax ?? undefined}
                  onChange={(min, max) =>
                    updateQualityFilters({ hfrMin: min, hfrMax: max })
                  }
                />
              );
            }
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
