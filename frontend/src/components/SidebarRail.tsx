import { Component, For, Show } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { setSidebarCollapsed, requestExpandSection } from "./sidebarLayout";
import { getActiveSectionIds, ActiveSectionFilters, SidebarSectionId, SECTION_ICONS } from "./Sidebar";

interface RailItem {
  id: SidebarSectionId;
  label: string;
}

const ITEMS: RailItem[] = [
  { id: "search",         label: "Search" },
  { id: "object-type",    label: "Object Type" },
  { id: "date-range",     label: "Date Range" },
  { id: "filters",        label: "Filters" },
  { id: "equipment",      label: "Equipment" },
  { id: "metrics",        label: "Metrics Quality" },
  { id: "fits-query",     label: "FITS Header Query" },
  { id: "custom-columns", label: "Custom Columns" },
];

const SidebarRail: Component = () => {
  const { filters, resetFilters } = useDashboardFilters();
  const { customColumns } = useSettingsContext();

  const activeIds = () => getActiveSectionIds(filters() as unknown as ActiveSectionFilters);

  const visibleItems = () =>
    ITEMS.filter((it) => it.id !== "custom-columns" || (customColumns() ?? []).length > 0);

  const onItemClick = (id: SidebarSectionId) => {
    setSidebarCollapsed(false);
    // Wait one frame so the width transition begins before the section scrolls.
    requestAnimationFrame(() => requestExpandSection(id));
  };

  return (
    <div class="h-full flex flex-col items-center py-3 gap-1">
      <button
        onClick={() => setSidebarCollapsed(false)}
        class="p-2 text-theme-text-tertiary hover:text-theme-text-primary transition-colors cursor-pointer"
        aria-label="Expand sidebar"
        title="Expand sidebar"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
      <div class="w-full border-t border-theme-border-em my-1" />
      <For each={visibleItems()}>
        {(item, i) => (
          <button
            onClick={() => onItemClick(item.id)}
            title={item.label}
            aria-label={item.label}
            class="relative p-2 rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:bg-theme-elevated transition-colors cursor-pointer sidebar-rail-icon"
            classList={{
              "text-theme-accent": activeIds().has(item.id),
              "text-theme-text-tertiary": !activeIds().has(item.id),
            }}
            style={{ "--i": String(i()) }}
          >
            {SECTION_ICONS[item.id]()}
            {activeIds().has(item.id) && (
              <span class="absolute top-1 right-1 w-2 h-2 rounded-full bg-theme-accent" />
            )}
          </button>
        )}
      </For>
      <Show when={activeIds().size > 0}>
        <div class="mt-auto w-full border-t border-theme-border-em my-1" />
        <button
          onClick={resetFilters}
          title="Reset Filters"
          aria-label="Reset Filters"
          class="p-2 rounded-[var(--radius-sm)] text-theme-text-tertiary hover:text-theme-text-primary hover:bg-theme-elevated transition-colors cursor-pointer"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="1 4 1 10 7 10" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
          </svg>
        </button>
      </Show>
    </div>
  );
};

export default SidebarRail;
