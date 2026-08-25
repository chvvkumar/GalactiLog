import { Component, For, Show } from "solid-js";
import type { GuidingAltitudeBandRow, GuidingPierSideRow, GuidingStarLostReason } from "../api/types";
import { TH_L, TH_R, TD, TD_R, fmtNum } from "./GuidingScorecard";

interface RmsRow {
  telescope: string;
  session_count: number;
  rms_total_arcsec?: number | null;
  rms_ra_arcsec?: number | null;
  rms_dec_arcsec?: number | null;
}

// Pier side and altitude band tables share every column except the key.
function RmsTable<T extends RmsRow>(props: { title: string; keyLabel: string; rows: T[]; keyOf: (r: T) => string }) {
  return (
    <div class="space-y-2">
      <h4 class="text-xs font-medium text-theme-text-primary">{props.title}</h4>
      <Show when={props.rows.length > 0} fallback={<p class="text-theme-text-secondary text-xs">No data</p>}>
        <div class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead>
              <tr class="border-b border-theme-border">
                <th class={TH_L}>Rig</th>
                <th class={TH_L}>{props.keyLabel}</th>
                <th class={TH_R}>Sessions</th>
                <th class={TH_R}>RMS Total</th>
                <th class={TH_R}>RMS RA</th>
                <th class={TH_R}>RMS Dec</th>
              </tr>
            </thead>
            <tbody>
              <For each={props.rows}>
                {(r) => (
                  <tr class="border-b border-theme-border/20 text-theme-text-primary">
                    <td class={`${TD} whitespace-nowrap`}>{r.telescope}</td>
                    <td class={TD}>{props.keyOf(r)}</td>
                    <td class={TD_R}>{r.session_count}</td>
                    <td class={TD_R}>{fmtNum(r.rms_total_arcsec)}</td>
                    <td class={TD_R}>{fmtNum(r.rms_ra_arcsec)}</td>
                    <td class={TD_R}>{fmtNum(r.rms_dec_arcsec)}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>
    </div>
  );
}

const GuidingPointing: Component<{
  pierSide: GuidingPierSideRow[];
  altitudeBands: GuidingAltitudeBandRow[];
  starLostReasons: GuidingStarLostReason[];
}> = (props) => {
  const reasons = () => [...props.starLostReasons].sort((a, b) => b.count - a.count);
  const maxCount = () => Math.max(...props.starLostReasons.map((r) => r.count), 1);
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Pointing</h3>
      <div class="grid md:grid-cols-3 gap-4">
        <RmsTable title="Pier side" keyLabel="Side" rows={props.pierSide} keyOf={(r) => r.pier_side} />
        <RmsTable title="Altitude band" keyLabel="Band" rows={props.altitudeBands} keyOf={(r) => r.band} />
        <div class="space-y-2">
          <h4 class="text-xs font-medium text-theme-text-primary">Star lost reasons</h4>
          <Show when={reasons().length > 0} fallback={<p class="text-theme-text-secondary text-xs">No data</p>}>
            <For each={reasons()}>
              {(r) => (
                <div class="flex items-center gap-2 text-xs">
                  <span class="w-32 truncate text-theme-text-primary" title={`${r.telescope}: ${r.reason}`}>
                    <span class="text-tiny text-theme-text-tertiary mr-1">{r.telescope}</span>
                    {r.reason}
                  </span>
                  <div class="flex-1 bg-theme-base rounded-full h-4 overflow-hidden">
                    <div class="h-4 rounded-full bg-theme-accent transition-all" style={{ width: `${(r.count / maxCount()) * 100}%` }} />
                  </div>
                  <span class="w-12 text-right text-theme-text-primary tabular-nums">{r.count}</span>
                </div>
              )}
            </For>
          </Show>
        </div>
      </div>
    </div>
  );
};

export default GuidingPointing;
