import { Component, createEffect, onCleanup } from "solid-js";
import {
  Chart,
  ScatterController,
  LinearScale,
  PointElement,
  Tooltip,
  LineElement,
} from "chart.js";
import type { CorrelationResponse } from "../../types";

Chart.register(ScatterController, LinearScale, PointElement, Tooltip, LineElement);

const METRIC_LABELS: Record<string, string> = {
  humidity: "Humidity (%)",
  wind_speed: "Wind Speed",
  ambient_temp: "Ambient Temp (\u00b0C)",
  dew_point: "Dew Point (\u00b0C)",
  pressure: "Pressure (hPa)",
  cloud_cover: "Cloud Cover (%)",
  sky_quality: "Sky Quality (SQM)",
  focuser_temp: "Focuser Temp (\u00b0C)",
  airmass: "Airmass",
  sensor_temp: "Sensor Temp (\u00b0C)",
  hfr: "HFR (px)",
  fwhm: "FWHM",
  eccentricity: "Eccentricity",
  guiding_rms: "Guiding RMS (\")",
  guiding_rms_ra: "Guiding RA RMS (\")",
  guiding_rms_dec: "Guiding DEC RMS (\")",
  detected_stars: "Detected Stars",
  adu_mean: "ADU Mean",
  adu_median: "ADU Median",
  adu_stdev: "ADU StDev",
};

const METRIC_SHORT: Record<string, string> = {
  humidity: "humidity",
  wind_speed: "wind",
  ambient_temp: "temperature",
  dew_point: "dew point",
  pressure: "pressure",
  cloud_cover: "cloud cover",
  sky_quality: "sky quality",
  focuser_temp: "focuser temp",
  airmass: "airmass",
  sensor_temp: "sensor temp",
  hfr: "HFR",
  fwhm: "FWHM",
  eccentricity: "eccentricity",
  guiding_rms: "guiding RMS",
  guiding_rms_ra: "RA guiding",
  guiding_rms_dec: "DEC guiding",
  detected_stars: "star count",
  adu_mean: "ADU mean",
  adu_median: "ADU median",
  adu_stdev: "ADU noise",
};

function describeCorrelation(data: CorrelationResponse): string {
  const { trend, x_metric, y_metric, points } = data;
  if (!trend || points.length < 3) return `Not enough data to determine a pattern (${points.length} points).`;

  const xName = METRIC_SHORT[x_metric] || x_metric;
  const yName = METRIC_SHORT[y_metric] || y_metric;
  const r2 = trend.r_squared;
  const rising = trend.slope > 0;

  // Strength description
  let strength: string;
  let verdict: string;
  if (r2 < 0.05) {
    strength = "No meaningful correlation";
    verdict = `${xName} does not appear to affect your ${yName}.`;
  } else if (r2 < 0.15) {
    strength = "Weak correlation";
    verdict = rising
      ? `${yName} tends to increase slightly with higher ${xName}, but the effect is minor.`
      : `${yName} tends to decrease slightly with higher ${xName}, but the effect is minor.`;
  } else if (r2 < 0.4) {
    strength = "Moderate correlation";
    verdict = rising
      ? `Higher ${xName} is associated with worse ${yName}. Consider this a factor in your imaging conditions.`
      : `Higher ${xName} is associated with better ${yName}. This is a meaningful pattern in your data.`;
  } else {
    strength = "Strong correlation";
    verdict = rising
      ? `${xName} has a strong negative impact on your ${yName}. This is a key factor at your site.`
      : `${xName} strongly improves your ${yName}. This is a key factor at your site.`;
  }

  return `${strength} (R²=${r2.toFixed(2)}). ${verdict}`;
}

interface Props {
  data: CorrelationResponse | undefined;
  loading: boolean;
  title?: string;
}

const CorrelationChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { points, trend, x_metric, y_metric, granularity } = props.data;
    const isSession = granularity === "session";

    const datasets: any[] = [
      {
        label: "Data",
        data: points.map((p) => ({ x: p.x, y: p.y })),
        backgroundColor: isSession
          ? "rgba(99, 132, 255, 0.8)"
          : "rgba(99, 132, 255, 0.3)",
        pointRadius: isSession ? 5 : 3,
        pointHoverRadius: isSession ? 7 : 5,
      },
    ];

    // Add trend line
    if (trend && points.length >= 3) {
      const xs = points.map((p) => p.x).sort((a, b) => a - b);
      const xMin = xs[0];
      const xMax = xs[xs.length - 1];
      datasets.push({
        label: `Trend (R\u00b2=${trend.r_squared.toFixed(2)})`,
        data: [
          { x: xMin, y: trend.slope * xMin + trend.intercept },
          { x: xMax, y: trend.slope * xMax + trend.intercept },
        ],
        type: "line" as const,
        borderColor: "rgba(255, 99, 132, 0.7)",
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
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
            title: { display: true, text: METRIC_LABELS[x_metric] || x_metric, color: "rgb(var(--text-secondary))" },
            ticks: { color: "rgb(var(--text-secondary))" },
            grid: { color: "rgba(var(--text-secondary), 0.1)" },
          },
          y: {
            title: { display: true, text: METRIC_LABELS[y_metric] || y_metric, color: "rgb(var(--text-secondary))" },
            ticks: { color: "rgb(var(--text-secondary))" },
            grid: { color: "rgba(var(--text-secondary), 0.1)" },
          },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const pt = points[ctx.dataIndex];
                if (!pt) return `(${ctx.parsed.x}, ${ctx.parsed.y})`;
                return `${pt.target_name || "Unknown"} (${pt.date}): ${ctx.parsed.x.toFixed(1)}, ${ctx.parsed.y.toFixed(2)}`;
              },
            },
          },
        },
      },
    });
  };

  createEffect(() => {
    // Reactive dependencies
    const _ = props.data;
    renderChart();
  });

  onCleanup(() => chartInstance?.destroy());

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      {props.title && <h3 class="text-sm font-medium text-theme-text-primary mb-2">{props.title}</h3>}
      <div class="relative" style={{ height: "300px" }}>
        {props.loading && (
          <div class="absolute inset-0 flex items-center justify-center text-xs text-theme-text-secondary">
            Loading...
          </div>
        )}
        <canvas ref={canvasRef} />
      </div>
      {props.data && props.data.points.length > 0 && (
        <div class="text-xs text-theme-text-secondary mt-2 leading-relaxed">
          {describeCorrelation(props.data)}
          <span class="opacity-60"> ({props.data.points.length} points)</span>
        </div>
      )}
    </div>
  );
};

export default CorrelationChart;
