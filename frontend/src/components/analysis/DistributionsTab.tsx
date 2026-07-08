import { Component, createSignal, Show } from "solid-js";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { queryKeys } from "../../api/queryKeys";
import type { SharedFilters } from "../../pages/AnalysisPage";
import HistogramChart from "./HistogramChart";
import BoxPlotChart from "./BoxPlotChart";
import StatsCard from "./StatsCard";

const ALL_METRICS = [
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

const Y_METRICS = [
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

const GROUP_OPTIONS = [
  { value: "filter", label: "By Filter" },
  { value: "equipment", label: "By Equipment" },
  { value: "month", label: "By Month" },
  { value: "target", label: "By Target" },
] as const;

interface Props {
  active: boolean;
  filters: SharedFilters;
}

const DistributionsTab: Component<Props> = (props) => {
  const [mode, setMode] = createSignal<"histogram" | "boxplot">("histogram");
  const [histMetric, setHistMetric] = createSignal("hfr");
  const [boxMetric, setBoxMetric] = createSignal("hfr");
  const [groupBy, setGroupBy] = createSignal<"filter" | "equipment" | "month" | "target">("filter");

  const histParams = () => ({
    metric: histMetric(),
    telescope: props.filters.telescope,
    camera: props.filters.camera,
    filter_used: props.filters.filterUsed,
    granularity: props.filters.granularity,
    date_from: props.filters.dateFrom,
    date_to: props.filters.dateTo,
  });

  const histQuery = useQuery(() => ({
    queryKey: queryKeys.distribution(histParams()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient.GET("/api/analysis/distribution", { params: { query: histParams() }, signal }).then(unwrap),
    enabled: props.active,
    placeholderData: keepPreviousData,
  }));

  const boxParams = () => ({
    metric: boxMetric(),
    group_by: groupBy(),
    telescope: props.filters.telescope,
    camera: props.filters.camera,
    filter_used: props.filters.filterUsed,
    date_from: props.filters.dateFrom,
    date_to: props.filters.dateTo,
  });

  const boxQuery = useQuery(() => ({
    queryKey: queryKeys.boxplot(boxParams()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient.GET("/api/analysis/boxplot", { params: { query: boxParams() }, signal }).then(unwrap),
    enabled: props.active,
    placeholderData: keepPreviousData,
  }));

  const selectClass = "text-sm bg-theme-elevated border border-theme-border rounded px-2.5 py-1.5 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-sm px-3 py-1.5 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <div class="flex items-center gap-3 mb-4">
        <h3 class="text-base font-medium text-theme-text-primary">Distributions</h3>
        <div class="flex items-center gap-1">
          <button class={toggleClass(mode() === "histogram")} onClick={() => setMode("histogram")}>Histogram</button>
          <button class={toggleClass(mode() === "boxplot")} onClick={() => setMode("boxplot")}>Box Plot</button>
        </div>
      </div>

      <div style={{ display: mode() === "histogram" ? undefined : "none" }}>
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <label class="text-sm text-theme-text-secondary">Metric:</label>
          <select class={selectClass} value={histMetric()} onChange={(e) => setHistMetric(e.currentTarget.value)}>
            {ALL_METRICS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ height: "450px" }} class="relative">
          <HistogramChart
            data={histQuery.data}
            loading={histQuery.isFetching}
            baselineMedian={histQuery.data?.stats?.median ?? null}
          />
        </div>
        <Show when={histQuery.data?.stats}>
          <div class="mt-3">
            <StatsCard stats={histQuery.data!.stats} label={`${ALL_METRICS.find((m) => m.value === histMetric())?.label} (skewness: ${histQuery.data!.skewness.toFixed(2)})`} />
          </div>
        </Show>
      </div>

      <div style={{ display: mode() === "boxplot" ? undefined : "none" }}>
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <label class="text-sm text-theme-text-secondary">Metric:</label>
          <select class={selectClass} value={boxMetric()} onChange={(e) => setBoxMetric(e.currentTarget.value)}>
            {Y_METRICS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
          <label class="text-sm text-theme-text-secondary">Group by:</label>
          <select class={selectClass} value={groupBy()} onChange={(e) => setGroupBy(e.currentTarget.value as any)}>
            {GROUP_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ height: `${Math.max(200, (boxQuery.data?.groups?.length || 3) * 60)}px` }} class="relative">
          <BoxPlotChart
            groups={boxQuery.data?.groups || []}
            loading={boxQuery.isFetching}
            metricLabel={Y_METRICS.find((m) => m.value === boxMetric())?.label}
          />
        </div>
      </div>
    </div>
  );
};

export default DistributionsTab;
