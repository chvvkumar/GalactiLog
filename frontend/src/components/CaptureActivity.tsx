import { Component, createEffect, onCleanup, onMount } from "solid-js";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Tooltip,
  Filler,
} from "chart.js";
import { chartFontSize } from "../utils/chartConfig";

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Filler);

interface Props {
  history: { date: string; files_added: number }[];
}

const CaptureActivity: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | null = null;

  const render = () => {
    if (!canvasRef) return;
    const sorted = [...props.history].sort((a, b) => a.date.localeCompare(b.date));
    const labels = sorted.map((e) => e.date.slice(5));
    const fullDates = sorted.map((e) => e.date);
    const data = sorted.map((e) => e.files_added);

    const accent = getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim() || "#4f9eff";
    const axisColor = "rgba(200, 210, 220, 0.7)";
    const gridColor = "rgba(200, 210, 220, 0.1)";

    chartInstance?.destroy();
    chartInstance = new Chart(canvasRef, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Frames",
            data,
            borderColor: accent,
            backgroundColor: `${accent}22`,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHitRadius: 12,
            tension: 0.25,
            fill: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            ticks: {
              color: axisColor,
              font: { size: chartFontSize.tick() },
              maxRotation: 0,
              autoSkipPadding: 16,
            },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: { color: axisColor, font: { size: chartFontSize.tick() }, precision: 0 },
            grid: { color: gridColor },
          },
        },
        plugins: {
          tooltip: {
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            callbacks: {
              title: (items) => fullDates[items[0].dataIndex] ?? "",
              label: (ctx) => `${ctx.parsed.y} frames`,
            },
          },
        },
      },
    });
  };

  onMount(render);
  createEffect(() => {
    void props.history;
    render();
  });
  onCleanup(() => chartInstance?.destroy());

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-theme-text-primary font-medium text-sm">Capture Activity</h3>
        <span class="text-xs text-theme-text-secondary">Frames per capture night (last 30)</span>
      </div>
      {props.history.length === 0 ? (
        <div class="h-32 flex items-center justify-center text-xs text-theme-text-secondary">
          No capture history yet
        </div>
      ) : (
        <div class="relative h-32">
          <canvas ref={canvasRef} />
        </div>
      )}
    </div>
  );
};

export default CaptureActivity;
