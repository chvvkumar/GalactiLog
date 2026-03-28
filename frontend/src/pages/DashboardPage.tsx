import { Component, onMount, createEffect } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import Sidebar from "../components/Sidebar";
import TargetFeed from "../components/TargetFeed";
import { initFiltersFromUrl, useCatalog } from "../store/catalog";

const DashboardPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { filtersAsParams } = useCatalog();

  // On first mount, restore filters from URL params or sessionStorage
  onMount(() => {
    const params = new URLSearchParams(window.location.search);
    initFiltersFromUrl(params);
  });

  // Keep URL params in sync with current filters
  createEffect(() => {
    const p = filtersAsParams();
    // Clear all filter params first, then set current ones
    const clear: Record<string, undefined> = {};
    for (const key of ["search", "camera", "telescope", "filters", "object_type", "date_from", "date_to", "hfr_min", "hfr_max", "fits_key", "fits_op", "fits_val"]) {
      clear[key] = undefined;
    }
    setSearchParams({ ...clear, ...p }, { replace: true });
  });

  return (
    <div class="flex" data-layout="sidebar-main">
      <Sidebar />
      <main class="flex-1 min-h-[calc(100vh-57px)]">
        <TargetFeed />
      </main>
    </div>
  );
};

export default DashboardPage;
