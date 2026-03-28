import { createMemo, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip } from "chart.js";
import type { SessionDetail, FrameRecord } from "../types";
import { useSettingsContext } from "./SettingsProvider";
import { METRIC_DEFINITIONS, getMetricColor, getMetricDef } from "../utils/chartConfig";
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

  const buildChart = () => {
    if (!canvasRef) return;
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }

    const enabledMetrics = graphSettings().enabled_metrics;
    const enabledFilters = graphSettings().enabled_filters;
    const frames = [...props.detail.frames].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
    const labels = frames.map((f) => {
      const d = new Date(f.timestamp);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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

    chartInstance = new Chart(canvasRef, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(0,0,0,0.8)",
            titleFont: { size: 11 },
            bodyFont: { size: 10 },
            padding: 8,
          },
        },
        scales: {
          x: {
            ticks: { color: "#64748b", font: { size: 9 }, maxTicksLimit: 12 },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
          left: {
            type: "linear",
            position: "left",
            ticks: { color: "#64748b", font: { size: 9 } },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
          right: {
            type: "linear",
            position: "right",
            ticks: { color: "#64748b", font: { size: 9 } },
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
        class="flex justify-between items-center w-full text-xs py-2.5 px-3 -mx-3 rounded-lg hover:bg-theme-elevated transition-colors cursor-pointer"
        onClick={toggleExpanded}
      >
        <span class="font-bold text-theme-text-primary">Session Metrics</span>
        <span class="px-2.5 py-1 border border-theme-border-em rounded text-[11px] text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-accent transition-colors">
          {expanded() ? "Collapse" : "Expand"}
        </span>
      </button>
      <Show when={expanded()}>
        <div class="border border-theme-border rounded-lg p-3 bg-theme-base mt-2">
          <div class="flex justify-between items-start gap-4 mb-2">
            <div class="text-[9px] text-theme-text-tertiary uppercase tracking-wider">Metrics</div>
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
