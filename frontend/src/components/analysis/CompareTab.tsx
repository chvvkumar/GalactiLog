import { Component, createSignal, Show, For } from "solid-js";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { queryKeys } from "../../api/queryKeys";
import type { SharedFilters } from "../../pages/AnalysisPage";
import BoxPlotChart from "./BoxPlotChart";
import StatsCard from "./StatsCard";
// CompareResponse extends the generated schema with the top-level arcsec-domain
// fields (`comparable`, `median_hfr_arcsec_a/_b`) that are optional until the
// backend ships them; cast at the fetch boundary, same precedent as CorrelationTab.
import type { CompareResponse } from "../../api/types";
import { metricOptions, METRIC_UNITS } from "../../utils/metricLabels";
import { formatArcsec } from "../../utils/format";

const Y_METRICS = metricOptions([
  "hfr", "fwhm", "eccentricity", "guiding_rms", "guiding_rms_ra",
  "guiding_rms_dec", "detected_stars", "adu_mean", "adu_median", "adu_stdev",
]);

interface Props {
  active: boolean;
  filters: SharedFilters;
  combos: Array<{ telescope: string; camera: string; label: string; grouped: boolean }>;
  availableFilters: string[];
}

const CompareTab: Component<Props> = (props) => {
  const [mode, setMode] = createSignal<"equipment" | "filter">("equipment");
  const [metric, setMetric] = createSignal("hfr");
  const [groupA, setGroupA] = createSignal("");
  const [groupB, setGroupB] = createSignal("");

  const canCompare = () => groupA() !== "" && groupB() !== "" && groupA() !== groupB();

  const params = () => ({
    metric: metric(),
    mode: mode(),
    group_a: groupA(),
    group_b: groupB(),
    date_from: props.filters.dateFrom,
    date_to: props.filters.dateTo,
  });

  const dataQuery = useQuery(() => ({
    queryKey: queryKeys.compare(params()),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient.GET("/api/analysis/compare", { params: { query: params() }, signal }).then(unwrap) as Promise<CompareResponse>,
    enabled: props.active && canCompare(),
    placeholderData: keepPreviousData,
  }));

  // When the backend flags the two sides as different optical trains for a
  // pixel-domain metric, the % improvement verdict is meaningless: suppress it
  // and either fall back to the arcsec medians (cross-train comparable) or say
  // why no comparison is shown.
  const crossTrainVerdict = (): string | null => {
    const d = dataQuery.data;
    if (!d || d.comparable !== false) return null;
    const a = d.median_hfr_arcsec_a;
    const b = d.median_hfr_arcsec_b;
    if (a != null && b != null) {
      return `Different optical trains: pixel HFR values are not directly comparable. Comparing in arcseconds instead: ${d.group_a.name} median ${formatArcsec(a)} vs ${d.group_b.name} median ${formatArcsec(b)}.`;
    }
    return `Different optical trains: pixel HFR is not comparable between these groups, and arcsecond data is unavailable (plate scale unknown). No improvement figure is shown.`;
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
      <h3 class="text-base font-medium text-theme-text-primary mb-3">Compare</h3>

      <div class="flex flex-wrap items-center gap-3 mb-4">
        <div class="flex items-center gap-1">
          <button class={toggleClass(mode() === "equipment")} onClick={() => { setMode("equipment"); setGroupA(""); setGroupB(""); }}>Equipment</button>
          <button class={toggleClass(mode() === "filter")} onClick={() => { setMode("filter"); setGroupA(""); setGroupB(""); }}>Filter</button>
        </div>
        <label class="text-sm text-theme-text-secondary">Metric:</label>
        <select class={selectClass} value={metric()} onChange={(e) => setMetric(e.currentTarget.value)}>
          {Y_METRICS.map((o) => <option value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div class="flex flex-wrap items-center gap-3 mb-4">
        <Show when={mode() === "equipment"}>
          <label class="text-sm text-theme-text-secondary">Group A:</label>
          <select class={selectClass} value={groupA()} onChange={(e) => setGroupA(e.currentTarget.value)}>
            <option value="">Select...</option>
            <For each={props.combos}>
              {(c) => <option value={`${c.telescope}|||${c.camera}`}>{c.label}{c.grouped ? " \u29C9" : ""}</option>}
            </For>
          </select>
          <label class="text-sm text-theme-text-secondary">Group B:</label>
          <select class={selectClass} value={groupB()} onChange={(e) => setGroupB(e.currentTarget.value)}>
            <option value="">Select...</option>
            <For each={props.combos}>
              {(c) => <option value={`${c.telescope}|||${c.camera}`}>{c.label}{c.grouped ? " \u29C9" : ""}</option>}
            </For>
          </select>
        </Show>

        <Show when={mode() === "filter"}>
          <label class="text-sm text-theme-text-secondary">Filter A:</label>
          <select class={selectClass} value={groupA()} onChange={(e) => setGroupA(e.currentTarget.value)}>
            <option value="">Select...</option>
            <For each={props.availableFilters}>
              {(f) => <option value={f}>{f}</option>}
            </For>
          </select>
          <label class="text-sm text-theme-text-secondary">Filter B:</label>
          <select class={selectClass} value={groupB()} onChange={(e) => setGroupB(e.currentTarget.value)}>
            <option value="">Select...</option>
            <For each={props.availableFilters}>
              {(f) => <option value={f}>{f}</option>}
            </For>
          </select>
        </Show>
      </div>

      <Show when={!canCompare()}>
        <div class="text-sm text-theme-text-secondary py-8 text-center">
          Select two different groups to compare.
        </div>
      </Show>

      <Show when={dataQuery.data && canCompare()}>
        <div style={{ height: "200px" }} class="relative mb-4">
          <BoxPlotChart
            groups={[dataQuery.data!.group_a.box, dataQuery.data!.group_b.box]}
            loading={dataQuery.isFetching}
            metricLabel={Y_METRICS.find((m) => m.value === metric())?.label}
          />
        </div>

        <Show
          when={crossTrainVerdict()}
          fallback={<div class="text-sm text-theme-text-primary mb-3 font-medium">{dataQuery.data!.verdict}</div>}
        >
          <div class="text-sm text-theme-text-secondary mb-3">{crossTrainVerdict()}</div>
        </Show>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          <StatsCard stats={dataQuery.data!.group_a.stats} label={dataQuery.data!.group_a.name} unit={METRIC_UNITS[metric()]} />
          <StatsCard stats={dataQuery.data!.group_b.stats} label={dataQuery.data!.group_b.name} unit={METRIC_UNITS[metric()]} />
        </div>
      </Show>
    </div>
  );
};

export default CompareTab;
