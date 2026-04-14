import { Component, onMount, onCleanup } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import Sidebar from "../components/Sidebar";
import TargetFeed from "../components/TargetFeed";
import ScanFiltersOnboarding from "../components/ScanFiltersOnboarding";
import DashboardFilterProvider, { hasFilterParams, ALL_PARAM_KEYS } from "../components/DashboardFilterProvider";
import SidebarRail from "../components/SidebarRail";
import SidebarResizeHandle from "../components/SidebarResizeHandle";
import { sidebarWidth, sidebarCollapsed, resizing, RAIL_WIDTH } from "../components/sidebarLayout";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import { sidebarOpen, setSidebarOpen } from "../store/sidebar";
export { sidebarOpen, setSidebarOpen };

const SESSION_KEY = "dashboard_params";

const DashboardPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { contentWidth } = useSettingsContext();

  onMount(() => {
    if (!hasFilterParams(searchParams)) {
      try {
        const saved = sessionStorage.getItem(SESSION_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as Record<string, string>;
          setSearchParams(parsed, { replace: true });
        }
      } catch { /* ignore */ }
    }
  });

  onCleanup(() => {
    const toSave: Record<string, string> = {};
    for (const key of ALL_PARAM_KEYS) {
      const val = searchParams[key];
      if (val !== undefined && val !== "") {
        toSave[key] = String(val);
      }
    }
    try {
      if (Object.keys(toSave).length > 0) {
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(toSave));
      }
    } catch { /* ignore */ }
  });

  return (
    <DashboardFilterProvider>
      <div class="flex" data-layout="sidebar-main">
        {/* Desktop sidebar */}
        <div
          class="hidden lg:flex relative border-r border-theme-border-em h-[calc(100vh-57px)] sticky top-[57px] self-start shrink-0"
          classList={{ "transition-[width] duration-[240ms] ease-[cubic-bezier(0.22,0.61,0.36,1)]": !resizing() }}
          style={{ width: `${sidebarCollapsed() ? RAIL_WIDTH : sidebarWidth()}px` }}
        >
          {sidebarCollapsed() ? <SidebarRail /> : <Sidebar />}
          {!sidebarCollapsed() && <SidebarResizeHandle />}
        </div>

        {/* Mobile drawer backdrop */}
        <div
          class={`fixed inset-0 bg-black/50 z-40 lg:hidden transition-opacity ${sidebarOpen() ? "opacity-100" : "opacity-0 pointer-events-none"}`}
          onClick={() => setSidebarOpen(false)}
        />

        {/* Mobile drawer */}
        <div class={`fixed top-0 left-0 h-full w-72 z-50 bg-theme-base transform transition-transform lg:hidden ${sidebarOpen() ? "translate-x-0" : "-translate-x-full"}`}>
          <div class="flex items-center justify-between p-4 border-b border-theme-border">
            <span class="text-sm font-medium text-theme-text-primary">Filters</span>
            <button
              onClick={() => setSidebarOpen(false)}
              class="p-1 text-theme-text-secondary hover:text-theme-text-primary transition-colors"
              aria-label="Close filters"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="6" y1="6" x2="18" y2="18" />
                <line x1="6" y1="18" x2="18" y2="6" />
              </svg>
            </button>
          </div>
          <Sidebar />
        </div>

        <main class={`flex-1 min-h-[calc(100vh-57px)] ${contentWidthClass(contentWidth())}`}>
          <ScanFiltersOnboarding variant="global" />
          <TargetFeed />
        </main>
      </div>
    </DashboardFilterProvider>
  );
};

export default DashboardPage;
