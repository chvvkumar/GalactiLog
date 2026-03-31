import { Component, Show, For, createEffect } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { showToast, dismissToast } from "./Toast";
import TargetTable from "./TargetTable";

const TargetFeed: Component = () => {
  const { targetData, page, totalPages, totalCount, setPage, pageSize } = useDashboardFilters();

  // Show loading as a toast; dismiss 1s after data arrives
  createEffect(() => {
    if (targetData.loading) {
      showToast("Loading targets...", "success", 10000);
    } else {
      dismissToast(1000);
    }
  });

  const pageRange = () => {
    const current = page();
    const total = totalPages();
    const pages: (number | "...")[] = [];
    if (total <= 7) {
      for (let i = 1; i <= total; i++) pages.push(i);
    } else {
      pages.push(1);
      if (current > 3) pages.push("...");
      for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
        pages.push(i);
      }
      if (current < total - 2) pages.push("...");
      pages.push(total);
    }
    return pages;
  };

  const showingRange = () => {
    const start = (page() - 1) * pageSize() + 1;
    const end = Math.min(page() * pageSize(), totalCount());
    return { start, end };
  };

  // Use latest data, or keep showing previous data while loading
  const displayData = () => targetData() ?? targetData.latest;

  return (
    <div class="p-4">
      <Show when={targetData.error && !displayData()}>
        <div class="text-center text-theme-error py-8">
          Failed to load targets: {String(targetData.error)}
        </div>
      </Show>
      <Show when={displayData()}>
        {(data) => (
          <Show
            when={data().targets.length > 0}
            fallback={<div class="text-center text-theme-text-secondary py-8">No targets match your filters</div>}
          >
            <Show when={totalPages() > 1}>
              <div class="flex items-center justify-between mb-2 px-1">
                <span class="text-xs text-theme-text-tertiary">
                  Showing {showingRange().start}-{showingRange().end} of {totalCount()} targets
                </span>
                <div class="flex items-center gap-1">
                  <button
                    onClick={() => setPage(page() - 1)}
                    disabled={page() <= 1}
                    class="px-2 py-1 text-xs rounded border border-theme-border text-theme-text-secondary hover:bg-theme-elevated disabled:opacity-30 disabled:cursor-default transition-colors"
                  >
                    Prev
                  </button>
                  <For each={pageRange()}>
                    {(p) => (
                      <Show
                        when={p !== "..."}
                        fallback={<span class="px-1 text-xs text-theme-text-tertiary">...</span>}
                      >
                        <button
                          onClick={() => setPage(p as number)}
                          class={`px-2 py-1 text-xs rounded border transition-colors ${
                            page() === p
                              ? "border-theme-accent bg-theme-accent/10 text-theme-accent font-medium"
                              : "border-theme-border text-theme-text-secondary hover:bg-theme-elevated"
                          }`}
                        >
                          {p}
                        </button>
                      </Show>
                    )}
                  </For>
                  <button
                    onClick={() => setPage(page() + 1)}
                    disabled={page() >= totalPages()}
                    class="px-2 py-1 text-xs rounded border border-theme-border text-theme-text-secondary hover:bg-theme-elevated disabled:opacity-30 disabled:cursor-default transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>
            </Show>

            <div class={targetData.loading ? "opacity-50 pointer-events-none transition-opacity" : "transition-opacity"}>
              <TargetTable targets={data().targets} />
            </div>
          </Show>
        )}
      </Show>
    </div>
  );
};

export default TargetFeed;
