import { Component, For, Show, createMemo, createSignal } from "solid-js";
import { api } from "../../api/client";
import type { PanelStats } from "../../types";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

function completionPct(seconds: number, max: number): number {
  return max > 0 ? (seconds / max) * 100 : 0;
}

function completionColor(pct: number): string {
  if (pct >= 80) return "#26a641";
  if (pct >= 40) return "#d29922";
  return "#f85149";
}

function completionOpacity(pct: number): number {
  // 30% minimum opacity so even empty panels are visible
  return 0.3 + 0.7 * Math.min(pct / 100, 1);
}

interface Position {
  panel: PanelStats;
  x: number;
  y: number;
  w: number;
  h: number;
  pct: number;
}

interface Props {
  panels: PanelStats[];
}

const MosaicGrid: Component<Props> = (props) => {
  const [tooltip, setTooltip] = createSignal<{ x: number; y: number; panel: PanelStats } | null>(null);

  const layout = createMemo((): { positions: Position[]; svgW: number; svgH: number } => {
    const panels = props.panels;
    if (panels.length === 0) return { positions: [], svgW: 0, svgH: 0 };

    const maxInt = Math.max(...panels.map((p) => p.total_integration_seconds), 1);

    const withCoords = panels.filter((p) => p.ra != null && p.dec != null);
    const withoutCoords = panels.filter((p) => p.ra == null || p.dec == null);

    const ras = withCoords.map((p) => p.ra!);
    const decs = withCoords.map((p) => p.dec!);
    const raSpan = withCoords.length >= 2 ? Math.max(...ras) - Math.min(...ras) : 0;
    const decSpan = withCoords.length >= 2 ? Math.max(...decs) - Math.min(...decs) : 0;
    const hasSpatial = raSpan > 0.01 || decSpan > 0.01;

    // --- Fallback: numbered grid when no spatial data ---
    if (!hasSpatial) {
      const CELL = 120;
      const GAP = 6;
      const sorted = [...panels].sort((a, b) => {
        const na = parseInt(a.panel_label.replace(/\D/g, "")) || a.sort_order;
        const nb = parseInt(b.panel_label.replace(/\D/g, "")) || b.sort_order;
        return na - nb;
      });
      const cols = Math.ceil(Math.sqrt(sorted.length));
      const rows = Math.ceil(sorted.length / cols);
      return {
        positions: sorted.map((p, i) => ({
          panel: p,
          x: (i % cols) * (CELL + GAP),
          y: Math.floor(i / cols) * (CELL + GAP),
          w: CELL,
          h: CELL,
          pct: completionPct(p.total_integration_seconds, maxInt),
        })),
        svgW: cols * (CELL + GAP) - GAP,
        svgH: rows * (CELL + GAP) - GAP,
      };
    }

    // --- Spatial layout from real RA/Dec ---
    // Estimate cell size from the median nearest-neighbour distance.
    // This approximates the camera FOV that the user imaged with.
    const coords = withCoords.map((p) => ({ ra: p.ra!, dec: p.dec! }));
    const distances: number[] = [];
    for (let i = 0; i < coords.length; i++) {
      let nearest = Infinity;
      for (let j = 0; j < coords.length; j++) {
        if (i === j) continue;
        const dRa = (coords[i].ra - coords[j].ra) * Math.cos((coords[i].dec * Math.PI) / 180);
        const dDec = coords[i].dec - coords[j].dec;
        nearest = Math.min(nearest, Math.sqrt(dRa * dRa + dDec * dDec));
      }
      if (nearest < Infinity) distances.push(nearest);
    }
    distances.sort((a, b) => a - b);
    // Median nearest-neighbour distance ≈ panel FOV
    const cellDeg = distances.length > 0 ? distances[Math.floor(distances.length / 2)] : 1;

    const minRa = Math.min(...ras);
    const maxRa = Math.max(...ras);
    const minDec = Math.min(...decs);
    const maxDec = Math.max(...decs);
    const cosDec = Math.cos(((minDec + maxDec) / 2 * Math.PI) / 180);

    // Scale: pixels per degree. Target ~500px for the long axis.
    const TARGET_PX = 500;
    const spanRaDeg = (maxRa - minRa) * cosDec + cellDeg;
    const spanDecDeg = (maxDec - minDec) + cellDeg;
    const scale = TARGET_PX / Math.max(spanRaDeg, spanDecDeg, cellDeg);

    const cellPx = cellDeg * scale;
    const GAP = Math.max(2, cellPx * 0.06);
    const innerCell = cellPx - GAP;
    const PAD = innerCell * 0.5;

    const positions: Position[] = withCoords.map((p) => {
      // Sky convention: RA increases right-to-left, Dec increases bottom-to-top
      const x = PAD + (maxRa - p.ra!) * cosDec * scale;
      const y = PAD + (maxDec - p.dec!) * scale;
      return {
        panel: p,
        x,
        y,
        w: innerCell,
        h: innerCell,
        pct: completionPct(p.total_integration_seconds, maxInt),
      };
    });

    // Panels without coordinates go in a row below
    const mainH = PAD * 2 + spanDecDeg * scale;
    withoutCoords.forEach((p, i) => {
      positions.push({
        panel: p,
        x: PAD + i * (innerCell + GAP),
        y: mainH + GAP,
        w: innerCell,
        h: innerCell,
        pct: completionPct(p.total_integration_seconds, maxInt),
      });
    });

    const allX = positions.map((p) => p.x + p.w);
    const allY = positions.map((p) => p.y + p.h);
    const svgW = Math.max(...allX) + PAD;
    const svgH = Math.max(...allY) + PAD;

    return { positions, svgW, svgH };
  });

  const BORDER = 3;

  return (
    <div>
      <Show when={layout().positions.length > 0}>
        <div class="relative overflow-x-auto" onMouseLeave={() => setTooltip(null)}>
          <svg
            viewBox={`0 0 ${layout().svgW} ${layout().svgH}`}
            class="block mx-auto"
            style={{ "max-width": "100%", height: `${Math.min(layout().svgH, 500)}px` }}
            preserveAspectRatio="xMidYMid meet"
          >
            <defs>
              <For each={layout().positions}>
                {(pos) => (
                  <clipPath id={`clip-${pos.panel.panel_id}`}>
                    <rect
                      x={pos.x + BORDER}
                      y={pos.y + BORDER}
                      width={pos.w - BORDER * 2}
                      height={pos.h - BORDER * 2}
                      rx={2}
                    />
                  </clipPath>
                )}
              </For>
            </defs>
            <For each={layout().positions}>
              {(pos) => {
                const color = () => completionColor(pos.pct);
                const opacity = () => completionOpacity(pos.pct);
                const thumbUrl = () =>
                  pos.panel.thumbnail_url ? api.thumbnailUrl(pos.panel.thumbnail_url) : null;
                return (
                  <g
                    onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY, panel: pos.panel })}
                    onMouseMove={(e) => setTooltip({ x: e.clientX, y: e.clientY, panel: pos.panel })}
                    onMouseLeave={() => setTooltip(null)}
                    class="cursor-pointer"
                  >
                    {/* Completion-colored border rect */}
                    <rect
                      x={pos.x}
                      y={pos.y}
                      width={pos.w}
                      height={pos.h}
                      rx={3}
                      fill={color()}
                      opacity={opacity()}
                    />
                    {/* Thumbnail image or fallback fill */}
                    <Show
                      when={thumbUrl()}
                      fallback={
                        <rect
                          x={pos.x + BORDER}
                          y={pos.y + BORDER}
                          width={pos.w - BORDER * 2}
                          height={pos.h - BORDER * 2}
                          rx={2}
                          fill={color()}
                          opacity={opacity()}
                          stroke="rgba(255,255,255,0.15)"
                          stroke-width={1}
                        />
                      }
                    >
                      {(url) => (
                        <image
                          href={url()}
                          x={pos.x + BORDER}
                          y={pos.y + BORDER}
                          width={pos.w - BORDER * 2}
                          height={pos.h - BORDER * 2}
                          preserveAspectRatio="xMidYMid slice"
                          clip-path={`url(#clip-${pos.panel.panel_id})`}
                        />
                      )}
                    </Show>
                    {/* Label overlay */}
                    <text
                      x={pos.x + pos.w / 2}
                      y={pos.y + pos.h / 2 - 6}
                      text-anchor="middle"
                      dominant-baseline="central"
                      class="fill-white"
                      font-size={`${Math.max(9, Math.min(13, pos.w * 0.12))}px`}
                      font-weight="600"
                      style={{ "text-shadow": "0 1px 3px rgba(0,0,0,0.8)" }}
                    >
                      {pos.panel.panel_label}
                    </text>
                    <text
                      x={pos.x + pos.w / 2}
                      y={pos.y + pos.h / 2 + 10}
                      text-anchor="middle"
                      dominant-baseline="central"
                      class="fill-white"
                      font-size={`${Math.max(8, Math.min(10, pos.w * 0.1))}px`}
                      opacity={0.85}
                      style={{ "text-shadow": "0 1px 3px rgba(0,0,0,0.8)" }}
                    >
                      {formatHours(pos.panel.total_integration_seconds)}
                    </text>
                  </g>
                );
              }}
            </For>
          </svg>
        </div>
      </Show>

      {/* Tooltip */}
      <Show when={tooltip()}>
        {(t) => (
          <div
            class="fixed z-50 bg-theme-elevated border border-theme-border rounded px-3 py-2 text-xs shadow-[var(--shadow-md)] pointer-events-none"
            style={{ left: `${t().x + 12}px`, top: `${t().y - 70}px` }}
          >
            <div class="font-medium text-theme-text-primary">{t().panel.panel_label}</div>
            <div class="text-theme-text-secondary">
              {formatHours(t().panel.total_integration_seconds)} &middot; {t().panel.total_frames} frames
            </div>
            <Show when={Object.keys(t().panel.filter_distribution).length > 0}>
              <div class="text-theme-text-secondary">
                {Object.entries(t().panel.filter_distribution).map(([f, s]) => `${f}: ${formatHours(s)}`).join(", ")}
              </div>
            </Show>
          </div>
        )}
      </Show>

      {/* Legend */}
      <div class="flex flex-col items-center gap-1.5 mt-3 text-xs text-theme-text-secondary">
        <div class="flex items-center gap-4">
          <span class="flex items-center gap-1.5">
            <div class="w-3 h-3 rounded-sm" style={{ background: "#f85149", opacity: 0.8 }} /> &lt;40%
          </span>
          <span class="flex items-center gap-1.5">
            <div class="w-3 h-3 rounded-sm" style={{ background: "#d29922", opacity: 0.8 }} /> 40-80%
          </span>
          <span class="flex items-center gap-1.5">
            <div class="w-3 h-3 rounded-sm" style={{ background: "#26a641", opacity: 0.8 }} /> &gt;80%
          </span>
        </div>
        <div class="text-theme-text-tertiary">
          Completion relative to the most-imaged panel in this mosaic
        </div>
      </div>
    </div>
  );
};

export default MosaicGrid;
