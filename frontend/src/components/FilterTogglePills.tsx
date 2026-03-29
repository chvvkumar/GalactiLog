import { For } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";

interface Props {
  filters: string[];
}

export default function FilterTogglePills(props: Props) {
  const { graphSettings, toggleFilter, filterColorMap } = useSettingsContext();

  const allFilters = () => ["overall", ...props.filters];

  return (
    <div class="flex flex-wrap gap-1.5">
      <For each={allFilters()}>
        {(filter) => {
          const isActive = () => graphSettings().enabled_filters.includes(filter);
          const color = () => {
            if (filter === "overall") return "var(--color-info)";
            return filterColorMap()[filter] ?? "var(--color-text-secondary)";
          };
          return (
            <button
              class="px-2 py-0.5 rounded text-caption font-medium border transition-colors cursor-pointer"
              style={{
                "border-color": isActive() ? color() : "var(--color-border-default)",
                "background-color": isActive() ? `${color()}22` : "var(--color-bg-elevated)",
                color: isActive() ? color() : "var(--color-text-tertiary)",
              }}
              onClick={() => toggleFilter(filter)}
            >
              {filter === "overall" ? "Overall" : filter}
            </button>
          );
        }}
      </For>
    </div>
  );
}
