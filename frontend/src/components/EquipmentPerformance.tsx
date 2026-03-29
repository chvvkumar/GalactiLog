import { Component, For, Show, createSignal } from "solid-js";
import type { EquipmentComboMetrics, EquipmentFilterMetrics } from "../types";
import FilterBadges from "./FilterBadges";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

function formatMetric(val: number | null, suffix = ""): string {
  if (val === null || val === undefined) return "\u2014";
  return val.toFixed(2) + suffix;
}

function metricClass(val: number | null): string {
  return val !== null ? "text-theme-text-primary" : "text-theme-text-secondary";
}

const FilterBreakdownRow: Component<{ row: EquipmentFilterMetrics }> = (props) => {
  const dist = () => ({ [props.row.filter_name]: props.row.total_integration_seconds });
  return (
    <tr class="border-b border-theme-border/20">
      <td class="py-1 pl-8 pr-2">
        <FilterBadges distribution={dist()} compact />
      </td>
      <td class="text-right text-theme-text-secondary py-1 px-2 tabular-nums">
        {props.row.frame_count.toLocaleString()}
      </td>
      <td class="text-right text-theme-text-secondary py-1 px-2 tabular-nums">
        {formatHours(props.row.total_integration_seconds)}
      </td>
      <td class={`text-right py-1 px-2 tabular-nums ${metricClass(props.row.median_hfr)}`}>
        {formatMetric(props.row.median_hfr)}
      </td>
      <td class={`text-right py-1 px-2 tabular-nums ${metricClass(props.row.best_hfr)}`}>
        {formatMetric(props.row.best_hfr)}
      </td>
      <td class={`text-right py-1 px-2 tabular-nums ${metricClass(props.row.median_eccentricity)}`}>
        {formatMetric(props.row.median_eccentricity)}
      </td>
      <td class={`text-right py-1 px-2 tabular-nums ${metricClass(props.row.median_fwhm)}`}>
        {formatMetric(props.row.median_fwhm, "\u2033")}
      </td>
    </tr>
  );
};

const ComboRow: Component<{ combo: EquipmentComboMetrics }> = (props) => {
  const [expanded, setExpanded] = createSignal(false);
  const dist = () => {
    const d: Record<string, number> = {};
    for (const f of props.combo.filter_breakdown) {
      d[f.filter_name] = f.total_integration_seconds;
    }
    return d;
  };

  return (
    <>
      <tr
        class="border-b border-theme-border hover:bg-theme-surface-hover cursor-pointer"
        onClick={() => setExpanded(!expanded())}
      >
        <td class="py-1.5 px-2">
          <div class="flex items-center gap-2">
            <span
              class="w-5 h-5 rounded flex items-center justify-center text-xs border flex-shrink-0 transition-colors"
              classList={{
                "border-theme-accent bg-theme-accent/20 text-theme-accent": expanded(),
                "border-theme-border text-theme-text-secondary": !expanded(),
              }}
            >
              {expanded() ? "\u2212" : "+"}
            </span>
            <span class="font-medium text-theme-text-primary">
              {props.combo.telescope} + {props.combo.camera}
            </span>
          </div>
        </td>
        <td class="text-right text-theme-text-secondary py-1.5 px-2 tabular-nums">
          {props.combo.frame_count.toLocaleString()}
        </td>
        <td class="text-right text-theme-text-secondary py-1.5 px-2 tabular-nums">
          {formatHours(props.combo.total_integration_seconds)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.median_hfr)}`}>
          {formatMetric(props.combo.median_hfr)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.best_hfr)}`}>
          {formatMetric(props.combo.best_hfr)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.median_eccentricity)}`}>
          {formatMetric(props.combo.median_eccentricity)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.median_fwhm)}`}>
          {formatMetric(props.combo.median_fwhm, "\u2033")}
        </td>
        <td class="py-1.5 px-2">
          <div class="flex justify-end">
            <FilterBadges distribution={dist()} compact nowrap />
          </div>
        </td>
      </tr>
      <Show when={expanded()}>
        <tr class="bg-theme-surface-alt">
          <td colspan="8" class="p-0">
            <table class="w-full text-xs">
              <thead>
                <tr class="border-b border-theme-border">
                  <th class="text-left text-theme-text-secondary font-normal py-1 pl-8 pr-2 text-[0.65rem] uppercase tracking-wide">Filter</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Frames</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Integration</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med HFR</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Best HFR</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med Ecc</th>
                  <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med FWHM</th>
                </tr>
              </thead>
              <tbody>
                <For each={props.combo.filter_breakdown}>
                  {(row) => <FilterBreakdownRow row={row} />}
                </For>
              </tbody>
            </table>
          </td>
        </tr>
      </Show>
    </>
  );
};

const EquipmentPerformance: Component<{ combos: EquipmentComboMetrics[] }> = (props) => {
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Equipment Performance</h3>
      <Show
        when={props.combos.length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No equipment data available</p>}
      >
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b border-theme-border">
              <th class="text-left text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Equipment</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Frames</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Integration</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med HFR</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Best HFR</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med Ecc</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Med FWHM</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-[0.65rem] uppercase tracking-wide">Filters</th>
            </tr>
          </thead>
          <tbody>
            <For each={props.combos}>
              {(combo) => <ComboRow combo={combo} />}
            </For>
          </tbody>
        </table>
      </Show>
    </div>
  );
};

export default EquipmentPerformance;
