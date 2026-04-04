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
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Analysis</h1>
      {/* Shared Controls */}
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

      {/* Tab Bar */}
      <div class="flex flex-wrap gap-1">
        <For each={TABS}>
          {(tab) => (
            <button class={tabClass(activeTab() === tab.id)} onClick={() => setActiveTab(tab.id)}>
              {tab.label}
            </button>
          )}
        </For>
      </div>

      {/* Tab Content */}
      <Show when={activeTab() === "correlation"}>
        <CorrelationTab filters={shared()} navX={navX()} navY={navY()} onNavConsumed={() => { setNavX(undefined); setNavY(undefined); }} />
      </Show>
      <Show when={activeTab() === "distributions"}>
        <DistributionsTab filters={shared()} />
      </Show>
      <Show when={activeTab() === "timeseries"}>
        <TimeSeriesTab filters={shared()} />
      </Show>
      <Show when={activeTab() === "matrix"}>
        <MatrixTab filters={shared()} />
      </Show>
      <Show when={activeTab() === "compare"}>
        <CompareTab filters={shared()} combos={combos()} availableFilters={filters() || []} />
      </Show>
    </div>
  );
};

export default AnalysisPage;
