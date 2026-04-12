import { Component, createEffect, onCleanup } from "solid-js";
import { Chart } from "chart.js";
import "../../utils/chartRegistry";
import "chartjs-adapter-date-fns";
import type { TimeSeriesResponse } from "../../types";
import { chartFontSize } from "../../utils/chartConfig";

interface Props {
  data: TimeSeriesResponse | undefined;
  loading: boolean;
  smoothing: "raw" | "ma7" | "ma30";
  metricLabel?: string;
}

const TimeSeriesChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { points, ma_7, ma_30 } = props.data;

    const datasets: any[] = [
      {
        label: "Nightly Median",
        data: points.map((p) => ({ x: p.date, y: p.value })),
        backgroundColor: "rgba(100, 180, 255, 0.6)",
        borderColor: "rgba(130, 200, 255, 0.8)",
        borderWidth: 1,
        pointRadius: 4,
        pointHoverRadius: 6,
        showLine: false,
      },
    ];

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
