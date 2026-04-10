import { createMemo, createEffect, onCleanup, Show } from "solid-js";
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler } from "chart.js";
import type { SessionDetail, FrameRecord } from "../types";
import { useSettingsContext } from "./SettingsProvider";
import { formatTime } from "../utils/dateTime";
import { METRIC_DEFINITIONS, getMetricColor, getMetricDef, chartFontSize } from "../utils/chartConfig";
import MetricTogglePills from "./MetricTogglePills";
import FilterTogglePills from "./FilterTogglePills";
import { rigColor } from "./RigTogglePills";

Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Filler);

interface Props {
  selectedDates: string[];
  sessionDetails: Record<string, SessionDetail>;
  expanded: boolean;
  onLoadSession: (date: string) => void;
}

/** Sentinel value inserted between sessions to create a visual gap */
const SESSION_GAP = "\u200B";

export default function TargetMetricsChart(props: Props) {
  const settingsCtx = useSettingsContext();
  const { graphSettings, filterColorMap } = settingsCtx;
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | null = null;
  let pendingRAF: number | null = null;

  // Auto-load session details for selected dates
  createEffect(() => {
    for (const date of props.selectedDates) {
      if (!props.sessionDetails[date]) {
        props.onLoadSession(date);
      }
    }
  });

  const allFilters = createMemo(() => {
    const filterSet = new Set<string>();
    for (const date of props.selectedDates) {
      const detail = props.sessionDetails[date];
      if (detail) {
        for (const fd of detail.filter_details) filterSet.add(fd.filter_name);
      }
    }
    return [...filterSet].sort();
  });

  const allRigs = createMemo(() => {
    const rigSet = new Set<string>();
    for (const date of props.selectedDates) {
      const detail = props.sessionDetails[date];
      if (detail) {
        for (const frame of detail.frames) {
          if (frame.rig) rigSet.add(frame.rig);
        }
      }
    }
    return [...rigSet].sort();
  });

  const isMultiRig = () => allRigs().length > 1;

  /** Build arrays of labels + per-metric data, with gaps between sessions */
  const chartFrameData = createMemo(() => {
    const sortedDates = [...props.selectedDates].sort();
    const labels: string[] = [];
    const framesByIndex: (FrameRecord | null)[] = [];
    const sessionBoundaries: number[] = []; // indices where sessions start

    for (let si = 0; si < sortedDates.length; si++) {
      const date = sortedDates[si];
      const detail = props.sessionDetails[date];
      if (!detail) continue;

      // Add gap between sessions
      if (labels.length > 0) {
        labels.push(SESSION_GAP);
        framesByIndex.push(null);
      }

      sessionBoundaries.push(labels.length);

      const frames = [...detail.frames].sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      );

      for (const frame of frames) {
        const d = new Date(frame.timestamp);
        const timeStr = formatTime(d, settingsCtx.timezone());
        labels.push(sortedDates.length > 1 ? `${date.slice(5)} ${timeStr}` : timeStr);
        framesByIndex.push(frame);
      }
    }

    return { labels, framesByIndex, sessionBoundaries };
  });

  // Mutable state read by the session boundary plugin - updated before each chart draw
  let currentBoundaries: number[] = [];
  let currentSortedDates: string[] = [];

  const sessionBoundaryPlugin = {
    id: "sessionBoundary",
    afterDraw(chart: Chart) {
      if (currentBoundaries.length <= 1) return;
      const ctx = chart.ctx;
      const xScale = chart.scales["x"];
      const yScale = chart.scales["left"] ?? chart.scales["right"];
      if (!xScale || !yScale) return;

      ctx.save();
      for (let bi = 0; bi < currentBoundaries.length; bi++) {
        const idx = currentBoundaries[bi];
        const x = xScale.getPixelForValue(idx);

        ctx.beginPath();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "rgba(255,255,255,0.25)";
        ctx.lineWidth = 1;
        ctx.moveTo(x, yScale.top);
        ctx.lineTo(x, yScale.bottom);
        ctx.stroke();
        ctx.setLineDash([]);

        const dateLabel = currentSortedDates[bi] ?? "";
        const tickFont = (xScale.options as any).ticks?.font as { size?: number } | undefined;
        const fontSize = tickFont?.size ?? chartFontSize.tick();
        ctx.fillStyle = "rgba(255,255,255,0.5)";
        ctx.font = `${fontSize}px sans-serif`;
        ctx.textAlign = "left";
        ctx.fillText(dateLabel, x + 3, yScale.top + fontSize + 2);
      }
      ctx.restore();
    },
  };

  const buildDatasets = () => {
    const enabledMetrics = graphSettings().enabled_metrics;
    const enabledFilters = graphSettings().enabled_filters;
    const { labels, framesByIndex, sessionBoundaries } = chartFrameData();
    const datasets: any[] = [];

    for (const metricKey of enabledMetrics) {
      const def = getMetricDef(metricKey);
      if (!def) continue;
      const field = def.frameField as keyof FrameRecord;
      const metricColor = getMetricColor(def.colorVar);

      if (isMultiRig()) {
        const rigs = allRigs();
        for (let ri = 0; ri < rigs.length; ri++) {
          const rig = rigs[ri];
          const color = rigColor(ri);

          if (enabledFilters.includes("overall")) {
            datasets.push({
              label: `${def.label} (${rig})`,
              data: framesByIndex.map((f) =>
                f && f.rig === rig ? ((f[field] as number | null) ?? null) : null
              ),
              borderColor: color,
              backgroundColor: `${color}33`,
              borderWidth: 1.5,
              pointRadius: 0,
              pointHitRadius: 8,
              tension: 0.3,
              spanGaps: false,
              yAxisID: def.yAxisId,
            });
          }

          for (const filterName of enabledFilters) {
            if (filterName === "overall") continue;
            datasets.push({
              label: `${def.label} (${rig} / ${filterName})`,
              data: framesByIndex.map((f) =>
                f && f.rig === rig && f.filter_used === filterName
                  ? ((f[field] as number | null) ?? null)
                  : null
              ),
              borderColor: color,
              backgroundColor: `${color}33`,
              borderWidth: 1.5,
              pointRadius: 0,
              pointHitRadius: 8,
              tension: 0.3,
              spanGaps: false,
              yAxisID: def.yAxisId,
              borderDash: [4, 2],
            });
          }
        }
      } else {
        if (enabledFilters.includes("overall")) {
          datasets.push({
            label: def.label,
            data: framesByIndex.map((f) => f ? ((f[field] as number | null) ?? null) : null),
            borderColor: metricColor,
            backgroundColor: `${metricColor}33`,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.3,
            spanGaps: false,
            yAxisID: def.yAxisId,
          });
        }

        for (const filterName of enabledFilters) {
          if (filterName === "overall") continue;
          const fColor = filterColorMap()[filterName] ?? metricColor;
          datasets.push({
            label: `${def.label} (${filterName})`,
            data: framesByIndex.map((f) =>
              f && f.filter_used === filterName ? ((f[field] as number | null) ?? null) : null
            ),
            borderColor: fColor,
            backgroundColor: `${fColor}33`,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.3,
            spanGaps: false,
            yAxisID: def.yAxisId,
            borderDash: [4, 2],
          });
        }
      }
    }

    return { labels, datasets, sessionBoundaries };
  };

  const buildChart = () => {
    if (!canvasRef) return;

    const { labels, datasets, sessionBoundaries } = buildDatasets();

    if (labels.length === 0) {
      if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
      return;
    }

    // Update closure state for the boundary plugin
    currentBoundaries = sessionBoundaries;
    currentSortedDates = [...props.selectedDates].sort();

    const gridColors = labels.map((_, i) =>
      sessionBoundaries.includes(i) ? "rgba(255,255,255,0.2)" : "rgba(255,255,255,0.03)"
    );

    // Update existing chart in-place to avoid animation reset
    if (chartInstance) {
      chartInstance.data.labels = labels;
      chartInstance.data.datasets = datasets;
      const xScale = chartInstance.options.scales!["x"] as any;
      xScale.ticks.callback = (_: unknown, index: number) => {
        const label = labels[index];
        return label === SESSION_GAP ? "" : label;
      };
      xScale.grid.color = (ctx: any) => gridColors[ctx.index] ?? "rgba(255,255,255,0.03)";
      chartInstance.update("none");
      return;
    }

    chartInstance = new Chart(canvasRef, {
      type: "line",
      data: { labels, datasets },
      plugins: [sessionBoundaryPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(0,0,0,0.8)",
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            padding: 8,
            filter: (item) => item.raw !== null,
          },
        },
        scales: {
          x: {
            ticks: {
              color: "#64748b",
              font: { size: chartFontSize.tick() },
              maxTicksLimit: 15,
              callback: function(_, index) {
                const label = labels[index];
                return label === SESSION_GAP ? "" : label;
              },
            },
            grid: {
              color: (ctx) => gridColors[ctx.index] ?? "rgba(255,255,255,0.03)",
            },
          },
          left: {
            type: "linear",
            position: "left",
            ticks: { color: "#64748b", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
          right: {
            type: "linear",
            position: "right",
            ticks: { color: "#64748b", font: { size: chartFontSize.tick() } },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
  };

  createEffect(() => {
    // Track all reactive dependencies
    chartFrameData();
    graphSettings();
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    if (props.expanded) {
      pendingRAF = requestAnimationFrame(() => {
        pendingRAF = null;
        buildChart();
      });
    }
  });

  onCleanup(() => {
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
  });

  const availableMetricKeys = () => METRIC_DEFINITIONS.map((m) => m.key);
  const loadingCount = createMemo(() => {
    let loading = 0;
    for (const date of props.selectedDates) {
      if (!props.sessionDetails[date]) loading++;
    }
    return loading;
  });

  return (
    <div class="border border-theme-border rounded-[var(--radius-md)] p-3 bg-theme-base mt-2">
      <div class="flex justify-between items-start gap-4 mb-2">
        <div class="flex items-center gap-3">
          <Show when={loadingCount() > 0}>
            <div class="text-tiny text-theme-text-tertiary">
              Loading {loadingCount()} session{loadingCount() > 1 ? "s" : ""}...
            </div>
          </Show>
        </div>
        <MetricTogglePills availableMetrics={availableMetricKeys()} />
      </div>
      <div class="mb-3">
        <FilterTogglePills filters={allFilters()} />
      </div>
      <div style={{ height: "220px" }}>
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}

