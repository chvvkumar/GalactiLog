import { Component, Show } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { toggleSidebarCollapsed } from "./sidebarLayout";
import CollapsibleSection from "./CollapsibleSection";
import SearchBar from "./SearchBar";
import ObjectTypeToggles from "./ObjectTypeToggles";
import DateRangePicker from "./DateRangePicker";
import FilterToggles from "./FilterToggles";
import HardwareSelects from "./HardwareSelects";
import MetricFilters from "./MetricFilters";
import FitsQueryBuilder from "./FitsQueryBuilder";
import CustomColumnFilters from "./CustomColumnFilters";

import { formatIntegration } from "../utils/format";

export type SidebarSectionId =
  | "search"
  | "object-type"
  | "catalog"
  | "date-range"
  | "filters"
  | "equipment"
  | "metrics"
  | "fits-query"
  | "custom-columns";

export interface ActiveSectionFilters {
  searchQuery?: string;
  camera?: string;
  telescope?: string;
  opticalFilters: unknown[];
  objectTypes: unknown[];
  catalog?: string | null;
  dateRange: { start?: unknown; end?: unknown };
  fitsQueries: unknown[];
  qualityFilters: Record<string, unknown>;
  metricFilters: Record<string, unknown>;
  customColumnFilters: unknown[];
}

export function getActiveSectionIds(f: ActiveSectionFilters): Set<SidebarSectionId> {
  const ids = new Set<SidebarSectionId>();
  if (f.searchQuery) ids.add("search");
  if (f.objectTypes.length > 0) ids.add("object-type");
  if (f.catalog) ids.add("catalog");
  if (f.dateRange.start || f.dateRange.end) ids.add("date-range");
  if (Object.keys(f.qualityFilters).some((k) => (f.qualityFilters as Record<string, unknown>)[k] != null)) ids.add("filters");
  if (f.camera || f.telescope || f.opticalFilters.length > 0) ids.add("equipment");
  if (Object.keys(f.metricFilters).length > 0) ids.add("metrics");
  if (f.fitsQueries.length > 0) ids.add("fits-query");
  if (f.customColumnFilters.length > 0) ids.add("custom-columns");
  return ids;
}

const CATALOG_OPTIONS = ["Caldwell", "Herschel 400", "Arp", "Abell"] as const;

const Sidebar: Component = () => {
  const { resetFilters, targetData, filters, updateFilter } = useDashboardFilters();
  const { customColumns } = useSettingsContext();

  const hasActiveFilters = () => getActiveSectionIds(filters() as unknown as ActiveSectionFilters).size > 0;

  return (
    <aside class="w-full min-h-0 max-h-[calc(100vh-57px)] p-4 space-y-3 overflow-y-auto">
      <div class="flex items-center justify-between -mt-1">
        <span class="text-label font-medium uppercase tracking-wider text-theme-text-tertiary">Filters</span>
        <button
          onClick={toggleSidebarCollapsed}
          class="p-1 text-theme-text-tertiary hover:text-theme-text-primary transition-colors cursor-pointer"
          aria-label="Collapse sidebar"
          title="Collapse sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
      </div>
      <Show when={targetData()}>
        {(data) => (
          <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <span class="text-theme-text-secondary">
              Integration <span class="text-theme-text-primary font-semibold">{formatIntegration(data().aggregates.total_integration_seconds)}</span>
            </span>
            <span class="text-theme-text-secondary">
              Targets <span class="text-theme-text-primary font-semibold">{String(data().aggregates.target_count)}</span>
            </span>
            <span class="text-theme-text-secondary">
              Frames <span class="text-theme-text-primary font-semibold">{data().aggregates.total_frames.toLocaleString()}</span>
            </span>
            <Show when={hasActiveFilters()}>
              <span class="text-caption text-theme-text-tertiary italic">filtered</span>
            </Show>
          </section>
        )}
      </Show>
      <CollapsibleSection id="search" label="Search"><SearchBar /></CollapsibleSection>
      <CollapsibleSection id="object-type" label="Object Type"><ObjectTypeToggles /></CollapsibleSection>
      <CollapsibleSection id="catalog" label="Catalog">
        <div class="flex gap-1.5 flex-wrap">
          {CATALOG_OPTIONS.map((cat) => (
            <button
              onClick={() => updateFilter("catalog", filters().catalog === cat ? null : cat)}
              class={`px-1.5 h-6 rounded text-caption font-bold flex items-center justify-center transition-all ${
                filters().catalog === cat
                  ? "ring-1 ring-theme-accent bg-theme-elevated text-theme-accent brightness-110"
                  : "ring-1 ring-transparent bg-theme-elevated text-theme-text-secondary hover:brightness-110"
              }`}
              title={cat}
            >
              {cat}
            </button>
          ))}
        </div>
      </CollapsibleSection>
      <CollapsibleSection id="date-range" label="Date Range"><DateRangePicker /></CollapsibleSection>
      <CollapsibleSection id="filters" label="Filters"><FilterToggles /></CollapsibleSection>
      <CollapsibleSection id="equipment" label="Equipment"><HardwareSelects /></CollapsibleSection>
      <CollapsibleSection id="metrics" label="Metrics"><MetricFilters /></CollapsibleSection>
      <CollapsibleSection id="fits-query" label="FITS Header Query"><FitsQueryBuilder /></CollapsibleSection>
      <Show when={(customColumns() ?? []).length > 0}>
        <CollapsibleSection id="custom-columns" label="Custom Columns"><CustomColumnFilters /></CollapsibleSection>
      </Show>
      <button
        onClick={resetFilters}
        class="w-full py-2 text-xs text-theme-text-secondary hover:text-theme-text-primary bg-theme-elevated hover:bg-theme-border-em rounded-[var(--radius-sm)] transition-colors"
      >
        Reset Filters
      </button>
    </aside>
  );
};

export default Sidebar;
