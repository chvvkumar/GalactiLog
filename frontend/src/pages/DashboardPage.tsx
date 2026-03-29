import { Component, onMount, onCleanup } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import Sidebar from "../components/Sidebar";
import TargetFeed from "../components/TargetFeed";
import DashboardFilterProvider, { hasFilterParams, ALL_PARAM_KEYS } from "../components/DashboardFilterProvider";

const SESSION_KEY = "dashboard_params";

const DashboardPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  // Restore saved params if URL has none
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

  // Save current params on cleanup
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
        <Sidebar />
        <main class="flex-1 min-h-[calc(100vh-57px)]">
          <TargetFeed />
        </main>
      </div>
    </DashboardFilterProvider>
  );
};

export default DashboardPage;
