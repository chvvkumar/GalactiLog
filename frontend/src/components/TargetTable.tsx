import { Component, For, createMemo } from "solid-js";
import type { TargetAggregation } from "../types";
import TargetRow from "./TargetRow";
import { useSettingsContext } from "./SettingsProvider";
import { timezoneLabel } from "../utils/dateTime";
import { useDashboardFilters, type SortKey } from "./DashboardFilterProvider";

function getLastSession(t: TargetAggregation): string {
  if (t.sessions.length === 0) return "";
  return [...t.sessions].sort((a, b) => b.session_date.localeCompare(a.session_date))[0].session_date;
}

function getDisplayName(t: TargetAggregation): string {
  return t.aliases[0] || t.primary_name;
}

const TargetTable: Component<{ targets: TargetAggregation[] }> = (props) => {
  const ctx = useSettingsContext();
  const tzLabel = () => timezoneLabel(ctx.timezone());
  const { sortKey, sortDir, toggleSort } = useDashboardFilters();

  const UNCATEGORIZED_ID = "obj:__uncategorized__";

  // Client-side sort only for "equipment" (no backend support);
  // other sort keys are handled server-side, so just pass through.
  const sortedTargets = createMemo(() => {
    const key = sortKey();
    const dir = sortDir();
    if (key !== "equipment") return props.targets;

    const sorted = [...props.targets].sort((a, b) => {
      if (a.target_id === UNCATEGORIZED_ID) return 1;
      if (b.target_id === UNCATEGORIZED_ID) return -1;
      const cmp = a.equipment.join(" ").localeCompare(b.equipment.join(" "));
      return dir === "asc" ? cmp : -cmp;
    });
    return sorted;
  });

  const arrow = (key: SortKey) => {
    if (sortKey() !== key) return " \u2195";
    return sortDir() === "asc" ? " \u2191" : " \u2193";
  };

  const headerClass = (key: SortKey) =>
    `text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary cursor-pointer select-none hover:text-theme-text-primary transition-colors whitespace-nowrap${sortKey() === key ? " border-b-2 border-theme-accent" : ""}`;
  const plainHeaderClass = "text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap";

  return (
    <table class="w-full text-sm border-collapse">
      <thead>
        <tr class="sticky top-0 bg-theme-surface border-b border-theme-border-em z-10 text-theme-text-tertiary text-label uppercase tracking-wider hidden md:table-row">
          <th class={headerClass("name")} onClick={() => toggleSort("name")}>
            Target Name{arrow("name")}
          </th>
          <th class={plainHeaderClass}>Designation</th>
          <th class={plainHeaderClass}>Palette</th>
          <th class={headerClass("integration")} onClick={() => toggleSort("integration")}>
            Integration Time{arrow("integration")}
          </th>
          <th class={headerClass("equipment")} onClick={() => toggleSort("equipment")}>
            Equipment Profile{arrow("equipment")}
          </th>
          <th class={headerClass("lastSession")} onClick={() => toggleSort("lastSession")}>
            Last Session ({tzLabel()}){arrow("lastSession")}
          </th>
          <th class={plainHeaderClass}></th>
        </tr>
      </thead>
      <tbody>
        <For each={sortedTargets()}>
          {(target) => (
            <TargetRow target={target} />
          )}
        </For>
      </tbody>
    </table>
  );
};

export default TargetTable;
