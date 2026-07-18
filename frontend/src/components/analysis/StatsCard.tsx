import { Component, Show } from "solid-js";
import type { SummaryStats } from "../../api/types";

interface Props {
  stats: SummaryStats;
  label?: string;
  // Unit suffix appended to every numeric value ("px", the arcsec glyph, "°C").
  unit?: string;
}

const StatsCard: Component<Props> = (props) => {
  const fmt = (v: number) => {
    const num =
      Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
    return props.unit ? `${num}${props.unit}` : num;
  };

  return (
    <div class="bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] px-3 py-2">
      <Show when={props.label}>
        <div class="text-xs text-theme-text-tertiary mb-1">{props.label}</div>
      </Show>
      <div class="grid grid-cols-3 sm:grid-cols-6 gap-x-4 gap-y-1 text-sm">
        <div>
          <span class="text-theme-text-tertiary">N: </span>
          <span class="text-theme-text-primary tabular-nums">{props.stats.count}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Min: </span>
          <span class="text-theme-text-primary tabular-nums">{fmt(props.stats.min)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Max: </span>
          <span class="text-theme-text-primary tabular-nums">{fmt(props.stats.max)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Mean: </span>
          <span class="text-theme-text-primary tabular-nums">{fmt(props.stats.mean)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Median: </span>
          <span class="text-theme-text-primary tabular-nums">{fmt(props.stats.median)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">StDev: </span>
          <span class="text-theme-text-primary tabular-nums">{fmt(props.stats.std_dev)}</span>
        </div>
      </div>
    </div>
  );
};

export default StatsCard;
