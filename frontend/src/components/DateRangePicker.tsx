import { Component } from "solid-js";
import { useCatalog } from "../store/catalog";

const DateRangePicker: Component = () => {
  const { filters, updateFilter, targetData } = useCatalog();

  const dateBounds = () => {
    const data = targetData();
    return {
      oldest: data?.aggregates?.oldest_date || "",
      newest: data?.aggregates?.newest_date || "",
    };
  };

  return (
    <div class="space-y-2">
      <label class="text-label font-medium uppercase tracking-wider text-theme-text-tertiary">Date Range</label>
      <div class="flex gap-2">
        <input
          type="date"
          value={filters().dateRange.start || ""}
          min={dateBounds().oldest}
          max={dateBounds().newest}
          placeholder={dateBounds().oldest}
          onInput={(e) =>
            updateFilter("dateRange", { ...filters().dateRange, start: e.currentTarget.value || null })
          }
          class="flex-1 px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
        <input
          type="date"
          value={filters().dateRange.end || ""}
          min={dateBounds().oldest}
          max={dateBounds().newest}
          placeholder={dateBounds().newest}
          onInput={(e) =>
            updateFilter("dateRange", { ...filters().dateRange, end: e.currentTarget.value || null })
          }
          class="flex-1 px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
      </div>
    </div>
  );
};

export default DateRangePicker;
