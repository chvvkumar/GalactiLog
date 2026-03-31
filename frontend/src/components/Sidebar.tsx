import { Component, Show } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import CollapsibleSection from "./CollapsibleSection";
import SearchBar from "./SearchBar";
import ObjectTypeToggles from "./ObjectTypeToggles";
import DateRangePicker from "./DateRangePicker";
import FilterToggles from "./FilterToggles";
import HardwareSelects from "./HardwareSelects";
import QualityFilters from "./QualityFilters";
import MetricFilters from "./MetricFilters";
import FitsQueryBuilder from "./FitsQueryBuilder";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

const Sidebar: Component = () => {
  const { resetFilters, targetData, filters } = useDashboardFilters();

  const hasActiveFilters = () => {
    const f = filters();
    return !!(
      f.searchQuery ||
      f.camera ||
      f.telescope ||
      f.opticalFilters.length > 0 ||
      f.objectTypes.length > 0 ||
      f.dateRange.start ||
      f.dateRange.end ||
      f.fitsQueries.length > 0 ||
      Object.keys(f.qualityFilters).some((k) => (f.qualityFilters as Record<string, unknown>)[k] != null) ||
      Object.keys(f.metricFilters).length > 0
    );
  };

  return (
    <aside class="w-72 min-h-[calc(100vh-57px)] border-r border-theme-border p-4 space-y-6 overflow-y-auto">
      <Show when={targetData()}>
        {(data) => (
          <section class="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <span class="text-theme-text-secondary">
              Integration <span class="text-theme-text-primary font-semibold">{formatHours(data().aggregates.total_integration_seconds)}</span>
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
      <section><SearchBar /></section>
      <CollapsibleSection id="object-type" label="Object Type"><ObjectTypeToggles /></CollapsibleSection>
      <CollapsibleSection id="date-range" label="Date Range"><DateRangePicker /></CollapsibleSection>
      <CollapsibleSection id="filters" label="Filters"><FilterToggles /></CollapsibleSection>
      <CollapsibleSection id="equipment" label="Equipment"><HardwareSelects /></CollapsibleSection>
      <CollapsibleSection id="quality" label="Quality (HFR)"><QualityFilters /></CollapsibleSection>
      <CollapsibleSection id="metrics" label="Metrics"><MetricFilters /></CollapsibleSection>
      <CollapsibleSection id="fits-query" label="FITS Header Query"><FitsQueryBuilder /></CollapsibleSection>
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
