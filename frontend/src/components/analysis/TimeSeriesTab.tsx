import { Component, createSignal, createMemo } from "solid-js";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { queryKeys } from "../../api/queryKeys";
import type { SharedFilters } from "../../pages/AnalysisPage";
// TimeSeriesResponse is the hand-written definition in `../../api/types`
// (`TimeSeriesPoint.target_name` is `string | null`, no `undefined`) for
// the cast below -- same schema-optionality gap as CorrelationTab's
// `CorrelationPoint.target_id` cast. Sole consumer is `TimeSeriesChart`,
// which imports this same type.
import type { TimeSeriesResponse } from "../../api/types";
import TimeSeriesChart from "./TimeSeriesChart";
import { MIN_GROUP, type MetricBaseline } from "../../utils/frameQuality";
import { metricOptions } from "../../utils/metricLabels";

// Higher-is-better metrics flip z-score polarity so "worse than baseline" stays positive.
const HIGHER_IS_BETTER = new Set(["detected_stars", "sky_quality"]);

// Robust median + MAD computed over the displayed values, matching the util's
// definition (MAD = median(|x - median|)). Returns null when too sparse or uniform.
function baselineFromValues(values: number[]): MetricBaseline | null {
  const xs = values.filter((v) => v != null && !Number.isNaN(v)).sort((a, b) => a - b);
  if (xs.length < MIN_GROUP) return null;
  const med = (arr: number[]): number => {
    const m = Math.floor(arr.length / 2);
    return arr.length % 2 ? arr[m] : (arr[m - 1] + arr[m]) / 2;
  };
  const median = med(xs);
  const mad = med(xs.map((v) => Math.abs(v - median)).sort((a, b) => a - b));
  if (mad === 0) return null;
  return { median, mad, n: xs.length };
}

const ALL_METRICS = metricOptions([
  "humidity", "wind_speed", "ambient_temp", "dew_point", "pressure",
  "cloud_cover", "sky_quality", "focuser_temp", "airmass", "sensor_temp",
  "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
  "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]);

interface Props {
  active: boolean;
  filters: SharedFilters;
}

const TimeSeriesTab: Component<Props> = (props) => {
  const [metric, setMetric] = createSignal("hfr");
  const [smoothing, setSmoothing] = createSignal<"raw" | "ma7" | "ma30">("raw");

  const params = () => ({
    metric: metric(),
    telescope: props.filters.telescope,
    camera: props.filters.camera,
    filter_used: props.filters.filterUsed,
    date_from: props.filters.dateFrom,
    date_to: props.filters.dateTo,
  });

  const dataQuery = useQuery(() => ({
    queryKey: queryKeys.timeseries(params()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient.GET("/api/analysis/timeseries", { params: { query: params() }, signal }).then(unwrap),
    enabled: props.active,
    placeholderData: keepPreviousData,
  }));

  // Baseline computed client-side over the displayed nightly-median points.
  const baseline = createMemo<MetricBaseline | null>(() => {
    const pts = dataQuery.data?.points;
    if (!pts || pts.length === 0) return null;
    return baselineFromValues(pts.map((p) => p.value));
  });

  const selectClass = "text-sm bg-theme-elevated border border-theme-border rounded px-2.5 py-1.5 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-sm px-3 py-1.5 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-base font-medium text-theme-text-primary mb-3">Time Series</h3>
      <div class="flex flex-wrap items-center gap-3 mb-4">
        <label class="text-sm text-theme-text-secondary">Metric:</label>
        <select class={selectClass} value={metric()} onChange={(e) => setMetric(e.currentTarget.value)}>
          {ALL_METRICS.map((o) => <option value={o.value}>{o.label}</option>)}
        </select>
        <div class="flex items-center gap-1">
          <button class={toggleClass(smoothing() === "raw")} onClick={() => setSmoothing("raw")}>Raw</button>
          <button class={toggleClass(smoothing() === "ma7")} onClick={() => setSmoothing("ma7")}>7-Night MA</button>
          <button class={toggleClass(smoothing() === "ma30")} onClick={() => setSmoothing("ma30")}>30-Night MA</button>
        </div>
      </div>
      <div style={{ height: "500px" }} class="relative">
        <TimeSeriesChart
          data={dataQuery.data as TimeSeriesResponse | undefined}
          loading={dataQuery.isFetching}
          smoothing={smoothing()}
          metricLabel={ALL_METRICS.find((m) => m.value === metric())?.label}
          baseline={baseline()}
          higherIsBetter={HIGHER_IS_BETTER.has(metric())}
        />
      </div>
    </div>
  );
};

export default TimeSeriesTab;
