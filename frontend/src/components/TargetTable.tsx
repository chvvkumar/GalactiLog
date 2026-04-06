import { Component, For, Show, createMemo } from "solid-js";
import type { TargetAggregation } from "../types";
import TargetRow from "./TargetRow";
import ColumnPicker from "./ColumnPicker";
import { useSettingsContext } from "./SettingsProvider";
import { isColumnVisible } from "../utils/displaySettings";
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

  const vis = () => ctx.columnVisibility();
  const targetCustomColumns = () => (ctx.customColumns() ?? []).filter(c => c.applies_to === "target");

  function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
    const v = vis() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} } };
    const updated = structuredClone(v);
    if (!updated.dashboard) updated.dashboard = { builtin: {}, custom: {} };
    if (!updated.dashboard[kind]) updated.dashboard[kind] = {};
    updated.dashboard[kind][key] = visible;
    ctx.saveColumnVisibility(updated);
  }

  return (
    <table class="w-full text-sm border-collapse">
      <thead>
        <tr class="sticky top-0 bg-theme-surface border-b border-theme-border-em z-10 text-theme-text-tertiary text-label uppercase tracking-wider hidden md:table-row">
          <th class={headerClass("name")} onClick={() => toggleSort("name")}>
            Target Name{arrow("name")}
          </th>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "designation")}>
            <th class={plainHeaderClass}>Designation</th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "palette")}>
            <th class={plainHeaderClass}>Palette</th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "integration")}>
            <th class={headerClass("integration")} onClick={() => toggleSort("integration")}>
              Integration Time{arrow("integration")}
            </th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "equipment")}>
            <th class={headerClass("equipment")} onClick={() => toggleSort("equipment")}>
              Equipment Profile{arrow("equipment")}
            </th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "last_session")}>
            <th class={headerClass("lastSession")} onClick={() => toggleSort("lastSession")}>
              Last Session ({tzLabel()}){arrow("lastSession")}
            </th>
          </Show>
          <For each={targetCustomColumns()}>
            {(col) => (
              <Show when={isColumnVisible(vis(), "dashboard", "custom", col.slug)}>
                <th class="py-2 px-3 text-right text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap">{col.name}</th>
              </Show>
            )}
          </For>
          <th class={plainHeaderClass}>
            <ColumnPicker
              table="dashboard"
              builtinColumns={[
                { key: "name", label: "Target Name", alwaysVisible: true },
                { key: "designation", label: "Designation" },
                { key: "palette", label: "Palette" },
                { key: "integration", label: "Integration Time" },
                { key: "equipment", label: "Equipment Profile" },
                { key: "last_session", label: "Last Session" },
              ]}
              customColumns={targetCustomColumns()}
              visibility={vis()}
              onToggle={handleColumnToggle}
            />
          </th>
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
