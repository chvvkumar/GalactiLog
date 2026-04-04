import { Component, createEffect, onCleanup } from "solid-js";
import {
  Chart,
  BarController,
  BarElement,
  LinearScale,
  CategoryScale,
  Tooltip,
  PointElement,
  ScatterController,
} from "chart.js";
import type { BoxPlotGroup } from "../../types";
import { chartFontSize } from "../../utils/chartConfig";

Chart.register(BarController, BarElement, LinearScale, CategoryScale, Tooltip, PointElement, ScatterController);

interface Props {
  groups: BoxPlotGroup[];
  loading: boolean;
  metricLabel?: string;
}

const BoxPlotChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || props.groups.length === 0) return;
    chartInstance?.destroy();

    const labels = props.groups.map((g) => g.group_name);
    const iqrData = props.groups.map((g) => [g.q1, g.q3] as [number, number]);
    const whiskerData = props.groups.map((g) => [g.min, g.max] as [number, number]);
    const medianData = props.groups.map((g, i) => ({ x: g.median, y: i }));

    const datasets: any[] = [
      {
        label: "Whiskers",
        data: whiskerData,
        backgroundColor: "rgba(200, 210, 220, 0.15)",
        borderColor: "rgba(200, 210, 220, 0.5)",
        borderWidth: 1,
        barPercentage: 0.15,
        categoryPercentage: 1,
      },
      {
        label: "IQR",
        data: iqrData,
        backgroundColor: "rgba(100, 180, 255, 0.4)",
        borderColor: "rgba(130, 200, 255, 0.8)",
        borderWidth: 1,
        barPercentage: 0.5,
        categoryPercentage: 1,
      },
      {
        label: "Median",
        type: "scatter" as const,
        data: medianData,
        backgroundColor: "rgba(255, 180, 80, 1)",
        borderColor: "rgba(255, 180, 80, 1)",
        pointRadius: 6,
        pointStyle: "line",
        rotation: 90,
      },
    ];

    const outlierData: { x: number; y: number }[] = [];
    props.groups.forEach((g, i) => {
      g.outliers.forEach((o) => outlierData.push({ x: o, y: i }));
    });
    if (outlierData.length > 0) {
      datasets.push({
        label: "Outliers",
        type: "scatter" as const,
        data: outlierData,
        backgroundColor: "transparent",
        borderColor: "rgba(255, 100, 100, 0.7)",
        pointRadius: 3,
        borderWidth: 1.5,
      });
    }

    chartInstance = new Chart(canvasRef, {
      type: "bar",
      data: { labels, datasets },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            title: { display: true, text: props.metricLabel || "Value", color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
          y: {
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.08)" },
          },
        },
        plugins: {
          tooltip: {
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            callbacks: {
              label: (ctx) => {
                const g = props.groups[ctx.dataIndex];
                if (!g) return "";
                if (ctx.dataset.label === "IQR") {
                  return `Q1: ${g.q1.toFixed(2)}, Median: ${g.median.toFixed(2)}, Q3: ${g.q3.toFixed(2)} (N=${g.count})`;
                }
                if (ctx.dataset.label === "Whiskers") {
                  return `Range: ${g.min.toFixed(2)} \u2013 ${g.max.toFixed(2)}`;
                }
                return "";
              },
            },
          },
          legend: { display: false },
        },
      },
    });
  };

  createEffect(() => {
    const _ = props.groups;
    renderChart();
  });

  onCleanup(() => chartInstance?.destroy());

  return (
    <div class="relative w-full h-full">
      {props.loading && props.groups.length === 0 && (
        <div class="absolute inset-0 flex items-center justify-center text-sm text-theme-text-secondary">Loading...</div>
      )}
      <canvas ref={canvasRef} />
    </div>
  );
};

export default BoxPlotChart;
