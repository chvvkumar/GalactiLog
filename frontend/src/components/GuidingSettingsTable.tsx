import { Component, For, Show, createMemo } from "solid-js";
import type { GuidingSettingsRow } from "../api/types";
import { TH_L, TH_R, TD, TD_R, NULL_GLYPH, fmtNum } from "./GuidingScorecard";

interface RigGroup {
  telescope: string;
  rows: GuidingSettingsRow[];
  best: GuidingSettingsRow | null;
}

// Rows arrive sorted by telescope, so consecutive grouping preserves order.
function groupByRig(rows: GuidingSettingsRow[]): RigGroup[] {
  const groups: RigGroup[] = [];
  for (const r of rows) {
    let g = groups[groups.length - 1];
    if (!g || g.telescope !== r.telescope) {
      g = { telescope: r.telescope, rows: [], best: null };
      groups.push(g);
    }
    g.rows.push(r);
    if (r.rms_total_arcsec != null && (g.best === null || r.rms_total_arcsec < (g.best.rms_total_arcsec as number))) {
      g.best = r;
    }
  }
  return groups;
}

function rowClass(row: GuidingSettingsRow, best: GuidingSettingsRow | null): string {
  if (row === best) return "text-theme-success";
  if (row.session_count < 3) return "text-theme-text-tertiary";
  return "text-theme-text-primary";
}

const GuidingSettingsTable: Component<{ settings: GuidingSettingsRow[] }> = (props) => {
  const groups = createMemo(() => groupByRig(props.settings));
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Guide Settings</h3>
      <Show
        when={groups().length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No guide settings data available</p>}
      >
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[640px]">
            <thead>
              <tr class="border-b border-theme-border">
                <th class={TH_L}>Algo RA</th>
                <th class={TH_L}>Algo Dec</th>
                <th class={TH_R}>Exposure ms</th>
                <th class={TH_L}>Dec mode</th>
                <th class={TH_R}>Sessions</th>
                <th class={TH_R}>Hours</th>
                <th class={TH_R}>RMS Total</th>
                <th class={TH_R}>RMS RA</th>
                <th class={TH_R}>RMS Dec</th>
                <th class={TH_R}>Star lost %</th>
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
                      {(row) => (
                        <tr class={`border-b border-theme-border/20 hover:bg-theme-hover transition-colors duration-150 ${rowClass(row, g.best)}`}>
                          <td class={TD}>{row.algo_ra ?? NULL_GLYPH}</td>
                          <td class={TD}>{row.algo_dec ?? NULL_GLYPH}</td>
                          <td class={TD_R}>{row.exposure_ms ?? NULL_GLYPH}</td>
                          <td class={TD}>{row.dec_guide_mode ?? NULL_GLYPH}</td>
                          <td class={TD_R}>{row.session_count}</td>
                          <td class={TD_R}>{fmtNum(row.guided_hours, 1)}</td>
                          <td class={TD_R}>{fmtNum(row.rms_total_arcsec)}</td>
                          <td class={TD_R}>{fmtNum(row.rms_ra_arcsec)}</td>
                          <td class={TD_R}>{fmtNum(row.rms_dec_arcsec)}</td>
                          <td class={TD_R}>{fmtNum(row.star_lost_pct, 1)}</td>
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

export default GuidingSettingsTable;
