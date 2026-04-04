import { Component, createSignal, createResource, Show, For } from "solid-js";
import { api } from "../../api/client";
import type { SharedFilters } from "../../pages/AnalysisPage";
import BoxPlotChart from "./BoxPlotChart";
import StatsCard from "./StatsCard";

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

interface Props {
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

  const dataKey = () =>
    canCompare() ? `compare-${mode()}-${metric()}-${groupA()}-${groupB()}-${props.filters.dateFrom}-${props.filters.dateTo}` : null;

  const [data] = createResource(dataKey, (key) => {
    if (!key) return undefined;
    return api.getCompare({
      metric: metric(),
      mode: mode(),
      group_a: groupA(),
      group_b: groupB(),
      date_from: props.filters.dateFrom,
      date_to: props.filters.dateTo,
    }).catch(() => undefined);
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

      <Show when={data() && canCompare()}>
        <div style={{ height: "200px" }} class="relative mb-4">
          <BoxPlotChart
            groups={[data()!.group_a.box, data()!.group_b.box]}
            loading={data.loading}
            metricLabel={Y_METRICS.find((m) => m.value === metric())?.label}
          />
        </div>

        <div class="text-sm text-theme-text-primary mb-3 font-medium">{data()!.verdict}</div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          <StatsCard stats={data()!.group_a.stats} label={data()!.group_a.name} />
          <StatsCard stats={data()!.group_b.stats} label={data()!.group_b.name} />
        </div>
      </Show>
    </div>
  );
};

export default CompareTab;
