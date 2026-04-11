import { Component } from "solid-js";
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
          class="flex-1 px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:border-theme-accent outline-none"
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
          class="flex-1 px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:border-theme-accent outline-none"
        />
      </div>
    </div>
  );
};

export default DateRangePicker;
