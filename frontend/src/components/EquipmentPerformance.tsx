import { Component, For, Show, createMemo, createSignal } from "solid-js";
import type { EquipmentComboMetrics, EquipmentFilterMetrics } from "../types";
import FilterBadges from "./FilterBadges";

import { formatIntegration, ARCSEC } from "../utils/format";
import {
  madZ,
  bandForZ,
  bandToCellClass,
  type MetricBaseline,
} from "../utils/frameQuality";

function formatMetric(val: number | null, suffix = ""): string {
  if (val === null || val === undefined) return "\u2014";
  return val.toFixed(2) + suffix;
}

function metricClass(val: number | null): string {
  return val !== null ? "text-theme-text-primary" : "text-theme-text-secondary";
}

// Catalog-wide reference for the combo-median tables: a MetricBaseline built from
// the combo medians across every combo in the list (median of the combo medians;
// mad = median(|x - median|); n = count of combos with a non-null value).
interface ComboBaselines {
  median_hfr: MetricBaseline;
  median_eccentricity: MetricBaseline;
  median_fwhm: MetricBaseline;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function baselineOf(values: (number | null)[]): MetricBaseline {
  const present = values.filter((v): v is number => v !== null && v !== undefined);
  const med = median(present);
  const madVal = med === null ? null : median(present.map((v) => Math.abs(v - med)));
  return { median: med, mad: madVal, n: present.length };
}

function buildComboBaselines(combos: EquipmentComboMetrics[]): ComboBaselines {
  return {
    median_hfr: baselineOf(combos.map((c) => c.median_hfr)),
    median_eccentricity: baselineOf(combos.map((c) => c.median_eccentricity)),
    median_fwhm: baselineOf(combos.map((c) => c.median_fwhm)),
  };
}

// All three metrics are higher-is-worse. Returns the color class plus a tooltip
// describing the deviation in sigma; falls back to the neutral default class.
function deviationCell(
  val: number | null,
  base: MetricBaseline,
  label: string,
): { class: string; title: string | undefined } {
  if (val === null || val === undefined) {
    return { class: "text-theme-text-secondary", title: undefined };
  }
  const z = madZ(val, base);
  const cls = bandToCellClass(bandForZ(z));
  const title = z === null ? undefined : `${label} ${z.toFixed(1)}\u03c3 vs catalog median`;
  return { class: cls, title };
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
        {formatIntegration(props.row.total_integration_seconds)}
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
        {formatMetric(props.row.median_fwhm, ARCSEC)}
      </td>
    </tr>
  );
};

const ComboRow: Component<{ combo: EquipmentComboMetrics; baselines: ComboBaselines }> = (props) => {
  const [expanded, setExpanded] = createSignal(false);
  const hfrCell = () => deviationCell(props.combo.median_hfr, props.baselines.median_hfr, "HFR");
  const eccCell = () => deviationCell(props.combo.median_eccentricity, props.baselines.median_eccentricity, "Ecc");
  const fwhmCell = () => deviationCell(props.combo.median_fwhm, props.baselines.median_fwhm, "FWHM");
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
        class="border-b border-theme-border hover:bg-theme-hover transition-colors duration-150 cursor-pointer"
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
            <Show when={props.combo.grouped}>
              <span
                class="text-theme-text-secondary text-tiny cursor-help"
                title="Grouped: multiple equipment aliases are combined under this name"
              >
                &#x29C9;
              </span>
            </Show>
          </div>
        </td>
        <td class="text-right text-theme-text-secondary py-1.5 px-2 tabular-nums">
          {props.combo.frame_count.toLocaleString()}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.avg_session_seconds)}`}>
          {props.combo.avg_session_seconds !== null && props.combo.avg_session_seconds !== undefined
            ? formatIntegration(props.combo.avg_session_seconds)
            : "—"}
        </td>
        <td class="text-right text-theme-text-secondary py-1.5 px-2 tabular-nums">
          {formatIntegration(props.combo.total_integration_seconds)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${hfrCell().class}`} title={hfrCell().title}>
          {formatMetric(props.combo.median_hfr)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${metricClass(props.combo.best_hfr)}`}>
          {formatMetric(props.combo.best_hfr)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${eccCell().class}`} title={eccCell().title}>
          {formatMetric(props.combo.median_eccentricity)}
        </td>
        <td class={`text-right py-1.5 px-2 tabular-nums ${fwhmCell().class}`} title={fwhmCell().title}>
          {formatMetric(props.combo.median_fwhm, ARCSEC)}
        </td>
        <td class="py-1.5 px-2">
          <div class="flex justify-end">
            <FilterBadges distribution={dist()} compact nowrap />
          </div>
        </td>
      </tr>
      <tr class={`bg-theme-surface-alt`}>
        <td colspan="9" class="p-0">
          <div class={`grid transition-[grid-template-rows] duration-200 ${expanded() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
            <div class="overflow-hidden">
              <div class="overflow-x-auto">
                <table class="w-full text-xs min-w-[500px]">
                  <thead>
                    <tr class="border-b border-theme-border">
                      <th class="text-left text-theme-text-secondary font-normal py-1 pl-8 pr-2 text-tiny uppercase tracking-wide">Filter</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Frames</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Integration</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med HFR</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Best HFR</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med Ecc</th>
                      <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med FWHM</th>
                    </tr>
                  </thead>
                  <tbody>
                    <For each={props.combo.filter_breakdown}>
                      {(row) => <FilterBreakdownRow row={row} />}
                    </For>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </td>
      </tr>
    </>
  );
};

const EquipmentPerformance: Component<{ combos: EquipmentComboMetrics[] }> = (props) => {
  const baselines = createMemo(() => buildComboBaselines(props.combos));
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Equipment Performance</h3>
      <Show
        when={props.combos.length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No equipment data available</p>}
      >
        <div class="overflow-x-auto">
        <table class="w-full text-xs min-w-[680px]">
          <thead>
            <tr class="border-b border-theme-border">
              <th class="text-left text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Equipment</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Frames</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Avg Session</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Integration</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med HFR</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Best HFR</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med Ecc</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Med FWHM</th>
              <th class="text-right text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide">Filters</th>
            </tr>
          </thead>
          <tbody>
            <For each={props.combos}>
              {(combo) => <ComboRow combo={combo} baselines={baselines()} />}
            </For>
          </tbody>
        </table>
        </div>
      </Show>
    </div>
  );
};

export default EquipmentPerformance;
