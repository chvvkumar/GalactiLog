import { Component, For, Show, createMemo, createSignal } from "solid-js";
import HelpPopover from "./HelpPopover";
import type { GuidingAltitudeBandRow } from "../api/types";
import { ColHeader, TD, TD_R, fmtNum } from "./GuidingScorecard";

type Band = GuidingAltitudeBandRow["band"];

// Quarter dome, centre at the observer (12,160), radius 140: horizon to the
// right, zenith at the top. Wedge order is horizon first, so the low band sits
// where a low target physically sits.
const WEDGES: { band: Band; label: string; d: string; tx: number; ty: number }[] = [
  {
    band: "<30",
    label: "altitude below 30 degrees",
    d: "M 12 160 L 152 160 A 140 140 0 0 0 133.244 90 Z",
    tx: 108.6,
    ty: 128,
  },
  {
    band: "30-60",
    label: "altitude 30 to 60 degrees",
    d: "M 12 160 L 133.244 90 A 140 140 0 0 0 82 38.756 Z",
    tx: 82.7,
    ty: 83,
  },
  {
    band: ">60",
    label: "altitude above 60 degrees",
    d: "M 12 160 L 82 38.756 A 140 140 0 0 0 12 20 Z",
    tx: 37.9,
    ty: 57,
  },
];

const TIMES = "×";

// Ordinal ramp and card chrome, all keyed off the runtime theme tokens so the
// panel follows every theme rather than pinning its own palette. The ramp is
// the accent at three alpha steps over the card, which keeps text-primary ink
// above 4.5:1 on both light and dark surfaces (the darkest step is only 62%
// of the way to a mid-tone accent).
const CSS = `
.skyarc-root{
  --skyarc-1: color-mix(in oklab, var(--color-accent) 22%, transparent);
  --skyarc-2: color-mix(in oklab, var(--color-accent) 42%, transparent);
  --skyarc-3: color-mix(in oklab, var(--color-accent) 62%, transparent);
  --skyarc-none: color-mix(in oklab, var(--color-text-tertiary) 22%, transparent);
}
.skyarc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;}
.skyarc-card{
  background:var(--color-bg-elevated);
  border:1px solid var(--color-border-default);
  border-radius:var(--radius-sm);
  padding:10px;
  min-width:0;
}
.skyarc-svg{display:block;width:100%;height:auto;}
.skyarc-svg text{pointer-events:none;}
.skyarc-wedge{
  stroke:var(--color-border-emphasis);
  stroke-width:2;
  stroke-linejoin:round;
  transition:filter .12s ease;
}
.skyarc-wedge:hover,.skyarc-wedge:focus-visible{filter:brightness(1.18);}
@media (prefers-reduced-motion: reduce){.skyarc-wedge{transition:none;}}
.skyarc-s1{fill:var(--skyarc-1);}
.skyarc-s2{fill:var(--skyarc-2);}
.skyarc-s3{fill:var(--skyarc-3);}
.skyarc-s0{fill:var(--skyarc-none);}
.skyarc-val{fill:var(--color-text-primary);font-size:12px;font-weight:650;}
.skyarc-sec{fill:var(--color-text-primary);font-size:8.4px;opacity:.8;}
.skyarc-none-lbl{fill:var(--color-text-tertiary);font-size:8.4px;}
.skyarc-lbl{fill:var(--color-text-tertiary);font-size:8.4px;}
.skyarc-lbl-w{fill:var(--color-text-tertiary);font-size:7.6px;letter-spacing:.06em;}
.skyarc-axis{stroke:var(--color-border-emphasis);stroke-width:1;}
.skyarc-sw{display:inline-flex;gap:2px;}
.skyarc-sw i{width:18px;height:10px;border-radius:2px;display:block;}
.skyarc-sw i:nth-child(1){background:var(--skyarc-1);}
.skyarc-sw i:nth-child(2){background:var(--skyarc-2);}
.skyarc-sw i:nth-child(3){background:var(--skyarc-3);}
`;

interface Cell {
  band: Band;
  label: string;
  d: string;
  tx: number;
  ty: number;
  row: GuidingAltitudeBandRow | undefined;
  total: number | null;
  step: 0 | 1 | 2 | 3;
  ratio: number | null;
}

interface Rig {
  telescope: string;
  cells: Cell[];
  sessions: number;
  min: number | null;
  max: number | null;
}

function totalOf(row: GuidingAltitudeBandRow | undefined): number | null {
  return row && row.rms_total_arcsec !== null && row.rms_total_arcsec !== undefined ? row.rms_total_arcsec : null;
}

function buildRigs(rows: GuidingAltitudeBandRow[]): Rig[] {
  const byRig = new Map<string, Map<Band, GuidingAltitudeBandRow>>();
  for (const r of rows) {
    let bands = byRig.get(r.telescope);
    if (!bands) byRig.set(r.telescope, (bands = new Map()));
    bands.set(r.band, r);
  }

  return [...byRig].map(([telescope, bands]) => {
    const present = WEDGES.map((w) => totalOf(bands.get(w.band))).filter((v): v is number => v !== null);
    const sorted = [...present].sort((a, b) => a - b);
    const base = totalOf(bands.get(">60"));

    const cells = WEDGES.map((w) => {
      const row = bands.get(w.band);
      const total = totalOf(row);
      // Rank within the rig, so shade compares bands on the rig's own scale.
      // One band alone gets the middle step rather than a false extreme.
      const i = total === null ? -1 : sorted.indexOf(total);
      const step: Cell["step"] =
        i < 0 ? 0 : sorted.length < 2 ? 2 : ((1 + Math.round((i * 2) / (sorted.length - 1))) as 1 | 2 | 3);
      return { ...w, row, total, step, ratio: total !== null && base ? total / base : null };
    });

    return {
      telescope,
      cells,
      sessions: [...bands.values()].reduce((sum, r) => sum + r.session_count, 0),
      min: sorted.length ? sorted[0] : null,
      max: sorted.length ? sorted[sorted.length - 1] : null,
    };
  });
}

interface Tip {
  rig: string;
  band: string;
  total: string;
  ra: string;
  dec: string;
  sessions: string;
  ratio: string;
  x: number;
  y: number;
}

const GuidingAltitude: Component<{ altitudeBands: GuidingAltitudeBandRow[] }> = (props) => {
  const rigs = createMemo(() => buildRigs(props.altitudeBands));
  const [tip, setTip] = createSignal<Tip | null>(null);
  let rootRef: HTMLDivElement | undefined;

  const show = (rig: Rig, cell: Cell, clientX: number, clientY: number) => {
    if (!cell.row) return;
    const r = rootRef?.getBoundingClientRect();
    const left = r ? Math.min(Math.max(clientX - r.left, 90), Math.max(r.width - 90, 90)) : 0;
    setTip({
      rig: rig.telescope,
      band: cell.label,
      total: fmtNum(cell.total),
      ra: fmtNum(cell.row.rms_ra_arcsec),
      dec: fmtNum(cell.row.rms_dec_arcsec),
      sessions: cell.row.session_count.toLocaleString(),
      ratio: cell.ratio === null ? "—" : `${TIMES}${cell.ratio.toFixed(2)}`,
      x: left,
      y: r ? Math.max(clientY - r.top - 12, 110) : 0,
    });
  };

  return (
    <div
      ref={rootRef}
      class="skyarc-root relative bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4"
      onKeyDown={(e) => {
        if (e.key === "Escape") setTip(null);
      }}
    >
      <style>{CSS}</style>
      <div class="flex items-center gap-2 mb-3">
        <h3 class="text-theme-text-primary font-medium text-sm">RMS by altitude band</h3>
        <HelpPopover title="RMS by altitude band" label="About RMS by altitude band">
          <p class="text-sm text-theme-text-secondary">
            Target altitude at capture. Guiding gets worse near the horizon because of seeing and refraction; use this
            to set a minimum altitude in the sequencer.
          </p>
        </HelpPopover>
      </div>

      <Show
        when={rigs().length > 0}
        fallback={<p class="text-theme-text-secondary text-xs">No data</p>}
      >
        <div class="skyarc-grid">
          <For each={rigs()}>
            {(rig) => (
              <div class="skyarc-card">
                <p class="text-theme-text-primary text-xs font-medium [overflow-wrap:anywhere]">{rig.telescope}</p>
                <p class="text-theme-text-tertiary text-caption tabular-nums mb-1.5">
                  <Show when={rig.min !== null} fallback={<>No RMS recorded</>}>
                    {rig.min === rig.max
                      ? `${fmtNum(rig.min)} arcsec`
                      : `${fmtNum(rig.min)} to ${fmtNum(rig.max)} arcsec`}
                  </Show>
                  {`, ${rig.sessions.toLocaleString()} sessions`}
                </p>
                <svg class="skyarc-svg" viewBox="0 0 190 172" role="img" aria-label={`${rig.telescope} sky arc`}>
                  <For each={rig.cells}>
                    {(cell) => (
                      <path
                        class={`skyarc-wedge skyarc-s${cell.step}`}
                        d={cell.d}
                        tabindex="0"
                        role="img"
                        aria-label={
                          cell.total === null
                            ? `${rig.telescope}, ${cell.label}, no data`
                            : `${rig.telescope}, ${cell.label}, ${fmtNum(cell.total)} arcsec, ${cell.row?.session_count ?? 0} sessions`
                        }
                        onPointerMove={(e) => show(rig, cell, e.clientX, e.clientY)}
                        onPointerLeave={() => setTip(null)}
                        onFocus={(e) => {
                          const b = e.currentTarget.getBoundingClientRect();
                          show(rig, cell, b.left + b.width / 2, b.top + b.height / 2);
                        }}
                        onBlur={() => setTip(null)}
                      />
                    )}
                  </For>

                  <line class="skyarc-axis" x1="12" y1="160" x2="152" y2="160" />

                  <For each={rig.cells}>
                    {(cell) => (
                      <Show
                        when={cell.total !== null}
                        fallback={
                          <text class="skyarc-none-lbl" x={cell.tx} y={cell.ty} text-anchor="middle">
                            no data
                          </text>
                        }
                      >
                        <text class="skyarc-val" x={cell.tx} y={cell.ty} text-anchor="middle">
                          {fmtNum(cell.total)}
                        </text>
                        <Show when={cell.ratio !== null}>
                          <text class="skyarc-sec" x={cell.tx} y={cell.ty + 12} text-anchor="middle">
                            {`${TIMES}${cell.ratio!.toFixed(2)}`}
                          </text>
                        </Show>
                        <text class="skyarc-sec" x={cell.tx} y={cell.ty + 22} text-anchor="middle">
                          {`n ${cell.row?.session_count ?? 0}`}
                        </text>
                      </Show>
                    )}
                  </For>

                  <text class="skyarc-lbl" x="166" y="160" text-anchor="middle" dominant-baseline="middle">0</text>
                  <text class="skyarc-lbl" x="145" y="83.5" text-anchor="middle" dominant-baseline="middle">30</text>
                  <text class="skyarc-lbl" x="88.5" y="27.5" text-anchor="middle" dominant-baseline="middle">60</text>
                  <text class="skyarc-lbl" x="12" y="8" text-anchor="middle" dominant-baseline="middle">90</text>
                  <text class="skyarc-lbl-w" x="152" y="170" text-anchor="end">horizon</text>
                </svg>
              </div>
            )}
          </For>
        </div>

        <div class="flex flex-col gap-1.5 mt-4 pt-3 border-t border-theme-border text-theme-text-secondary text-caption">
          <span class="flex items-center gap-2 flex-wrap">
            <span class="skyarc-sw" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span>Shade runs best band to worst band, each rig on its own scale.</span>
            <HelpPopover title="Shade and ratio" label="About the shade and ratio">
              <p class="text-sm text-theme-text-secondary">
                Shading is ranked inside one rig, lightest for its best band and darkest for its worst, so a rig that
                guides badly stays readable beside a rig that guides well and shade never compares across rigs. The{" "}
                {TIMES} figure is the band RMS divided by the same rig's above-60 RMS, so {TIMES}1.61 means guiding is
                1.61 times worse than that rig's high-altitude figure.
              </p>
            </HelpPopover>
          </span>
          <span class="text-theme-text-tertiary">
            Wedge angle is target altitude at capture: 0 degrees at the horizon on the right, 90 degrees at the zenith
            at the top. Values are RMS total in arcseconds, tick labels are degrees.
          </span>
          <span class="text-theme-text-tertiary">
            {TIMES} is the ratio to that rig's above-60 band. n is the sessions behind the number. Hover or
            keyboard-focus a wedge for the RA and Dec split.
          </span>
        </div>

        <details class="mt-3 text-xs">
          <summary class="cursor-pointer text-theme-text-secondary">Table view</summary>
          <div class="overflow-x-auto">
            <table class="w-full text-xs mt-2">
              <thead>
                <tr class="border-b border-theme-border">
                  <ColHeader label="Rig" left>
                    <p>The telescope mapped to the PHD2 profile. Cameras used under one telescope share a row.</p>
                  </ColHeader>
                  <ColHeader label="Band" left>
                    <p>
                      Target altitude at capture. Guiding gets worse near the horizon because of seeing and refraction;
                      use this to set a minimum altitude in the sequencer.
                    </p>
                  </ColHeader>
                  <ColHeader label="Sessions">
                    <p>Guiding sessions in this altitude band. Bands with few sessions move a lot with one bad night.</p>
                  </ColHeader>
                  <ColHeader label="RMS Total">
                    <p>
                      Typical guide error in arcseconds across both axes, weighted by frames. Lower is better; compare
                      against your image scale.
                    </p>
                  </ColHeader>
                  <ColHeader label="RMS RA">
                    <p>
                      Guide error on the right ascension axis, in arcseconds. A high figure points at periodic error or
                      polar alignment drift.
                    </p>
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
        </details>
      </Show>

      <Show when={tip()}>
        {(t) => (
          <div
            class="absolute z-20 min-w-[160px] -translate-x-1/2 -translate-y-full pointer-events-none bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] shadow-[var(--shadow-md)] p-2 text-caption"
            style={{ left: `${t().x}px`, top: `${t().y}px` }}
            role="status"
            aria-live="polite"
          >
            <b class="block text-theme-text-primary text-label">{t().rig}</b>
            <span class="block text-theme-text-tertiary">{t().band}</span>
            <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 mt-1.5 tabular-nums">
              <dt class="text-theme-text-tertiary">RMS total</dt>
              <dd class="m-0 text-right text-theme-text-primary">{t().total} arcsec</dd>
              <dt class="text-theme-text-tertiary">RMS RA</dt>
              <dd class="m-0 text-right text-theme-text-primary">{t().ra} arcsec</dd>
              <dt class="text-theme-text-tertiary">RMS Dec</dt>
              <dd class="m-0 text-right text-theme-text-primary">{t().dec} arcsec</dd>
              <dt class="text-theme-text-tertiary">Sessions</dt>
              <dd class="m-0 text-right text-theme-text-primary">{t().sessions}</dd>
              <dt class="text-theme-text-tertiary">vs above 60</dt>
              <dd class="m-0 text-right text-theme-text-primary">{t().ratio}</dd>
            </dl>
          </div>
        )}
      </Show>
    </div>
  );
};

export default GuidingAltitude;
