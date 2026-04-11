import { Component, For } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useSettingsContext } from "./SettingsProvider";
import { setSidebarCollapsed, requestExpandSection } from "./sidebarLayout";
import { getActiveSectionIds, ActiveSectionFilters, SidebarSectionId } from "./Sidebar";

interface RailItem {
  id: SidebarSectionId;
  label: string;
  icon: () => any;
}

// Icons are simple single-path glyphs chosen for legibility at 18px.
const ITEMS: RailItem[] = [
  { id: "search",         label: "Search",              icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )},
  { id: "object-type",    label: "Object Type",         icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9 12 2" />
    </svg>
  )},
  { id: "date-range",     label: "Date Range",          icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )},
  { id: "filters",        label: "Filters",             icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  )},
  { id: "equipment",      label: "Equipment",           icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" /><line x1="12" y1="3" x2="12" y2="6" /><line x1="12" y1="18" x2="12" y2="21" />
    </svg>
  )},
  { id: "metrics",        label: "Metrics",             icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 12a9 9 0 0 1 18 0" /><line x1="12" y1="12" x2="16" y2="8" />
    </svg>
  )},
  { id: "fits-query",     label: "FITS Header Query",   icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
    </svg>
  )},
  { id: "custom-columns", label: "Custom Columns",      icon: () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="18" rx="1" />
    </svg>
  )},
];

const SidebarRail: Component = () => {
  const { filters } = useDashboardFilters();
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
            class="relative p-2 rounded-[var(--radius-sm)] text-theme-text-tertiary hover:text-theme-text-primary hover:bg-theme-elevated transition-colors cursor-pointer sidebar-rail-icon"
            style={{ "--i": String(i()) }}
          >
            {item.icon()}
            {activeIds().has(item.id) && (
              <span class="absolute top-1 right-1 w-2 h-2 rounded-full bg-theme-accent" />
            )}
          </button>
        )}
      </For>
    </div>
  );
};

export default SidebarRail;
