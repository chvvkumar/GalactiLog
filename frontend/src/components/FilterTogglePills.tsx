import { For } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import Toggle from "./ui/Toggle";

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
            <Toggle
              active={isActive()}
              color={color()}
              onClick={() => toggleFilter(filter)}
            >
              {filter === "overall" ? "Overall" : filter}
            </Toggle>
          );
        }}
      </For>
    </div>
  );
}
