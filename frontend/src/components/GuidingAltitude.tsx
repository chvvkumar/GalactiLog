import { Component, For, Show } from "solid-js";
import type { GuidingAltitudeBandRow } from "../api/types";
import { ColHeader, TD, TD_R, fmtNum } from "./GuidingScorecard";

const GuidingAltitude: Component<{ altitudeBands: GuidingAltitudeBandRow[] }> = (props) => (
  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
    <h3 class="text-theme-text-primary font-medium text-sm mb-3">RMS by altitude band</h3>
    <Show
      when={props.altitudeBands.length > 0}
      fallback={<p class="text-theme-text-secondary text-xs">No data</p>}
    >
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="border-b border-theme-border">
              <ColHeader label="Rig" left>
                <p>The telescope mapped to the PHD2 profile. Cameras used under one telescope share a row.</p>
              </ColHeader>
              <ColHeader label="Band" left>
                <p>Target altitude at capture. Guiding gets worse near the horizon because of seeing and refraction; use this to set a minimum altitude in the sequencer.</p>
              </ColHeader>
              <ColHeader label="Sessions">
                <p>Guiding sessions in this altitude band. Bands with few sessions move a lot with one bad night.</p>
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
            </tr>
          </thead>
          <tbody>
            <For each={props.altitudeBands}>
              {(r) => (
                <tr class="border-b border-theme-border/20 text-theme-text-primary">
                  <td class={`${TD} whitespace-nowrap`}>{r.telescope}</td>
                  <td class={TD}>{r.band}</td>
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

export default GuidingAltitude;
