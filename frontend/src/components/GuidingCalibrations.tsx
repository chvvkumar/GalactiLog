import { Component, For, Show, createMemo } from "solid-js";
import type { GuidingCalibration } from "../api/types";
import { TH_L, TH_R, TD, TD_R, NULL_GLYPH, fmtNum } from "./GuidingScorecard";

function orthoClass(v: number | null | undefined): string {
  if (v == null) return "text-theme-text-secondary";
  if (v > 10) return "text-theme-error";
  if (v > 5) return "text-theme-warning";
  return "text-theme-text-primary";
}

// Rows arrive sorted by telescope then started_at desc and already capped at
// 10 per rig server side; consecutive grouping preserves both.
function groupByRig(rows: GuidingCalibration[]): { telescope: string; rows: GuidingCalibration[] }[] {
  const groups: { telescope: string; rows: GuidingCalibration[] }[] = [];
  for (const r of rows) {
    let g = groups[groups.length - 1];
    if (!g || g.telescope !== r.telescope) {
      g = { telescope: r.telescope, rows: [] };
      groups.push(g);
    }
    if (g.rows.length < 10) g.rows.push(r);
  }
  return groups;
}

const GuidingCalibrations: Component<{ calibrations: GuidingCalibration[] }> = (props) => {
  const groups = createMemo(() => groupByRig(props.calibrations));
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Calibrations</h3>
      <Show
        when={groups().length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No calibration data available</p>}
      >
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[760px]">
            <thead>
              <tr class="border-b border-theme-border">
                <th class={TH_L}>Date</th>
                <th class={TH_L}>Profile</th>
                <th class={TH_L}>Completed</th>
                <th class={TH_L}>Pier</th>
                <th class={TH_R}>Dec</th>
                <th class={TH_R}>Ortho err deg</th>
                <th class={TH_R}>RA rate arcsec/s</th>
                <th class={TH_R}>Dec rate arcsec/s</th>
                <th class={TH_R}>RA speed</th>
                <th class={TH_R}>Dec speed</th>
              </tr>
            </thead>
            <tbody>
              <For each={groups()}>
                {(g) => (
                  <>
                    <tr class="border-b border-theme-border bg-theme-surface-alt">
                      <td colspan="10" class={`${TD} font-medium text-theme-text-primary`}>{g.telescope}</td>
                    </tr>
                    <For each={g.rows}>
                      {(c) => (
                        <tr class="border-b border-theme-border/20 text-theme-text-primary hover:bg-theme-hover transition-colors duration-150">
                          <td class={`${TD} whitespace-nowrap`}>{c.started_at.slice(0, 16).replace("T", " ")}</td>
                          <td class={TD}>{c.equipment_profile ?? NULL_GLYPH}</td>
                          <td class={TD}>{c.completed ? "yes" : "no"}</td>
                          <td class={TD}>{c.pier_side ?? NULL_GLYPH}</td>
                          <td class={TD_R}>{fmtNum(c.dec_deg, 1)}</td>
                          <td class={`${TD_R} ${orthoClass(c.ortho_error_deg)}`}>{fmtNum(c.ortho_error_deg, 1)}</td>
                          <td class={TD_R}>{fmtNum(c.west_rate_arcsec_s)}</td>
                          <td class={TD_R}>{fmtNum(c.north_rate_arcsec_s)}</td>
                          <td class={TD_R}>{fmtNum(c.ra_guide_speed)}</td>
                          <td class={TD_R}>{fmtNum(c.dec_guide_speed)}</td>
                        </tr>
                      )}
                    </For>
                  </>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>
    </div>
  );
};

export default GuidingCalibrations;
