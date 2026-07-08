import { Component, createEffect, onCleanup } from "solid-js";
import { Chart } from "chart.js";
import "../../utils/chartRegistry";
import "chartjs-adapter-date-fns";
import type { TimeSeriesResponse } from "../../api/types";
import { chartFontSize } from "../../utils/chartConfig";
import { madZ, bandForZ, type MetricBaseline } from "../../utils/frameQuality";

interface Props {
  data: TimeSeriesResponse | undefined;
  loading: boolean;
  smoothing: "raw" | "ma7" | "ma30";
  metricLabel?: string;
  baseline?: MetricBaseline | null;
  higherIsBetter?: boolean;
}

// Subtle point tints matching the theme warning/error tokens (watch/reject bands).
const BAND_POINT_COLOR: Record<string, string | null> = {
  watch: "rgba(245, 180, 80, 0.85)", // theme-warning (amber)
  reject: "rgba(245, 110, 110, 0.9)", // theme-error (red)
};

const TimeSeriesChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { points, ma_7, ma_30 } = props.data;
    const baseline = props.baseline;
    const higherIsBetter = props.higherIsBetter ?? false;

    const defaultPointColor = "rgba(100, 180, 255, 0.6)";
    const pointColors = baseline
      ? points.map((p) => {
          const band = bandForZ(madZ(p.value, baseline, higherIsBetter));
          return BAND_POINT_COLOR[band] ?? defaultPointColor;
        })
      : defaultPointColor;

    const datasets: any[] = [];

    // Baseline reference bands drawn beneath the points: a filled median ± 1*MAD
    // band and a fainter median + 3*MAD reject bound. Skipped when the baseline is
    // too sparse or uniform (baseline === null).
    if (baseline && baseline.median != null && baseline.mad != null && points.length > 0) {
      const xs = points.map((p) => p.date);
      const med = baseline.median;
      const mad = baseline.mad;
      const flat = (y: number) => xs.map((x) => ({ x, y }));
      const lineBase = {
        type: "line" as const,
        pointRadius: 0,
        pointHoverRadius: 0,
        fill: false,
        spanGaps: true,
      };
      // Reject bound: median + 3*MAD on the "worse" side (and mirror for better metrics).
      datasets.push({
        ...lineBase,
        label: "+3 MAD",
        data: flat(higherIsBetter ? med - 3 * mad : med + 3 * mad),
        borderColor: "rgba(245, 110, 110, 0.35)",
        borderWidth: 1,
        borderDash: [4, 4],
      });
      // Upper edge of the ±1 MAD band.
      datasets.push({
        ...lineBase,
        label: "+1 MAD",
        data: flat(med + mad),
        borderColor: "rgba(200, 210, 220, 0.25)",
        borderWidth: 1,
        backgroundColor: "rgba(120, 190, 255, 0.06)",
        fill: "+1", // fill to the next dataset (lower edge of band)
      });
      // Lower edge of the ±1 MAD band.
      datasets.push({
        ...lineBase,
        label: "-1 MAD",
        data: flat(med - mad),
        borderColor: "rgba(200, 210, 220, 0.25)",
        borderWidth: 1,
      });
      // Baseline median line.
      datasets.push({
        ...lineBase,
        label: "Baseline median",
        data: flat(med),
        borderColor: "rgba(200, 210, 220, 0.45)",
        borderWidth: 1.5,
      });
    }

    datasets.push({
      label: "Nightly Median",
      data: points.map((p) => ({ x: p.date, y: p.value })),
      backgroundColor: pointColors,
      borderColor: "rgba(130, 200, 255, 0.8)",
      borderWidth: 1,
      pointRadius: 4,
      pointHoverRadius: 6,
      showLine: false,
    });

    if (props.smoothing === "ma7" && ma_7.length > 0) {
      datasets.push({
        label: "7-Night MA",
        data: ma_7.map((p) => ({ x: p.date, y: p.value })),
        type: "line" as const,
        borderColor: "rgba(255, 180, 80, 0.9)",
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        tension: 0.3,
      });
    }

    if (props.smoothing === "ma30" && ma_30.length > 0) {
      datasets.push({
        label: "30-Night MA",
        data: ma_30.map((p) => ({ x: p.date, y: p.value })),
        type: "line" as const,
        borderColor: "rgba(100, 220, 100, 0.9)",
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
        tension: 0.3,
      });
    }

    chartInstance = new Chart(canvasRef, {
      type: "scatter",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            type: "time",
            time: { unit: "day", tooltipFormat: "yyyy-MM-dd" },
            title: { display: true, text: "Date", color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() }, maxRotation: 45 },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
          y: {
            title: { display: true, text: props.metricLabel || "Value", color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
        },
        plugins: {
          tooltip: {
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            filter: (item) =>
              !["Baseline median", "+1 MAD", "-1 MAD", "+3 MAD"].includes(item.dataset.label || ""),
            callbacks: {
              label: (ctx) => {
                const pt = points.find((p) => p.value === ctx.parsed.y);
                if (pt) {
                  return `${pt.target_name || "Mixed"}: ${pt.value.toFixed(2)} (${pt.frame_count} frames)`;
                }
                return `${ctx.parsed.y?.toFixed(2)}`;
              },
            },
          },
          legend: { display: false },
        },
      },
    });
  };

  createEffect(() => {
    const _d = props.data;
    const _s = props.smoothing;
    const _b = props.baseline;
    const _h = props.higherIsBetter;
    renderChart();
  });

  onCleanup(() => chartInstance?.destroy());

  return (
    <div class="relative w-full h-full">
      {props.loading && !props.data && (
        <div class="absolute inset-0 flex items-center justify-center text-sm text-theme-text-secondary">Loading...</div>
      )}
      <canvas ref={canvasRef} />
    </div>
  );
};

export default TimeSeriesChart;
