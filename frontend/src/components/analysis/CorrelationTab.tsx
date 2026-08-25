import { Component, createSignal, createEffect, Show } from "solid-js";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { queryKeys } from "../../api/queryKeys";
import type { SharedFilters } from "../../pages/AnalysisPage";
// CorrelationResponse is the hand-written definition in `../../api/types`
// (`CorrelationPoint.target_id` is `string | null`, no `undefined`) for the
// cast below -- the generated schema types `target_id` as
// `string | null | undefined` because the field is optional in the OpenAPI
// schema (a real backend/OpenAPI schema gap, not a runtime difference; the
// field is always present in the actual response). Sole consumer is
// `CorrelationChart`, which imports this same type -- cast at this
// boundary. Same precedent as `DashboardFilterProvider.tsx`'s
// `TargetAggregationResponse` cast.
import type { CorrelationResponse } from "../../api/types";
import CorrelationChart from "./CorrelationChart";
import StatsCard from "./StatsCard";
import { metricOptions, metricLabel, METRIC_UNITS, PHD2_X_METRICS, PHD2_METRIC_NOTE } from "../../utils/metricLabels";

const X_OPTIONS = metricOptions([
  "humidity", "wind_speed", "ambient_temp", "dew_point", "pressure",
  "cloud_cover", "sky_quality", "focuser_temp", "airmass", "sensor_temp",
]);

// Rendered as a separate optgroup; the backend accepts these for correlation only.
const PHD2_X_OPTIONS = metricOptions(PHD2_X_METRICS);

const Y_OPTIONS = metricOptions([
  "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
  "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]);

const PRESETS = [
  { label: "Humidity vs HFR", x: "humidity", y: "hfr" },
  { label: "Airmass vs FWHM", x: "airmass", y: "fwhm" },
  { label: "Wind vs Guiding", x: "wind_speed", y: "guiding_rms" },
  { label: "Temp vs Eccentricity", x: "ambient_temp", y: "eccentricity" },
  { label: "Sky Quality vs Stars", x: "sky_quality", y: "detected_stars" },
  { label: "Guiding vs FWHM", x: "phd2_rms_total", y: "fwhm" },
];

interface Props {
  active: boolean;
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

  // Gate the fetch on tab visibility: while the tab is hidden the query is
  // disabled so no request fires until the tab is revealed.
  const params = () => ({
    x_metric: customX(),
    y_metric: customY(),
    telescope: props.filters.telescope,
    camera: props.filters.camera,
    filter_used: props.filters.filterUsed,
    granularity: props.filters.granularity,
    date_from: props.filters.dateFrom,
    date_to: props.filters.dateTo,
  });

  const dataQuery = useQuery(() => ({
    queryKey: queryKeys.correlation(params()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient.GET("/api/analysis/correlation", { params: { query: params() }, signal }).then(unwrap),
    enabled: props.active,
    // Retain the last successfully-resolved value across a refetch (matching
    // the old createResource's `.latest` behavior) so the chart doesn't flash
    // empty while a filter-driven refetch is in flight.
    placeholderData: keepPreviousData,
  }));

  const filteredData = () => {
    const d = dataQuery.data;
    if (!d || !hideOutliers()) return d;
    const pts = d.points.filter((p) => !p.outlier);
    return { ...d, points: pts };
  };

  // Show a note only when the response reports that its point set was sampled.
  // Read defensively so the note stays hidden until the backend supplies the
  // total/sampled counts.
  const samplingNote = (): string | null => {
    const d = dataQuery.data as (typeof dataQuery.data & { total?: number; sampled?: number }) | undefined;
    if (!d) return null;
    const total = d.total_count ?? d.total;
    const sampled = d.sampled_count ?? d.sampled;
    if (typeof total === "number" && typeof sampled === "number" && sampled < total) {
      return `Showing ${sampled.toLocaleString()} of ${total.toLocaleString()} frames (sampled for display; trend and statistics use all frames)`;
    }
    return null;
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
          <optgroup label="Guiding (PHD2)">
            {PHD2_X_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </optgroup>
        </select>
        <label class="text-sm text-theme-text-secondary">Y Axis:</label>
        <select class={selectClass} value={customY()} onChange={(e) => setCustomY(e.currentTarget.value)}>
          {Y_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
        </select>
        <button class={toggleClass(hideOutliers())} onClick={() => setHideOutliers(!hideOutliers())}>
          {hideOutliers() ? "Show Outliers" : "Hide Outliers"}
        </button>
      </div>

      <Show when={customX().startsWith("phd2_")}>
        <p class="text-xs text-theme-text-tertiary mb-2">{PHD2_METRIC_NOTE}</p>
      </Show>

      <Show when={samplingNote()}>
        <p class="text-xs text-theme-text-tertiary mb-2">{samplingNote()}</p>
      </Show>

      <div style={{ height: "500px" }} class="relative">
        <CorrelationChart data={filteredData() as CorrelationResponse | undefined} loading={dataQuery.isFetching} />
      </div>

      {/* Stats cards */}
      <Show when={dataQuery.data?.x_stats && dataQuery.data?.y_stats}>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">
          <StatsCard stats={dataQuery.data!.x_stats!} label={`X: ${metricLabel(customX())}`} unit={METRIC_UNITS[customX()]} />
          <StatsCard stats={dataQuery.data!.y_stats!} label={`Y: ${Y_OPTIONS.find((o) => o.value === customY())?.label}`} unit={METRIC_UNITS[customY()]} />
        </div>
      </Show>
    </div>
  );
};

export default CorrelationTab;
