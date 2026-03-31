import { createMemo, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip } from "chart.js";
import type { SessionDetail, FrameRecord } from "../types";
import { useSettingsContext } from "./SettingsProvider";
import { METRIC_DEFINITIONS, getMetricColor, getMetricDef, chartFontSize } from "../utils/chartConfig";
import MetricTogglePills from "./MetricTogglePills";
import FilterTogglePills from "./FilterTogglePills";

Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip);

interface Props {
  detail: SessionDetail;
}

export default function SessionMetricsChart(props: Props) {
  const { graphSettings, saveGraphSettings } = useSettingsContext();
  const [expanded, setExpanded] = createSignal(graphSettings().session_chart_expanded);
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | null = null;
  let pendingRAF: number | null = null;

  const filters = () => props.detail.filter_details.map((f) => f.filter_name);

  const buildDatasets = () => {
    const enabledMetrics = graphSettings().enabled_metrics;
    const enabledFilters = graphSettings().enabled_filters;
    const frames = [...props.detail.frames].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
    const labels = frames.map((f) => {
      const d = new Date(f.timestamp);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
    });

    const datasets: any[] = [];

    for (const metricKey of enabledMetrics) {
      const def = getMetricDef(metricKey);
      if (!def) continue;
      const color = getMetricColor(def.colorVar);
      const field = def.frameField as keyof FrameRecord;

      if (enabledFilters.includes("overall")) {
        datasets.push({
          label: def.label,
          data: frames.map((f) => (f[field] as number | null) ?? null),
          borderColor: color,
          backgroundColor: `${color}33`,
          borderWidth: 1.5,
          pointRadius: 0,
          pointHitRadius: 8,
          tension: 0.3,
          spanGaps: true,
          yAxisID: def.yAxisId,
        });
      }

      for (const filterName of enabledFilters) {
        if (filterName === "overall") continue;
        datasets.push({
          label: `${def.label} (${filterName})`,
          data: frames.map((f) =>
            f.filter_used === filterName ? ((f[field] as number | null) ?? null) : null
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

    return { labels, datasets };
  };

  const buildChart = () => {
    if (!canvasRef) return;

    const { labels, datasets } = buildDatasets();

    if (labels.length === 0) {
      if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
      return;
    }

    // Update existing chart in-place to avoid animation reset
    if (chartInstance) {
      chartInstance.data.labels = labels;
      chartInstance.data.datasets = datasets;
      chartInstance.update("none");
      return;
    }

    chartInstance = new Chart(canvasRef, {
      type: "line",
      data: { labels, datasets },
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
          },
        },
        scales: {
          x: {
            ticks: { color: "#64748b", font: { size: chartFontSize.tick() }, maxTicksLimit: 12 },
            grid: { color: "rgba(255,255,255,0.05)" },
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
    // Track reactive dependencies
    graphSettings();
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    if (expanded()) {
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

  const toggleExpanded = () => {
    const next = !expanded();
    setExpanded(next);
    saveGraphSettings({ session_chart_expanded: next });
  };

  return (
    <div>
      <button
        class="flex justify-between items-center w-full text-xs py-2.5 px-3 -mx-3 rounded-[var(--radius-md)] hover:bg-theme-hover transition-all cursor-pointer border-l-2 border-l-transparent hover:border-l-theme-accent/50"
        classList={{ "!border-l-theme-accent bg-theme-hover/50": expanded() }}
        onClick={toggleExpanded}
      >
        <span class="font-bold text-theme-text-primary">Session Metrics</span>
        <span class="px-2.5 py-1 border border-theme-border-em rounded text-label text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-accent transition-colors">
          {expanded() ? "Collapse" : "Expand"}
        </span>
      </button>
      <Show when={expanded()}>
        <div class="border border-theme-border rounded-[var(--radius-md)] p-3 bg-theme-base mt-2">
          <div class="flex justify-between items-start gap-4 mb-2">
            <div class="text-tiny text-theme-text-tertiary uppercase tracking-wider">Metrics</div>
            <MetricTogglePills />
          </div>
          <div class="mb-3">
            <FilterTogglePills filters={filters()} />
          </div>
          <div style={{ height: "200px" }}>
            <canvas ref={canvasRef} />
          </div>
        </div>
      </Show>
    </div>
  );
}
