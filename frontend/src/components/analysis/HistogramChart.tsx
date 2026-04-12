import { Component, createEffect, onCleanup } from "solid-js";
import { Chart } from "chart.js";
import "../../utils/chartRegistry";
import type { DistributionResponse } from "../../types";
import { chartFontSize } from "../../utils/chartConfig";

interface Props {
  data: DistributionResponse | undefined;
  loading: boolean;
}

const HistogramChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { bins } = props.data;
    const labels = bins.map((b) => `${b.bin_start.toFixed(1)}`);

    chartInstance = new Chart(canvasRef, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Count",
            data: bins.map((b) => b.count),
            backgroundColor: "rgba(100, 180, 255, 0.6)",
            borderColor: "rgba(130, 200, 255, 0.9)",
            borderWidth: 1,
          },
        ],
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
            callbacks: {
              title: (items) => {
                const i = items[0]?.dataIndex;
                if (i === undefined) return "";
                const b = bins[i];
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
