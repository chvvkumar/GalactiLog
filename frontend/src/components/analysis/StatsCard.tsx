import { Component, Show } from "solid-js";
import type { SummaryStats } from "../../types";

interface Props {
  stats: SummaryStats;
  label?: string;
}

const StatsCard: Component<Props> = (props) => {
  const fmt = (v: number) => {
    if (Math.abs(v) >= 1000) return v.toFixed(0);
    if (Math.abs(v) >= 10) return v.toFixed(1);
    return v.toFixed(2);
  };

  return (
    <div class="bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] px-3 py-2">
      <Show when={props.label}>
        <div class="text-xs text-theme-text-tertiary mb-1">{props.label}</div>
      </Show>
      <div class="grid grid-cols-3 sm:grid-cols-6 gap-x-4 gap-y-1 text-sm">
        <div>
          <span class="text-theme-text-tertiary">N: </span>
          <span class="text-theme-text-primary">{props.stats.count}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Min: </span>
          <span class="text-theme-text-primary">{fmt(props.stats.min)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Max: </span>
          <span class="text-theme-text-primary">{fmt(props.stats.max)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Mean: </span>
          <span class="text-theme-text-primary">{fmt(props.stats.mean)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">Median: </span>
          <span class="text-theme-text-primary">{fmt(props.stats.median)}</span>
        </div>
        <div>
          <span class="text-theme-text-tertiary">StDev: </span>
          <span class="text-theme-text-primary">{fmt(props.stats.std_dev)}</span>
        </div>
      </div>
    </div>
  );
};

export default StatsCard;
