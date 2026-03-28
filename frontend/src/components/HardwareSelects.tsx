import { Component, Show, For } from "solid-js";
import { useCatalog } from "../store/catalog";

const HardwareSelects: Component = () => {
  const { filters, updateFilter, equipment } = useCatalog();

  return (
    <div class="space-y-2">
      <label class="text-xs text-theme-text-secondary">Equipment</label>
      <Show when={equipment()} fallback={<p class="text-xs text-theme-text-secondary">Loading...</p>}>
        {(eq) => (
          <>
            <select
              value={filters().camera || ""}
              onChange={(e) => updateFilter("camera", e.currentTarget.value || null)}
              class="w-full px-2 py-1.5 bg-theme-base border border-theme-border rounded text-xs text-theme-text-primary focus:outline-none focus:ring-1 focus:border-theme-accent"
            >
              <option value="">All Cameras</option>
              <For each={eq().cameras}>{(c) => <option value={c}>{c}</option>}</For>
            </select>
            <select
              value={filters().telescope || ""}
              onChange={(e) => updateFilter("telescope", e.currentTarget.value || null)}
              class="w-full px-2 py-1.5 bg-theme-base border border-theme-border rounded text-xs text-theme-text-primary focus:outline-none focus:ring-1 focus:border-theme-accent"
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
