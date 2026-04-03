import { Component, For, Show, createMemo, createSignal } from "solid-js";
import { api } from "../../api/client";
import { remToPx } from "../../utils/chartConfig";
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

  const layout = createMemo((): { positions: Position[]; svgW: number; svgH: number; spatial: boolean } => {
    const panels = props.panels;
    if (panels.length === 0) return { positions: [], svgW: 0, svgH: 0, spatial: false };

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
      const CELL = 200;
      const GAP = 8;
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
        spatial: false,
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
      // Display convention: lower RA on left, higher Dec on top
      const x = PAD + (p.ra! - minRa) * cosDec * scale;
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

    return { positions, svgW, svgH, spatial: true };
  });

  const BORDER = 3;

  // Determine the majority pier side so we can rotate mismatched thumbnails 180°
  const majorityPierSide = createMemo(() => {
    const counts: Record<string, number> = {};
    for (const p of props.panels) {
      const ps = p.thumbnail_pier_side;
      if (ps) counts[ps] = (counts[ps] || 0) + 1;
    }
    let best = "";
    let bestCount = 0;
    for (const [side, count] of Object.entries(counts)) {
      if (count > bestCount) {
        best = side;
        bestCount = count;
      }
    }
    return best;
  });

  const needsRotation = (panel: PanelStats) => {
    const majority = majorityPierSide();
    return majority && panel.thumbnail_pier_side && panel.thumbnail_pier_side !== majority;
  };

  return (
    <div>
      <Show when={layout().positions.length > 0}>
        <div class="relative overflow-x-auto" onMouseLeave={() => setTooltip(null)}>
          <svg
            viewBox={`0 0 ${layout().svgW} ${layout().svgH}`}
            class="block mx-auto w-full"
            style={{ "max-height": "70vh" }}
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
                      {(url) => {
                        const imgX = pos.x + BORDER;
                        const imgY = pos.y + BORDER;
                        const imgW = pos.w - BORDER * 2;
                        const imgH = pos.h - BORDER * 2;
                        const cx = imgX + imgW / 2;
                        const cy = imgY + imgH / 2;
                        // Build transform: spatial layout flips RA axis so mirror images horizontally;
                        // pier side mismatch adds 180° rotation (equivalent to also flipping vertically)
                        const parts: string[] = [];
                        if (layout().spatial) parts.push(`translate(${2 * cx} 0) scale(-1 1)`);
                        if (needsRotation(pos.panel)) parts.push(`rotate(180 ${cx} ${cy})`);
                        const xform = parts.length > 0 ? parts.join(" ") : undefined;
                        return (
                          <image
                            href={url()}
                            x={imgX}
                            y={imgY}
                            width={imgW}
                            height={imgH}
                            preserveAspectRatio="xMidYMid slice"
                            clip-path={`url(#clip-${pos.panel.panel_id})`}
                            transform={xform}
                          />
                        );
                      }}
                    </Show>
                    {/* Label overlay */}
                    <text
                      x={pos.x + pos.w / 2}
                      y={pos.y + pos.h / 2 - 6}
                      text-anchor="middle"
                      dominant-baseline="central"
                      class="fill-white"
                      font-size={`${Math.max(remToPx(0.643), Math.min(remToPx(0.929), pos.w * 0.12))}px`}
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
                      font-size={`${Math.max(remToPx(0.571), Math.min(remToPx(0.714), pos.w * 0.1))}px`}
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
