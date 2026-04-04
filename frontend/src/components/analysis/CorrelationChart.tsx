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
import { chartFontSize } from "../../utils/chartConfig";

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
          ? "rgba(100, 180, 255, 0.85)"
          : "rgba(100, 180, 255, 0.55)",
        borderColor: isSession
          ? "rgba(130, 200, 255, 1)"
          : "rgba(130, 200, 255, 0.7)",
        borderWidth: 1,
        pointRadius: isSession ? 6 : 4,
        pointHoverRadius: isSession ? 8 : 6,
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
        borderColor: "rgba(255, 180, 80, 0.9)",
        borderWidth: 2.5,
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
            title: { display: true, text: METRIC_LABELS[x_metric] || x_metric, color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
            ticks: { color: "rgba(200, 210, 220, 0.7)", font: { size: chartFontSize.tick() } },
            grid: { color: "rgba(200, 210, 220, 0.12)" },
          },
          y: {
            title: { display: true, text: METRIC_LABELS[y_metric] || y_metric, color: "rgba(200, 210, 220, 0.8)", font: { size: chartFontSize.tooltipTitle() } },
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
    <>
      {props.title && <h3 class="text-sm font-medium text-theme-text-primary mb-2">{props.title}</h3>}
      <div class="relative w-full h-full">
        {props.loading && !props.data && (
          <div class="absolute inset-0 flex items-center justify-center text-sm text-theme-text-secondary">
            Loading...
          </div>
        )}
        <canvas ref={canvasRef} />
      </div>
      {props.data && props.data.points.length > 0 && (
        <div class="text-sm text-theme-text-secondary mt-3 leading-relaxed">
          {describeCorrelation(props.data)}
          <span class="opacity-60"> ({props.data.points.length} points)</span>
        </div>
      )}
      <p class="text-xs text-theme-text-tertiary mt-3 opacity-50">
        Correlations show statistical associations, not causation. Many factors affect image quality simultaneously.
      </p>
    </>
  );
};

export default CorrelationChart;
