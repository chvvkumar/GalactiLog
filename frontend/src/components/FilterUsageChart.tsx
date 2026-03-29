import { Component, For, Show } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import { getFilterBadgeStyle } from "../utils/filterStyles";

const FilterUsageChart: Component<{ usage: Record<string, number> }> = (props) => {
  const { filterColorMap, filterAliasMap, filterBadgeStyle } = useSettingsContext();

  function getColor(name: string): string {
    const colorMap = filterColorMap();
    const aliasMap = filterAliasMap();
    const canonical = aliasMap[name] || name;
    return colorMap[canonical] || colorMap[name] || "#6b7280";
  }

  const entries = () => Object.entries(props.usage).sort(([, a], [, b]) => b - a);
  const maxVal = () => Math.max(...Object.values(props.usage), 1);

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <h3 class="text-white font-medium text-sm">Filter Usage</h3>
      <For each={entries()}>
        {([name, seconds]) => {
          const color = getColor(name);
          const badgeStyle = () => getFilterBadgeStyle(filterBadgeStyle(), color);
          return (
            <div class="flex items-center gap-2 text-xs">
              <span
                class="w-12 text-center text-caption font-bold rounded px-1 py-0.5 inline-flex items-center justify-center gap-0.5"
                style={badgeStyle().style}
              >
                <Show when={badgeStyle().dot}>
                  <span class="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ "background-color": badgeStyle().dot }} />
                </Show>
                {name}
              </span>
              <div class="flex-1 bg-theme-base rounded-full h-4 overflow-hidden">
                <div
                  class="h-4 rounded-full transition-all"
                  style={{ width: `${(seconds / maxVal()) * 100}%`, "background-color": color }}
                />
              </div>
              <span class="w-14 text-right text-white">{(seconds / 3600).toFixed(1)}h</span>
            </div>
          );
        }}
      </For>
    </div>
  );
};

export default FilterUsageChart;
