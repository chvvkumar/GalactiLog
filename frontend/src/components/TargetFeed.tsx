import { Component, Show, For } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import TargetTable from "./TargetTable";

const SkeletonRow: Component = () => (
  <tr class="border-b border-theme-border">
    <td class="p-3"><div class="h-4 w-32 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-20 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="flex gap-1"><div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" /><div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" /></div></td>
    <td class="p-3"><div class="h-4 w-16 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-24 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-20 bg-theme-elevated rounded animate-pulse" /></td>
    <td class="p-3"><div class="h-4 w-6 bg-theme-elevated rounded animate-pulse" /></td>
  </tr>
);

const SkeletonCard: Component = () => (
  <div class="border-b border-theme-border p-3 space-y-2">
    <div class="flex justify-between">
      <div class="h-4 w-40 bg-theme-elevated rounded animate-pulse" />
      <div class="h-6 w-16 bg-theme-elevated rounded animate-pulse" />
    </div>
    <div class="h-3 w-24 bg-theme-elevated rounded animate-pulse" />
    <div class="flex gap-2">
      <div class="h-3 w-16 bg-theme-elevated rounded animate-pulse" />
      <div class="h-3 w-20 bg-theme-elevated rounded animate-pulse" />
    </div>
    <div class="flex gap-1">
      <div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" />
      <div class="h-5 w-8 bg-theme-elevated rounded animate-pulse" />
    </div>
  </div>
);

const TargetFeed: Component = () => {
  const { targetData, refetchTargets, fetchError, page, totalPages, totalCount, setPage, pageSize, setPageSize } = useDashboardFilters();
  const PAGE_SIZES = [10, 25, 50, 100, 250];


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

  const displayData = () => targetData() ?? targetData.latest;

  return (
    <div class="p-4">
      <Show when={fetchError() && !displayData()}>
        <div class="text-center text-theme-error py-8">
          Failed to load targets: {String(fetchError())}
        </div>
      </Show>

      {/* Inline error banner when cached data is shown but latest request failed */}
      <Show when={fetchError() && displayData()}>
        <div class="mb-2 px-3 py-2 rounded border border-theme-error/30 bg-theme-error/10 text-theme-error text-xs flex items-center justify-between">
          <span>Filter request failed: {String(fetchError())}</span>
          <button onClick={() => refetchTargets()} class="ml-3 underline hover:no-underline">Retry</button>
        </div>
      </Show>

      {/* Skeleton: shown on initial load (no data yet) */}
      <Show when={targetData.loading && !displayData()}>
        {/* Desktop skeleton */}
        <div class="overflow-x-auto hidden md:block">
          <table class="w-full text-sm">
            <thead><tr class="border-b border-theme-border text-left">
              <th class="p-3 text-xs text-theme-text-secondary">Target</th>
              <th class="p-3 text-xs text-theme-text-secondary">Designation</th>
              <th class="p-3 text-xs text-theme-text-secondary">Palette</th>
              <th class="p-3 text-xs text-theme-text-secondary">Integration</th>
              <th class="p-3 text-xs text-theme-text-secondary">Equipment</th>
              <th class="p-3 text-xs text-theme-text-secondary">Last Session</th>
              <th class="p-3" />
            </tr></thead>
            <tbody>
              <For each={Array(pageSize())}>{() => <SkeletonRow />}</For>
            </tbody>
          </table>
        </div>
        {/* Mobile skeleton */}
        <div class="md:hidden">
          <For each={Array(pageSize())}>{() => <SkeletonCard />}</For>
        </div>
      </Show>

      <Show when={displayData()}>
        {(data) => (
          <Show
            when={data().targets.length > 0}
            fallback={<div class="text-center text-theme-text-secondary py-8">No targets match your filters</div>}
          >
            <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mb-2 px-1">
              <div class="flex items-center gap-3">
                <span class="text-xs text-theme-text-tertiary">
                  Showing {showingRange().start}-{showingRange().end} of {totalCount()} targets
                </span>
                <select
                  value={pageSize()}
                  onChange={(e) => setPageSize(Number(e.currentTarget.value))}
                  class="px-2 py-1 text-xs rounded border border-theme-border bg-theme-input text-theme-text-secondary cursor-pointer transition-colors hover:border-theme-border-em"
                >
                  <For each={PAGE_SIZES}>
                    {(size) => <option value={size}>{size} / page</option>}
                  </For>
                </select>
              </div>
              <Show when={totalPages() > 1}>
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
              </Show>
            </div>

            <div class={targetData.loading && !fetchError() ? "opacity-50 pointer-events-none transition-opacity" : "transition-opacity"}>
              <TargetTable targets={data().targets} />
            </div>
          </Show>
        )}
      </Show>
    </div>
  );
};

export default TargetFeed;
