import { createMemo, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { Chart, LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip } from "chart.js";
import type { SessionDetail, FrameRecord } from "../types";
import { useSettingsContext } from "./SettingsProvider";
import { formatTime } from "../utils/dateTime";
import { METRIC_DEFINITIONS, getMetricColor, getMetricDef, chartFontSize } from "../utils/chartConfig";
import MetricTogglePills from "./MetricTogglePills";
import FilterTogglePills from "./FilterTogglePills";
import RigTogglePills, { rigColor } from "./RigTogglePills";

Chart.register(LineController, CategoryScale, LinearScale, PointElement, LineElement, Tooltip);

interface Props {
  detail: SessionDetail;
  enabledRigs?: string[];
  onToggleRig?: (rig: string) => void;
}

export default function SessionMetricsChart(props: Props) {
  const settingsCtx = useSettingsContext();
  const { graphSettings, saveGraphSettings } = settingsCtx;
  const [expanded, setExpanded] = createSignal(graphSettings().session_chart_expanded);
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | null = null;
  let pendingRAF: number | null = null;

  const filters = () => props.detail.filter_details.map((f) => f.filter_name);

  const buildDatasets = () => {
    const enabledMetrics = graphSettings().enabled_metrics;
    const enabledFilters = graphSettings().enabled_filters;
    const rigs = props.detail.rigs ?? [];
    const multiRig = rigs.length > 1 && props.enabledRigs && props.enabledRigs.length > 0;

    const allFrames = [...props.detail.frames].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
    const labels = allFrames.map((f) => {
      const d = new Date(f.timestamp);
      return formatTime(d, settingsCtx.timezone());
    });

    const datasets: any[] = [];

    for (const metricKey of enabledMetrics) {
      const def = getMetricDef(metricKey);
      if (!def) continue;
      const field = def.frameField as keyof FrameRecord;

      if (multiRig) {
        for (let ri = 0; ri < rigs.length; ri++) {
          const rig = rigs[ri];
          if (!props.enabledRigs!.includes(rig.rig_label)) continue;
          const color = rigColor(ri);

          if (enabledFilters.includes("overall")) {
            datasets.push({
              label: `${def.label} (${rig.rig_label})`,
              data: allFrames.map((f) =>
                f.rig === rig.rig_label ? ((f[field] as number | null) ?? null) : null
              ),
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
              label: `${def.label} (${rig.rig_label} / ${filterName})`,
              data: allFrames.map((f) =>
                f.rig === rig.rig_label && f.filter_used === filterName
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
        const color = getMetricColor(def.colorVar);

        if (enabledFilters.includes("overall")) {
          datasets.push({
            label: def.label,
            data: allFrames.map((f) => (f[field] as number | null) ?? null),
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
            data: allFrames.map((f) =>
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
    props.enabledRigs;
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    if (expanded()) {
      // <Show> unmounts the canvas when collapsed, so the old chartInstance
      // is stale. Destroy it so a fresh chart is created on the new canvas.
      if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
      }
      pendingRAF = requestAnimationFrame(() => {
        pendingRAF = null;
        if (!canvasRef) {
          setTimeout(() => buildChart(), 0);
          return;
        }
        buildChart();
      });
    } else {
      // Collapsed - clean up the chart instance
      if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
      }
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
      <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
      <button
        class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
        classList={{ "text-theme-text-primary": expanded(), "text-theme-text-secondary": !expanded() }}
        onClick={toggleExpanded}
      >
        <span class="font-semibold border-l-2 border-theme-accent pl-2">Session Metrics</span>
        <svg
          class={`w-3.5 h-3.5 transition-transform duration-200 ${expanded() ? "rotate-180" : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
        </svg>
      </button>
      <Show when={expanded()}>
        <div class="p-3">
          <div class="flex justify-between items-start gap-4 mb-2">
            <div class="text-tiny text-theme-text-tertiary uppercase tracking-wider">Metrics</div>
            <MetricTogglePills />
          </div>
          <div class="mb-3">
            <FilterTogglePills filters={filters()} />
          </div>
          <Show when={(props.detail.rigs?.length ?? 0) > 1 && props.enabledRigs && props.onToggleRig}>
            <div class="mb-3">
              <RigTogglePills
                rigs={props.detail.rigs.map(r => r.rig_label)}
                enabledRigs={props.enabledRigs!}
                onToggle={props.onToggleRig!}
              />
            </div>
          </Show>
          <div style={{ height: "200px" }}>
            <canvas ref={canvasRef} />
          </div>
        </div>
      </Show>
      </div>
    </div>
  );
}
