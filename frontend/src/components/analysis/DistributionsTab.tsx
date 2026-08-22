import { Component, createSignal, Show } from "solid-js";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { queryKeys } from "../../api/queryKeys";
import type { SharedFilters } from "../../pages/AnalysisPage";
import HistogramChart from "./HistogramChart";
import BoxPlotChart from "./BoxPlotChart";
import StatsCard from "./StatsCard";
import { metricOptions, METRIC_UNITS, PIXEL_METRIC_NOTE } from "../../utils/metricLabels";

const ALL_METRICS = metricOptions([
  "humidity", "wind_speed", "ambient_temp", "dew_point", "pressure",
  "cloud_cover", "sky_quality", "focuser_temp", "airmass", "sensor_temp",
  "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
  "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]);

const Y_METRICS = metricOptions([
  "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
  "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]);

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

  // HFR is pixel-domain, so values mixed across optical trains are not
  // cross-comparable. Shown whenever the current scope can span more than one
  // train (no telescope/camera filter, or the box plot is explicitly grouped by
  // equipment). FWHM is always arcseconds and needs no such note.
  const crossTrainNote = (metric: string, groupedByEquipment: boolean): string | null => {
    if (metric !== "hfr") return null;
    const singleTrain = props.filters.telescope !== undefined && props.filters.camera !== undefined;
    if (singleTrain && !groupedByEquipment) return null;
    return `Values are per-train pixel-domain units, not comparable across optical trains. ${PIXEL_METRIC_NOTE}`;
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
        <Show when={crossTrainNote(histMetric(), false)}>
          <p class="text-xs text-theme-text-tertiary mb-2">{crossTrainNote(histMetric(), false)}</p>
        </Show>
        <div style={{ height: "450px" }} class="relative">
          <HistogramChart
            data={histQuery.data}
            loading={histQuery.isFetching}
            baselineMedian={histQuery.data?.stats?.median ?? null}
            metricLabel={ALL_METRICS.find((m) => m.value === histMetric())?.label}
          />
        </div>
        <Show when={histQuery.data?.stats}>
          <div class="mt-3">
            <StatsCard stats={histQuery.data!.stats} label={`${ALL_METRICS.find((m) => m.value === histMetric())?.label} (skewness: ${histQuery.data!.skewness.toFixed(2)})`} unit={METRIC_UNITS[histMetric()]} />
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
        <Show when={crossTrainNote(boxMetric(), groupBy() === "equipment")}>
          <p class="text-xs text-theme-text-tertiary mb-2">{crossTrainNote(boxMetric(), groupBy() === "equipment")}</p>
        </Show>
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
