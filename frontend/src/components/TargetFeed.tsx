import { Component, Show, For } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import TargetTable from "./TargetTable";

const TargetFeed: Component = () => {
  const { targetData, page, totalPages, totalCount, setPage, pageSize } = useDashboardFilters();

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

  return (
    <div class="p-4">
      <Show when={targetData.loading}>
        <div class="text-center text-theme-text-secondary py-8">Loading targets...</div>
      </Show>
      <Show when={targetData.error}>
        <div class="text-center text-theme-error py-8">
          Failed to load targets: {String(targetData.error)}
        </div>
      </Show>
      <Show when={targetData()}>
        {(data) => (
          <Show
            when={data().targets.length > 0}
            fallback={<div class="text-center text-theme-text-secondary py-8">No targets match your filters</div>}
          >
            <TargetTable targets={data().targets} />

            <Show when={totalPages() > 1}>
              <div class="flex items-center justify-between mt-4 px-2">
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
          </Show>
        )}
      </Show>
    </div>
  );
};

export default TargetFeed;
