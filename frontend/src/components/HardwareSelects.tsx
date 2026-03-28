import { Component, Show, For } from "solid-js";
import { useCatalog } from "../store/catalog";

const HardwareSelects: Component = () => {
  const { filters, updateFilter, equipment } = useCatalog();

  return (
    <div class="space-y-2">
      <label class="text-[11px] font-medium uppercase tracking-wider text-theme-text-tertiary">Equipment</label>
      <Show when={equipment()} fallback={<p class="text-xs text-theme-text-secondary">Loading...</p>}>
        {(eq) => (
          <>
            <select
              value={filters().camera || ""}
              onChange={(e) => updateFilter("camera", e.currentTarget.value || null)}
              class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
            >
              <option value="">All Cameras</option>
              <For each={eq().cameras}>{(c) => <option value={c}>{c}</option>}</For>
            </select>
            <select
              value={filters().telescope || ""}
              onChange={(e) => updateFilter("telescope", e.currentTarget.value || null)}
              class="w-full px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
            >
              <option value="">All Telescopes</option>
              <For each={eq().telescopes}>{(t) => <option value={t}>{t}</option>}</For>
            </select>
          </>
        )}
      </Show>
    </div>
  );
};

export default HardwareSelects;
