import { Component, For, Show, createMemo, type JSX } from "solid-js";
import { A } from "@solidjs/router";
import { useAuth } from "./AuthProvider";
import HelpPopover from "./HelpPopover";
import type { GuidingRig } from "../api/types";
import { madZ, bandForZ, bandToCellClass, type MetricBaseline } from "../utils/frameQuality";

// Shared table conventions for the Guiding cards (same classes as
// EquipmentPerformance.tsx). Exported so the sibling Guiding* cards stay in step.
export const TH = "text-theme-text-secondary font-normal py-1 px-2 text-tiny uppercase tracking-wide";
export const TH_L = `text-left ${TH}`;
export const TH_R = `text-right ${TH}`;
export const TD = "py-1.5 px-2 tabular-nums";
export const TD_R = `text-right ${TD}`;
export const NULL_GLYPH = "—";

/** Column header with its explanation behind a help glyph. */
export const ColHeader: Component<{ label: string; left?: boolean; children: JSX.Element }> = (props) => (
  <th class={props.left ? TH_L : TH_R}>
    <span class={`inline-flex items-center gap-1 ${props.left ? "" : "justify-end"}`}>
      {props.label}
      <HelpPopover title={props.label} label={`About ${props.label}`} align="right">
        {props.children}
      </HelpPopover>
    </span>
  </th>
);

export function fmtNum(val: number | null | undefined, dp = 2): string {
  if (val === null || val === undefined) return NULL_GLYPH;
  return val.toFixed(dp);
}

// Both destinations are admin-only controls (the Guide Logs card and the PHD2
// profile mapping), so a viewer gets the same sentence without a link.
const HINT_LINK = "text-theme-accent hover:underline";

export const GuidingEmptyNotice: Component<{ unmapped: number }> = (props) => {
  const { isAdmin } = useAuth();
  return (
    <p class="text-sm text-theme-text-secondary">
      <Show
        when={props.unmapped > 0}
        fallback={
          <>
            No PHD2 guide logs catalogued.{" "}
            <Show when={isAdmin()} fallback={<>An admin can enable guide log scanning in Settings, Library, Guide Logs.</>}>
              <A href="/settings?tab=scan#guide-logs" class={HINT_LINK}>Enable guide log scanning</A> in Settings.
            </Show>
          </>
        }
      >
        {props.unmapped} guiding sessions found but no PHD2 profile is mapped to a telescope.{" "}
        <Show when={isAdmin()} fallback={<>An admin can map profiles in Settings, Equipment, PHD2 Profiles.</>}>
          <A href="/settings?tab=equipment#phd2-profiles" class={HINT_LINK}>Map profiles in Settings</A>.
        </Show>
      </Show>
    </p>
  );
};

// Cross-rig baseline: median / MAD of each metric across every rig, same
// construction as EquipmentPerformance.tsx. madZ returns null (neutral) below
// MIN_GROUP rigs, so small installs render uncoloured rather than over-graded.
function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function baselineOf(values: (number | null | undefined)[]): MetricBaseline {
  const present = values.filter((v): v is number => v !== null && v !== undefined);
  const med = median(present);
  const madVal = med === null ? null : median(present.map((v) => Math.abs(v - med)));
  return { median: med, mad: madVal, n: present.length };
}

type Graded = "rms_total_arcsec" | "rms_ra_arcsec" | "rms_dec_arcsec";
const GRADED: Graded[] = ["rms_total_arcsec", "rms_ra_arcsec", "rms_dec_arcsec"];

function buildBaselines(rigs: GuidingRig[]): Record<Graded, MetricBaseline> {
  const out = {} as Record<Graded, MetricBaseline>;
  for (const k of GRADED) out[k] = baselineOf(rigs.map((r) => r[k]));
  return out;
}

// All graded metrics are higher-is-worse.
function cellClass(val: number | null | undefined, base: MetricBaseline): string {
  if (val === null || val === undefined) return "text-theme-text-secondary";
  return bandToCellClass(bandForZ(madZ(val, base)));
}

const GuidingScorecard: Component<{ rigs: GuidingRig[] }> = (props) => {
  const baselines = createMemo(() => buildBaselines(props.rigs));
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Guiding Scorecard</h3>
      <Show
        when={props.rigs.length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No guiding data available</p>}
      >
        <div class="overflow-x-auto">
          <table class="w-full text-xs min-w-[640px]">
            <thead>
              <tr class="border-b border-theme-border">
                <ColHeader label="Rig" left>
                  <p>The telescope mapped to the PHD2 profile. Cameras used under one telescope share a row.</p>
                </ColHeader>
                <ColHeader label="Sessions">
                  <p>Guiding sessions catalogued for the rig. The smaller number are sessions with fewer than 100 guide frames, left out of the RMS figures.</p>
                </ColHeader>
                <ColHeader label="Hours">
                  <p>Total guided time.</p>
                </ColHeader>
                <ColHeader label="RMS Total">
                  <p>Typical guide error in arcseconds across both axes, weighted by frames. Lower is better; compare against your image scale.</p>
                </ColHeader>
                <ColHeader label="RMS RA">
                  <p>Guide error on the right ascension axis, in arcseconds. A high figure points at periodic error or polar alignment drift.</p>
                </ColHeader>
                <ColHeader label="RMS Dec">
                  <p>Guide error on the declination axis, in arcseconds. A high figure points at balance or backlash.</p>
                </ColHeader>
                <ColHeader label="Filtered">
                  <p>RMS after removing short spikes, so gusts and cable snags do not dominate. The gap to RMS Total shows how much of the error is spikes.</p>
                </ColHeader>
                <ColHeader label="Dec:RA">
                  <p>Ratio of Dec error to RA error. Near 1 is balanced; far from 1 says which axis to work on.</p>
                </ColHeader>
                <ColHeader label="Settle s">
                  <p>Median time after a dither before guiding is back within limits. High values cost imaging time; tune settle tolerance or dither size.</p>
                </ColHeader>
              </tr>
            </thead>
            <tbody>
              <For each={props.rigs}>
                {(rig) => (
                  <>
                    <tr class="border-b border-theme-border/20 hover:bg-theme-hover transition-colors duration-150">
                      <td class={`${TD} font-medium text-theme-text-primary whitespace-nowrap`}>{rig.telescope}</td>
                      <td class={`${TD_R} text-theme-text-primary`}>
                        <span>{rig.session_count}</span>
                        <Show when={rig.gated_session_count > 0}>
                          <span class="ml-1 text-tiny text-theme-text-tertiary">{rig.gated_session_count} too short to score</span>
                        </Show>
                      </td>
                      <td class={`${TD_R} text-theme-text-primary`}>{fmtNum(rig.guided_hours, 1)}</td>
                      <td class={`${TD_R} ${cellClass(rig.rms_total_arcsec, baselines().rms_total_arcsec)}`}>{fmtNum(rig.rms_total_arcsec)}</td>
                      <td class={`${TD_R} ${cellClass(rig.rms_ra_arcsec, baselines().rms_ra_arcsec)}`}>{fmtNum(rig.rms_ra_arcsec)}</td>
                      <td class={`${TD_R} ${cellClass(rig.rms_dec_arcsec, baselines().rms_dec_arcsec)}`}>{fmtNum(rig.rms_dec_arcsec)}</td>
                      <td class={`${TD_R} text-theme-text-primary`}>{fmtNum(rig.rms_total_filtered_arcsec)}</td>
                      <td class={`${TD_R} text-theme-text-primary`}>{fmtNum(rig.ra_dec_ratio)}</td>
                      <td class={`${TD_R} text-theme-text-primary`}>{fmtNum(rig.settle_median_s, 1)}</td>
                    </tr>
                    <tr class="border-b border-theme-border">
                      <td colspan="9" class="pb-1.5 px-2 text-tiny text-theme-text-tertiary">
                        Guide exposure: {rig.exposure_ms_values.length > 0 ? `${rig.exposure_ms_values.join(", ")} ms` : NULL_GLYPH}
                      </td>
                    </tr>
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

export default GuidingScorecard;
