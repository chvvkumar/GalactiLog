import { Component, For, createMemo, createSignal } from "solid-js";
import type { TargetAggregation } from "../types";
import TargetRow from "./TargetRow";

type SortKey = "name" | "integration" | "lastSession" | "equipment";
type SortDir = "asc" | "desc";

function getLastSession(t: TargetAggregation): string {
  if (t.sessions.length === 0) return "";
  return [...t.sessions].sort((a, b) => b.session_date.localeCompare(a.session_date))[0].session_date;
}

function getDisplayName(t: TargetAggregation): string {
  return t.aliases[0] || t.primary_name;
}

const TargetTable: Component<{ targets: TargetAggregation[] }> = (props) => {
  const stored = localStorage.getItem("dashboard_sort");
  const initial: { key: SortKey; dir: SortDir } = stored
    ? JSON.parse(stored)
    : { key: "integration", dir: "desc" };

  const [sortKey, setSortKey] = createSignal<SortKey>(initial.key);
  const [sortDir, setSortDir] = createSignal<SortDir>(initial.dir);

  const persistSort = (key: SortKey, dir: SortDir) => {
    localStorage.setItem("dashboard_sort", JSON.stringify({ key, dir }));
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey() === key) {
      const newDir = sortDir() === "asc" ? "desc" : "asc";
      setSortDir(newDir);
      persistSort(key, newDir);
    } else {
      const newDir = key === "name" ? "asc" : "desc";
      setSortKey(key);
      setSortDir(newDir);
      persistSort(key, newDir);
    }
  };

  const sortedTargets = createMemo(() => {
    const key = sortKey();
    const dir = sortDir();
    const sorted = [...props.targets].sort((a, b) => {
      let cmp = 0;
      switch (key) {
        case "name":
          cmp = getDisplayName(a).localeCompare(getDisplayName(b));
          break;
        case "integration":
          cmp = a.total_integration_seconds - b.total_integration_seconds;
          break;
        case "lastSession":
          cmp = getLastSession(a).localeCompare(getLastSession(b));
          break;
        case "equipment":
          cmp = a.equipment.join(" ").localeCompare(b.equipment.join(" "));
          break;
      }
      return dir === "asc" ? cmp : -cmp;
    });
    return sorted;
  });

  const arrow = (key: SortKey) => {
    if (sortKey() !== key) return " \u2195";
    return sortDir() === "asc" ? " \u2191" : " \u2193";
  };

  const headerClass = "text-left py-2 px-3 font-medium cursor-pointer select-none hover:text-theme-text-primary transition-colors whitespace-nowrap";
  const plainHeaderClass = "text-left py-2 px-3 font-medium whitespace-nowrap";

  return (
    <table class="w-full text-sm border-collapse">
      <thead>
        <tr class="text-theme-text-secondary text-[11px] uppercase tracking-wider border-b border-theme-border">
          <th class={headerClass} onClick={() => toggleSort("name")}>
            Target Name{arrow("name")}
          </th>
          <th class={plainHeaderClass}>Designation</th>
          <th class={plainHeaderClass}>Palette</th>
          <th class={headerClass} onClick={() => toggleSort("integration")}>
            Integration Time{arrow("integration")}
          </th>
          <th class={headerClass} onClick={() => toggleSort("equipment")}>
            Equipment Profile{arrow("equipment")}
          </th>
          <th class={headerClass} onClick={() => toggleSort("lastSession")}>
            Last Session{arrow("lastSession")}
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
