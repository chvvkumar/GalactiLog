import { Component, createSignal, createResource, createEffect, For, Show, onMount, onCleanup } from "solid-js";
import { api } from "../api/client";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import { useStats } from "../store/stats";
import CorrelationTab from "../components/analysis/CorrelationTab";
import DistributionsTab from "../components/analysis/DistributionsTab";
import TimeSeriesTab from "../components/analysis/TimeSeriesTab";
import MatrixTab from "../components/analysis/MatrixTab";
import CompareTab from "../components/analysis/CompareTab";
import HelpPopover from "../components/HelpPopover";

const TABS = [
  { id: "correlation", label: "Correlation" },
  { id: "distributions", label: "Distributions" },
  { id: "timeseries", label: "Time Series" },
  { id: "matrix", label: "Matrix" },
  { id: "compare", label: "Compare" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export interface SharedFilters {
  telescope: string | undefined;
  camera: string | undefined;
  filterUsed: string | undefined;
  granularity: "frame" | "session";
  dateFrom: string | undefined;
  dateTo: string | undefined;
}

const AnalysisPage: Component = () => {
  const { stats } = useStats();
  const ctx = useSettingsContext();
  const [activeTab, setActiveTab] = createSignal<TabId>("correlation");
  const [telescope, setTelescope] = createSignal<string | undefined>(undefined);
  const [camera, setCamera] = createSignal<string | undefined>(undefined);
  const [filterUsed, setFilterUsed] = createSignal<string | undefined>(undefined);
  const [granularity, setGranularity] = createSignal<"frame" | "session">("frame");
  const [dateFrom, setDateFrom] = createSignal<string | undefined>(undefined);
  const [dateTo, setDateTo] = createSignal<string | undefined>(undefined);

  // Navigation from matrix cell click
  const [navX, setNavX] = createSignal<string | undefined>(undefined);
  const [navY, setNavY] = createSignal<string | undefined>(undefined);

  const handleMatrixNav = (e: Event) => {
    const detail = (e as CustomEvent).detail;
    if (detail?.tab === "correlation") {
      setNavX(detail.x);
      setNavY(detail.y);
      setActiveTab("correlation");
    }
  };

  onMount(() => window.addEventListener("analysis-navigate", handleMatrixNav));
  onCleanup(() => window.removeEventListener("analysis-navigate", handleMatrixNav));

  const [filters] = createResource(() => api.getAnalysisFilters());

  const shared = (): SharedFilters => ({
    telescope: telescope(),
    camera: camera(),
    filterUsed: filterUsed(),
    granularity: granularity(),
    dateFrom: dateFrom(),
    dateTo: dateTo(),
  });

  const combos = () => {
    const s = stats();
    if (!s) return [];
    return s.equipment_performance.map((c) => ({
      telescope: c.telescope,
      camera: c.camera,
      label: `${c.telescope} + ${c.camera}`,
      grouped: c.grouped,
    }));
  };

  const equipmentValue = () => {
    const tel = telescope();
    const cam = camera();
    if (!tel && !cam) return "";
    return `${tel}|||${cam}`;
  };

  let equipSelectRef!: HTMLSelectElement;
  createEffect(() => {
    const v = equipmentValue();
    if (equipSelectRef) equipSelectRef.value = v;
  });

  const selectClass = "text-sm bg-theme-elevated border border-theme-border rounded px-2.5 py-1.5 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-sm px-3 py-1.5 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;
  const tabClass = (active: boolean) =>
    `px-3 sm:px-4 py-2 text-sm transition-colors duration-150 ${
      active
        ? "bg-theme-elevated text-theme-text-primary rounded-[var(--radius-sm)] font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover rounded-[var(--radius-sm)]"
    }`;

  return (
    <div class={`p-4 space-y-4 ${contentWidthClass(ctx.contentWidth())}`}>
      <div class="flex items-center gap-2">
        <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Analysis</h1>
        <HelpPopover>
          <p class="text-sm text-theme-text-secondary">
            Explore relationships and trends across your imaging data. Set scope once in Shared Filters, then switch between tabs to view the same data in different ways.
          </p>
          <ul class="list-disc list-inside space-y-1">
            <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Correlation</strong>: scatter plot of two metrics.</li>
            <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Distributions</strong>: histogram of one metric, optionally grouped.</li>
            <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Time Series</strong>: a metric plotted over time.</li>
            <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Matrix</strong>: heatmap of one metric across two categorical axes.</li>
            <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Compare</strong>: side-by-side distributions across groups.</li>
          </ul>
          <p class="text-sm text-theme-text-secondary">Each section has its own info icon with details and examples.</p>
        </HelpPopover>
      </div>
      <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
        <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
          <div class="flex items-center gap-2">
            <h2 class="text-sm font-semibold text-theme-text-primary">Shared Filters</h2>
            <HelpPopover>
              <p class="text-sm text-theme-text-secondary">
                Scope controls that apply to every tab on this page at the same time. Switching tabs preserves your selection.
              </p>
              <ul class="list-disc list-inside space-y-1">
                <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Equipment</strong>: telescope and camera combination.</li>
                <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Filter</strong>: restrict to a single optical filter (e.g. Ha, OIII, L).</li>
                <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Granularity</strong>: per frame uses each individual sub, per session aggregates by imaging session.</li>
                <li class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Date range</strong>: restrict by capture date.</li>
              </ul>
              <p class="text-sm text-theme-text-secondary">Example: pick your main scope, Ha filter, per session, last 12 months, then flip through tabs to see that slice every way.</p>
            </HelpPopover>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <select
              ref={equipSelectRef}
              class={selectClass}
              value={equipmentValue()}
              onChange={(e) => {
                const val = e.currentTarget.value;
                if (!val) {
                  setTelescope(undefined);
                  setCamera(undefined);
                } else {
                  const [t, c] = val.split("|||");
                  setTelescope(t);
                  setCamera(c);
                }
              }}
            >
              <option value="">All equipment</option>
              <For each={combos()}>
                {(c) => (
                  <option value={`${c.telescope}|||${c.camera}`}>{c.label}{c.grouped ? " \u29C9" : ""}</option>
                )}
              </For>
            </select>

            <select
              class={selectClass}
              value={filterUsed() || ""}
              onChange={(e) => setFilterUsed(e.currentTarget.value || undefined)}
            >
              <option value="">All filters</option>
              <For each={filters() || []}>
                {(f) => <option value={f}>{f}</option>}
              </For>
            </select>

            <div class="flex items-center gap-1">
              <button class={toggleClass(granularity() === "frame")} onClick={() => setGranularity("frame")}>
                Per Frame
              </button>
              <button class={toggleClass(granularity() === "session")} onClick={() => setGranularity("session")}>
                Per Session
              </button>
            </div>

            <div class="flex items-center gap-1.5 text-sm text-theme-text-secondary">
              <span>From</span>
              <input
                type="date"
                class={selectClass}
                value={dateFrom() || ""}
                onChange={(e) => setDateFrom(e.currentTarget.value || undefined)}
              />
              <span>To</span>
              <input
                type="date"
                class={selectClass}
                value={dateTo() || ""}
                onChange={(e) => setDateTo(e.currentTarget.value || undefined)}
              />
            </div>
          </div>

          <div class="flex flex-wrap gap-1">
            <For each={TABS}>
              {(tab) => (
                <button class={tabClass(activeTab() === tab.id)} onClick={() => setActiveTab(tab.id)}>
                  {tab.label}
                </button>
              )}
            </For>
          </div>
        </div>

        <Show when={activeTab() === "correlation"}>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-theme-text-primary">Correlation</h2>
              <HelpPopover>
                <p class="text-sm text-theme-text-secondary">
                  Scatter plot of any two numeric metrics across the filtered dataset. Use it to spot relationships between variables.
                </p>
                <ul class="list-disc list-inside space-y-1">
                  <li class="text-sm text-theme-text-secondary">Plot HFR against guide RMS to check whether seeing tracks guiding.</li>
                  <li class="text-sm text-theme-text-secondary">Plot star count against altitude to see how elevation affects detections.</li>
                </ul>
              </HelpPopover>
            </div>
            <CorrelationTab filters={shared()} navX={navX()} navY={navY()} onNavConsumed={() => { setNavX(undefined); setNavY(undefined); }} />
          </div>
        </Show>
        <Show when={activeTab() === "distributions"}>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-theme-text-primary">Distributions</h2>
              <HelpPopover>
                <p class="text-sm text-theme-text-secondary">
                  Histogram of a single metric with optional grouping. Reveals the spread, central tendency, and outliers in your data.
                </p>
                <ul class="list-disc list-inside space-y-1">
                  <li class="text-sm text-theme-text-secondary">HFR grouped by filter shows whether some filters consistently yield worse stars.</li>
                  <li class="text-sm text-theme-text-secondary">Exposure time distribution confirms how often you use each sub length.</li>
                </ul>
              </HelpPopover>
            </div>
            <DistributionsTab filters={shared()} />
          </div>
        </Show>
        <Show when={activeTab() === "timeseries"}>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-theme-text-primary">Time Series</h2>
              <HelpPopover>
                <p class="text-sm text-theme-text-secondary">
                  A metric plotted over time, either per frame or aggregated by session or night. Useful for spotting drift, degradation, and seasonal patterns.
                </p>
                <ul class="list-disc list-inside space-y-1">
                  <li class="text-sm text-theme-text-secondary">Camera temperature across a single night to verify cooling stability.</li>
                  <li class="text-sm text-theme-text-secondary">Median HFR per session across months to watch for focus or collimation drift.</li>
                </ul>
              </HelpPopover>
            </div>
            <TimeSeriesTab filters={shared()} />
          </div>
        </Show>
        <Show when={activeTab() === "matrix"}>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-theme-text-primary">Matrix</h2>
              <HelpPopover>
                <p class="text-sm text-theme-text-secondary">
                  Heatmap grid of one metric across two categorical axes. Good for spotting gaps in coverage and comparing aggregate values at a glance.
                </p>
                <ul class="list-disc list-inside space-y-1">
                  <li class="text-sm text-theme-text-secondary">Filter by target shows integration time per channel for each object.</li>
                  <li class="text-sm text-theme-text-secondary">Telescope by filter highlights which rigs have imaged which bands.</li>
                </ul>
                <p class="text-sm text-theme-text-secondary">Click a cell to jump to the Correlation tab pre-filtered to that combination.</p>
              </HelpPopover>
            </div>
            <MatrixTab filters={shared()} />
          </div>
        </Show>
        <Show when={activeTab() === "compare"}>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-semibold text-theme-text-primary">Compare</h2>
              <HelpPopover>
                <p class="text-sm text-theme-text-secondary">
                  Side-by-side comparison of a metric's distribution across two or more groups. Quantifies how one setup differs from another.
                </p>
                <ul class="list-disc list-inside space-y-1">
                  <li class="text-sm text-theme-text-secondary">Compare HFR between two telescopes on the same target to judge optical performance.</li>
                  <li class="text-sm text-theme-text-secondary">Compare eccentricity across filters to spot chromatic focus issues.</li>
                </ul>
              </HelpPopover>
            </div>
            <CompareTab filters={shared()} combos={combos()} availableFilters={filters() || []} />
          </div>
        </Show>
      </div>
    </div>
  );
};

export default AnalysisPage;
