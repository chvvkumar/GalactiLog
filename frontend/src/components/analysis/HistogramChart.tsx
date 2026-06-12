import { Component, createEffect, onCleanup } from "solid-js";
import { Chart } from "chart.js";
import "../../utils/chartRegistry";
import type { DistributionResponse } from "../../types";
import { chartFontSize } from "../../utils/chartConfig";

interface Props {
  data: DistributionResponse | undefined;
  loading: boolean;
  baselineMedian?: number | null;
}

// Maps a metric value to a fractional position on the histogram's category axis.
// Each bin occupies one category slot centered on its integer index; the value is
// interpolated within its bin. Returns null when the value is outside all bins.
function medianCategoryIndex(
  bins: { bin_start: number; bin_end: number }[],
  value: number,
): number | null {
  for (let i = 0; i < bins.length; i++) {
    const b = bins[i];
    if (value >= b.bin_start && value <= b.bin_end) {
      const width = b.bin_end - b.bin_start;
      const frac = width > 0 ? (value - b.bin_start) / width : 0.5;
      return i - 0.5 + frac;
    }
  }
  if (value < bins[0].bin_start) return -0.5;
  if (value > bins[bins.length - 1].bin_end) return bins.length - 0.5;
  return null;
}

const HistogramChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { bins } = props.data;
    const labels = bins.map((b) => `${b.bin_start.toFixed(1)}`);

    const datasets: any[] = [
      {
        label: "Count",
        data: bins.map((b) => b.count),
        backgroundColor: "rgba(100, 180, 255, 0.6)",
        borderColor: "rgba(130, 200, 255, 0.9)",
        borderWidth: 1,
      },
    ];

    // Vertical baseline-median reference line. The x-axis is a category scale, so
    // the median value is mapped to a fractional category index via the bin centers.
    const median = props.baselineMedian;
    if (median != null && bins.length > 0) {
      const idx = medianCategoryIndex(bins, median);
      if (idx != null) {
        const maxCount = Math.max(...bins.map((b) => b.count));
        datasets.push({
          label: "Baseline median",
          type: "line" as const,
          data: [
            { x: idx, y: 0 },
            { x: idx, y: maxCount },
          ],
          borderColor: "rgba(200, 210, 220, 0.55)",
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 0,
          pointHoverRadius: 0,
          fill: false,
        });
      }
    }

    chartInstance = new Chart(canvasRef, {
      type: "bar",
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            title: { display: true, text: "Value", color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
          y: {
            title: { display: true, text: "Count", color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
        },
        plugins: {
          tooltip: {
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            filter: (item) => item.dataset.label !== "Baseline median",
            callbacks: {
              title: (items) => {
                const i = items[0]?.dataIndex;
                if (i === undefined) return "";
                const b = bins[i];
                if (!b) return "";
                return `${b.bin_start.toFixed(2)} \u2013 ${b.bin_end.toFixed(2)}`;
              },
            },
          },
          legend: { display: false },
        },
      },
    });
  };

  createEffect(() => {
    const _ = props.data;
    const _m = props.baselineMedian;
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

export default HistogramChart;
