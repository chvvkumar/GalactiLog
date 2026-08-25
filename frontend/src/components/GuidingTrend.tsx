import { Component, For, Show, createMemo, createSignal } from "solid-js";
import type { GuidingMonthlyRow } from "../api/types";
import { fmtNum } from "./GuidingScorecard";

const GuidingTrend: Component<{ monthly: GuidingMonthlyRow[] }> = (props) => {
  const rigs = createMemo(() => Array.from(new Set(props.monthly.map((m) => m.telescope))));
  const [picked, setPicked] = createSignal<string | null>(null);
  // First rig by default; falls back if the picked rig disappears on refetch.
  const selected = () => {
    const p = picked();
    return p !== null && rigs().includes(p) ? p : rigs()[0];
  };
  const rows = createMemo(() => props.monthly.filter((m) => m.telescope === selected()));
  const maxRms = createMemo(() => Math.max(...rows().map((m) => m.rms_total_arcsec ?? 0), 0));

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex items-center justify-between gap-2 flex-wrap">
        <h3 class="text-theme-text-primary font-medium text-sm">Monthly RMS Trend</h3>
        <Show when={rigs().length > 1}>
          <div class="flex items-center gap-2 flex-wrap">
            <For each={rigs()}>
              {(rig) => (
                <button
                  type="button"
                  class={`px-3 py-1 text-xs rounded ${selected() === rig ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "bg-theme-bg text-theme-text-secondary border border-theme-border hover:bg-theme-hover"}`}
                  onClick={() => setPicked(rig)}
                >
                  {rig}
                </button>
              )}
            </For>
          </div>
        </Show>
      </div>
      <Show when={rows().length > 0} fallback={<p class="text-theme-text-secondary text-xs">No monthly data available</p>}>
        <div class="overflow-x-auto">
          <div class="flex items-end gap-2 min-w-max">
            <For each={rows()}>
              {(m) => (
                <div class="flex flex-col items-center w-14 text-xs tabular-nums">
                  <span class="text-tiny text-theme-text-primary h-4">
                    {m.rms_total_arcsec == null ? "" : fmtNum(m.rms_total_arcsec)}
                  </span>
                  <div class="h-24 w-full flex items-end">
                    <Show when={m.rms_total_arcsec != null}>
                      <div
                        class="w-full rounded-t bg-theme-accent transition-all"
                        style={{ height: `${maxRms() > 0 ? ((m.rms_total_arcsec ?? 0) / maxRms()) * 100 : 0}%` }}
                        title={`${m.month}: ${fmtNum(m.rms_total_arcsec)} arcsec, ${m.session_count} sessions, ${fmtNum(m.guided_hours, 1)} h`}
                      />
                    </Show>
                  </div>
                  <span class="mt-1 text-theme-text-secondary whitespace-nowrap">{m.month}</span>
                  <span class="text-tiny text-theme-text-tertiary">
                    {m.star_lost_pct == null ? "" : `${fmtNum(m.star_lost_pct, 1)}% lost`}
                  </span>
                </div>
              )}
            </For>
          </div>
        </div>
      </Show>
    </div>
  );
};

export default GuidingTrend;
