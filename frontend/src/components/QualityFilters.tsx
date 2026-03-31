import { Component, createSignal, createEffect } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { debounce } from "../utils/debounce";

const QualityFilters: Component = () => {
  const { filters, updateQualityFilters } = useDashboardFilters();
  const [hfrMin, setHfrMin] = createSignal<string>("");
  const [hfrMax, setHfrMax] = createSignal<string>("");

  let initialized = false;

  // Sync from store on init only
  createEffect(() => {
    const qf = filters().qualityFilters;
    if (!initialized) {
      initialized = true;
      if (qf.hfrMin != null) setHfrMin(String(qf.hfrMin));
      if (qf.hfrMax != null) setHfrMax(String(qf.hfrMax));
    }
  });

  const applyFilters = debounce(() => {
    const min = hfrMin() ? parseFloat(hfrMin()) : undefined;
    const max = hfrMax() ? parseFloat(hfrMax()) : undefined;
    updateQualityFilters({
      hfrMin: min && !isNaN(min) ? min : undefined,
      hfrMax: max && !isNaN(max) ? max : undefined,
    });
  }, 500);

  return (
    <div>
      <div class="flex gap-2 items-center">
        <input
          type="number"
          step="0.1"
          min="0"
          value={hfrMin()}
          onInput={(e) => {
            setHfrMin(e.currentTarget.value);
            applyFilters();
          }}
          placeholder="Min"
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
        <span class="text-theme-text-secondary text-xs">&ndash;</span>
        <input
          type="number"
          step="0.1"
          min="0"
          value={hfrMax()}
          onInput={(e) => {
            setHfrMax(e.currentTarget.value);
            applyFilters();
          }}
          placeholder="Max"
          class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
        />
      </div>
    </div>
  );
};

export default QualityFilters;
