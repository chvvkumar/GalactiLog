import { Component, For, Show, createResource } from "solid-js";
import { useCatalog } from "../store/catalog";
import { useSettingsContext } from "./SettingsProvider";
import { api } from "../api/client";
import { getFilterBadgeStyle } from "../utils/filterStyles";

const FilterToggles: Component = () => {
  const { filters, toggleOpticalFilter } = useCatalog();
  const { settings, filterColorMap, filterAliasMap, filterBadgeStyle } = useSettingsContext();
  const [discovered] = createResource(() => api.getDiscovered("filters").then((r) => r.items));

  const isActive = (f: string) => filters().opticalFilters.includes(f);

  function getColor(name: string): string {
    const colorMap = filterColorMap();
    const aliasMap = filterAliasMap();
    const canonical = aliasMap[name] || name;
    return colorMap[canonical] || colorMap[name] || "#666666";
  }

  const groupedFilters = () => {
    const s = settings();
    if (!s) return [];
    return Object.keys(s.filters);
  };

  const ungroupedFilters = () => {
    const s = settings();
    const disc = discovered();
    if (!disc) return [];
    if (!s) return disc.map((d) => d.name);

    const covered = new Set<string>();
    for (const [canonical, cfg] of Object.entries(s.filters)) {
      covered.add(canonical);
      for (const alias of cfg.aliases) covered.add(alias);
    }
    return disc.map((d) => d.name).filter((name) => !covered.has(name));
  };

  const renderPill = (name: string) => {
    const active = isActive(name);
    const color = getColor(name);
    const badgeStyle = () => getFilterBadgeStyle(filterBadgeStyle(), color);
    return (
      <button
        onClick={() => toggleOpticalFilter(name)}
        class={`h-6 rounded text-caption font-bold flex items-center justify-center gap-0.5 transition-all ${
          active ? "ring-1 ring-theme-accent brightness-110" : "ring-1 ring-transparent hover:brightness-110"
        }`}
        classList={{ "w-6": name.length <= 1 && !badgeStyle().dot, "px-1.5": name.length > 1 || !!badgeStyle().dot }}
        style={badgeStyle().style}
        title={name}
      >
        <Show when={badgeStyle().dot}>
          <span class="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ "background-color": badgeStyle().dot }} />
        </Show>
        {name}
      </button>
    );
  };

  return (
    <div class="space-y-2">
      <label class="text-label font-medium uppercase tracking-wider text-theme-text-tertiary">Filters</label>
      <div class="space-y-1.5">
        <Show when={groupedFilters().length > 0}>
          <span class="text-caption text-theme-text-secondary">Grouped</span>
          <div class="flex gap-1.5 flex-wrap">
            <For each={groupedFilters()}>{(f) => renderPill(f)}</For>
          </div>
        </Show>
        <Show when={ungroupedFilters().length > 0}>
          <span class="text-caption text-theme-text-secondary">Ungrouped</span>
          <div class="flex gap-1.5 flex-wrap">
            <For each={ungroupedFilters()}>{(f) => renderPill(f)}</For>
          </div>
        </Show>
      </div>
    </div>
  );
};

export default FilterToggles;
