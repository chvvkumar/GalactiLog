import { Component, For, Show, createMemo, createSignal } from "solid-js";
import type { PanelStats } from "../../types";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

function getCompletionColor(pct: number): string {
  if (pct >= 80) return "var(--color-success, #26a641)";
  if (pct >= 40) return "var(--color-warning, #d29922)";
  return "var(--color-error, #f85149)";
}

interface Props {
  panels: PanelStats[];
}

const MosaicGrid: Component<Props> = (props) => {
  const [tooltip, setTooltip] = createSignal<{ x: number; y: number; panel: PanelStats } | null>(null);

  const gridData = createMemo(() => {
    const panels = props.panels;
    if (panels.length === 0) return { positions: [], width: 0, height: 0 };

    // Compute relative RA/Dec positions
    const withCoords = panels.filter((p) => p.ra != null && p.dec != null);
    const withoutCoords = panels.filter((p) => p.ra == null || p.dec == null);

    // Max integration for color scaling
    const maxInt = Math.max(...panels.map((p) => p.total_integration_seconds), 1);

    if (withCoords.length < 2) {
      // Fall back to a simple row layout
      const CELL = 80;
      const GAP = 10;
      return {
        positions: panels.map((p, i) => ({
          panel: p,
          x: i * (CELL + GAP),
          y: 0,
          width: CELL,
          height: CELL,
          pct: (p.total_integration_seconds / maxInt) * 100,
        })),
        width: panels.length * (CELL + GAP),
        height: CELL,
      };
    }

    // Map RA/Dec to pixel positions
    const ras = withCoords.map((p) => p.ra!);
    const decs = withCoords.map((p) => p.dec!);
    const minRa = Math.min(...ras);
    const maxRa = Math.max(...ras);
    const minDec = Math.min(...decs);
    const maxDec = Math.max(...decs);
    const raRange = maxRa - minRa || 1;
    const decRange = maxDec - minDec || 1;

    const GRID_SIZE = 400;
    const CELL = 70;
    const PADDING = 50;

    const positions = withCoords.map((p) => {
      // RA increases to the left in sky coordinates, invert for display
      const xNorm = 1 - (p.ra! - minRa) / raRange;
      const yNorm = 1 - (p.dec! - minDec) / decRange;
      return {
        panel: p,
        x: PADDING + xNorm * (GRID_SIZE - 2 * PADDING - CELL),
        y: PADDING + yNorm * (GRID_SIZE - 2 * PADDING - CELL),
        width: CELL,
        height: CELL,
        pct: (p.total_integration_seconds / maxInt) * 100,
      };
    });

    // Place panels without coordinates in a row below
    withoutCoords.forEach((p, i) => {
      positions.push({
        panel: p,
        x: PADDING + i * (CELL + 10),
        y: GRID_SIZE - CELL,
        width: CELL,
        height: CELL,
        pct: (p.total_integration_seconds / maxInt) * 100,
      });
    });

    return { positions, width: GRID_SIZE, height: GRID_SIZE };
  });

  return (
    <div class="relative" onMouseLeave={() => setTooltip(null)}>
      <svg
        width={gridData().width}
        height={gridData().height}
        class="block mx-auto"
      >
        <For each={gridData().positions}>
          {(pos) => (
            <g
              onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY, panel: pos.panel })}
              onMouseLeave={() => setTooltip(null)}
              class="cursor-pointer"
            >
              <rect
                x={pos.x}
                y={pos.y}
                width={pos.width}
                height={pos.height}
                rx={4}
                fill={getCompletionColor(pos.pct)}
                opacity={0.8}
                stroke="var(--color-theme-border)"
                stroke-width={1}
              />
              <text
                x={pos.x + pos.width / 2}
                y={pos.y + pos.height / 2 - 6}
                text-anchor="middle"
                class="fill-white"
                font-size="11"
                font-weight="bold"
              >
                {pos.panel.panel_label}
              </text>
              <text
                x={pos.x + pos.width / 2}
                y={pos.y + pos.height / 2 + 10}
                text-anchor="middle"
                class="fill-white"
                font-size="9"
                opacity={0.8}
              >
                {formatHours(pos.panel.total_integration_seconds)}
              </text>
            </g>
          )}
        </For>
      </svg>

      <Show when={tooltip()}>
        {(t) => (
          <div
            class="fixed z-50 bg-theme-elevated border border-theme-border rounded px-3 py-2 text-xs shadow-[var(--shadow-md)] pointer-events-none"
            style={{ left: `${t().x + 10}px`, top: `${t().y - 60}px` }}
          >
            <div class="font-medium text-theme-text-primary">{t().panel.target_name}</div>
            <div class="text-theme-text-secondary">
              {formatHours(t().panel.total_integration_seconds)} &middot; {t().panel.total_frames} frames
            </div>
            <div class="text-theme-text-secondary">
              {Object.entries(t().panel.filter_distribution).map(([f, s]) => `${f}: ${formatHours(s)}`).join(", ")}
            </div>
          </div>
        )}
      </Show>

      {/* Legend */}
      <div class="flex items-center justify-center gap-4 mt-2 text-xs text-theme-text-secondary">
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-error, #f85149)" }} /> &lt;40%
        </span>
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-warning, #d29922)" }} /> 40-80%
        </span>
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-success, #26a641)" }} /> &gt;80%
        </span>
      </div>
    </div>
  );
};

export default MosaicGrid;
