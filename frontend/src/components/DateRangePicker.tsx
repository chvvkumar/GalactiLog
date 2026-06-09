import { Component, createMemo, Show } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";

const DateRangePicker: Component = () => {
  const { filters, updateFilter, targetData } = useDashboardFilters();

  const dateBounds = () => {
    const data = targetData();
    return {
      oldest: data?.aggregates?.oldest_date || "",
      newest: data?.aggregates?.newest_date || "",
    };
  };

  const dateRangeError = createMemo(() => {
    const start = filters().dateRange.start;
    const end = filters().dateRange.end;
    if (start && end && start > end) {
      return "From date must be on or before To date.";
    }
    return null;
  });

  return (
    <div>
      <div class="flex gap-2">
        <input
          type="date"
          value={filters().dateRange.start || ""}
          min={dateBounds().oldest}
          max={filters().dateRange.end || dateBounds().newest}
          placeholder={dateBounds().oldest}
          onInput={(e) =>
            updateFilter("dateRange", { ...filters().dateRange, start: e.currentTarget.value || null })
          }
          class={`flex-1 px-2 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:border-theme-accent outline-none ${dateRangeError() ? "border-red-500" : "border-theme-border"}`}
        />
        <input
          type="date"
          value={filters().dateRange.end || ""}
          min={filters().dateRange.start || dateBounds().oldest}
          max={dateBounds().newest}
          placeholder={dateBounds().newest}
          onInput={(e) =>
            updateFilter("dateRange", { ...filters().dateRange, end: e.currentTarget.value || null })
          }
          class={`flex-1 px-2 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:border-theme-accent outline-none ${dateRangeError() ? "border-red-500" : "border-theme-border"}`}
        />
      </div>
      <Show when={dateRangeError()}>
        <p class="mt-1 text-xs text-red-500">{dateRangeError()}</p>
      </Show>
    </div>
  );
};

export default DateRangePicker;
