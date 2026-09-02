import { Component, JSX, Show } from "solid-js";
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
  | "date-range"
  | "filters"
  | "equipment"
  | "metrics"
  | "fits-query"
  | "custom-columns";

// Single-path glyphs shared by the collapsed rail and the expanded section headers.
export const SECTION_ICONS: Record<SidebarSectionId, () => JSX.Element> = {
  "search": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  "object-type": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9 12 2" />
    </svg>
  ),
  "date-range": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  "filters": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="13.5" cy="6.5" r=".5" /><circle cx="17.5" cy="10.5" r=".5" /><circle cx="8.5" cy="7.5" r=".5" /><circle cx="6.5" cy="12.5" r=".5" />
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
    </svg>
  ),
  "equipment": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" /><line x1="12" y1="3" x2="12" y2="6" /><line x1="12" y1="18" x2="12" y2="21" />
    </svg>
  ),
  "metrics": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 12a9 9 0 0 1 18 0" /><line x1="12" y1="12" x2="16" y2="8" />
    </svg>
  ),
  "fits-query": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  "custom-columns": () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="18" rx="1" />
    </svg>
  ),
};

export interface ActiveSectionFilters {
  searchQuery?: string;
  selectedTargetId?: string | null;
  camera?: string;
  telescope?: string;
  opticalFilters: unknown[];
  objectTypes: unknown[];
  dateRange: { start?: unknown; end?: unknown };
  fitsQueries: unknown[];
  qualityFilters: Record<string, unknown>;
  metricFilters: Record<string, unknown>;
  customColumnFilters: unknown[];
}

export function getActiveSectionIds(f: ActiveSectionFilters): Set<SidebarSectionId> {
  const ids = new Set<SidebarSectionId>();
  if (f.searchQuery || f.selectedTargetId) ids.add("search");
  if (f.objectTypes.length > 0) ids.add("object-type");
  if (f.dateRange.start || f.dateRange.end) ids.add("date-range");
  if (Object.keys(f.qualityFilters).some((k) => (f.qualityFilters as Record<string, unknown>)[k] != null)) ids.add("filters");
  if (f.camera || f.telescope || f.opticalFilters.length > 0) ids.add("equipment");
  if (Object.keys(f.metricFilters).length > 0) ids.add("metrics");
  if (f.fitsQueries.length > 0) ids.add("fits-query");
  if (f.customColumnFilters.length > 0) ids.add("custom-columns");
  return ids;
}

const Sidebar: Component = () => {
  const { resetFilters, targetData, filters } = useDashboardFilters();
  const { customColumns } = useSettingsContext();

  const activeSections = () => getActiveSectionIds(filters() as unknown as ActiveSectionFilters);
  const hasActiveFilters = () => activeSections().size > 0;

  return (
    <aside class="w-full min-h-0 max-h-[calc(100vh-57px)] p-4 space-y-3 overflow-y-auto">
      <button
        onClick={toggleSidebarCollapsed}
        class="group flex items-center justify-between w-full -mt-1 cursor-pointer"
        aria-label="Collapse sidebar"
        title="Collapse sidebar"
      >
        <span class="text-label font-medium uppercase tracking-wider text-theme-text-tertiary group-hover:text-theme-text-primary transition-colors">Filters</span>
        <span class="p-1 text-theme-text-tertiary group-hover:text-theme-text-primary transition-colors">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </span>
      </button>
      <Show when={targetData()}>
        {(data) => (
          <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <span class="text-theme-text-secondary">
              Integration <span class="text-theme-text-primary font-semibold">{formatIntegration(data().aggregates.total_integration_seconds)}</span>
            </span>
            <span class="text-theme-text-secondary" title="Includes unresolved OBJECT-header groups alongside resolved targets; the Statistics page reports resolved targets only, so the two counts can differ by design.">
              Groups <span class="text-theme-text-primary font-semibold">{String(data().aggregates.target_count)}</span>
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
      <CollapsibleSection id="search" label="Search" icon={SECTION_ICONS["search"]} active={activeSections().has("search")}><SearchBar /></CollapsibleSection>
      <CollapsibleSection id="object-type" label="Object Type" icon={SECTION_ICONS["object-type"]} active={activeSections().has("object-type")}><ObjectTypeToggles /></CollapsibleSection>
      <CollapsibleSection id="date-range" label="Date Range" icon={SECTION_ICONS["date-range"]} active={activeSections().has("date-range")}><DateRangePicker /></CollapsibleSection>
      <CollapsibleSection id="filters" label="Filters" icon={SECTION_ICONS["filters"]} active={activeSections().has("filters")}><FilterToggles /></CollapsibleSection>
      <CollapsibleSection id="equipment" label="Equipment" icon={SECTION_ICONS["equipment"]} active={activeSections().has("equipment")}><HardwareSelects /></CollapsibleSection>
      <CollapsibleSection id="metrics" label="Metrics Quality" icon={SECTION_ICONS["metrics"]} active={activeSections().has("metrics")}><MetricFilters /></CollapsibleSection>
      <CollapsibleSection id="fits-query" label="FITS Header Query" icon={SECTION_ICONS["fits-query"]} active={activeSections().has("fits-query")}><FitsQueryBuilder /></CollapsibleSection>
      <Show when={(customColumns() ?? []).length > 0}>
        <CollapsibleSection id="custom-columns" label="Custom Columns" icon={SECTION_ICONS["custom-columns"]} active={activeSections().has("custom-columns")}><CustomColumnFilters /></CollapsibleSection>
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
