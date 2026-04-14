import { Component, createSignal, createResource, createEffect, Show } from "solid-js";
import { api } from "../../api/client";
import type { SharedFilters } from "../../pages/AnalysisPage";
import CorrelationChart from "./CorrelationChart";
import StatsCard from "./StatsCard";

const X_OPTIONS = [
  { value: "humidity", label: "Humidity" },
  { value: "wind_speed", label: "Wind Speed" },
  { value: "ambient_temp", label: "Ambient Temp" },
  { value: "dew_point", label: "Dew Point" },
  { value: "pressure", label: "Pressure" },
  { value: "cloud_cover", label: "Cloud Cover" },
  { value: "sky_quality", label: "Sky Quality" },
  { value: "focuser_temp", label: "Focuser Temp" },
  { value: "airmass", label: "Airmass" },
  { value: "sensor_temp", label: "Sensor Temp" },
];

const Y_OPTIONS = [
  { value: "hfr", label: "HFR" },
  { value: "fwhm", label: "FWHM" },
  { value: "eccentricity", label: "Eccentricity" },
  { value: "guiding_rms", label: "Guiding RMS" },
  { value: "guiding_rms_ra", label: "Guiding RA RMS" },
  { value: "guiding_rms_dec", label: "Guiding DEC RMS" },
  { value: "detected_stars", label: "Detected Stars" },
  { value: "adu_mean", label: "ADU Mean" },
  { value: "adu_median", label: "ADU Median" },
  { value: "adu_stdev", label: "ADU StDev" },
];

const PRESETS = [
  { label: "Humidity vs HFR", x: "humidity", y: "hfr" },
  { label: "Airmass vs FWHM", x: "airmass", y: "fwhm" },
  { label: "Wind vs Guiding", x: "wind_speed", y: "guiding_rms" },
  { label: "Temp vs Eccentricity", x: "ambient_temp", y: "eccentricity" },
  { label: "Sky Quality vs Stars", x: "sky_quality", y: "detected_stars" },
];

interface Props {
  filters: SharedFilters;
  navX?: string;
  navY?: string;
  onNavConsumed?: () => void;
}

const CorrelationTab: Component<Props> = (props) => {
  const [customX, setCustomX] = createSignal("humidity");
  const [customY, setCustomY] = createSignal("hfr");
  const [hideOutliers, setHideOutliers] = createSignal(false);

  // Handle navigation from matrix tab
  createEffect(() => {
    if (props.navX && props.navY) {
      setCustomX(props.navX);
      setCustomY(props.navY);
      props.onNavConsumed?.();
    }
  });

  const chartKey = () =>
    `${props.filters.telescope}-${props.filters.camera}-${props.filters.filterUsed}-${props.filters.granularity}-${props.filters.dateFrom}-${props.filters.dateTo}-${customX()}-${customY()}`;

  const [data] = createResource(chartKey, () =>
    api.getCorrelation({
      x_metric: customX(),
      y_metric: customY(),
      telescope: props.filters.telescope,
      camera: props.filters.camera,
      filter_used: props.filters.filterUsed,
      granularity: props.filters.granularity,
      date_from: props.filters.dateFrom,
      date_to: props.filters.dateTo,
    })
  );

  const filteredData = () => {
    const d = data();
    if (!d || !hideOutliers()) return d;
    const pts = d.points.filter((p) => !p.outlier);
    return { ...d, points: pts };
  };

  const exportCsv = () => {
    const d = filteredData();
    if (!d) return;
    const header = "x,y,date,target_name,outlier";
    const rows = d.points.map((p) => {
      const name = p.target_id ? (d.target_names?.[p.target_id] ?? "") : "";
      return `${p.x},${p.y},${p.date},"${name}",${p.outlier}`;
    });
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `correlation_${customX()}_vs_${customY()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const selectClass = "text-sm bg-theme-elevated border border-theme-border rounded px-2.5 py-1.5 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-sm px-3 py-1.5 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-base font-medium text-theme-text-primary">Correlation Explorer</h3>
        <button onClick={exportCsv} class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors" title="Export CSV">
          Export CSV
        </button>
      </div>

      {/* Presets */}
      <div class="flex flex-wrap gap-1.5 mb-3">
        {PRESETS.map((p) => (
          <button
            class={`text-xs px-2.5 py-1 rounded-[var(--radius-sm)] border transition-colors ${
              customX() === p.x && customY() === p.y
                ? "border-theme-accent text-theme-accent bg-theme-accent/10"
                : "border-theme-border text-theme-text-secondary hover:text-theme-text-primary"
            }`}
            onClick={() => { setCustomX(p.x); setCustomY(p.y); }}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Controls */}
      <div class="flex flex-wrap items-center gap-3 mb-4">
        <label class="text-sm text-theme-text-secondary">X Axis:</label>
        <select class={selectClass} value={customX()} onChange={(e) => setCustomX(e.currentTarget.value)}>
          {X_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
        </select>
        <label class="text-sm text-theme-text-secondary">Y Axis:</label>
        <select class={selectClass} value={customY()} onChange={(e) => setCustomY(e.currentTarget.value)}>
          {Y_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
        </select>
        <button class={toggleClass(hideOutliers())} onClick={() => setHideOutliers(!hideOutliers())}>
          {hideOutliers() ? "Show Outliers" : "Hide Outliers"}
        </button>
      </div>

      <div style={{ height: "500px" }} class="relative">
        <CorrelationChart data={filteredData()} loading={data.loading} />
      </div>

      {/* Stats cards */}
      <Show when={data()?.x_stats && data()?.y_stats}>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">
          <StatsCard stats={data()!.x_stats!} label={`X: ${X_OPTIONS.find((o) => o.value === customX())?.label}`} />
          <StatsCard stats={data()!.y_stats!} label={`Y: ${Y_OPTIONS.find((o) => o.value === customY())?.label}`} />
        </div>
      </Show>
    </div>
  );
};

export default CorrelationTab;
