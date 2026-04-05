import { Component, For, Show } from "solid-js";
import type { SessionSummary } from "../types";
import FilterBadges from "./FilterBadges";
import { useSettingsContext } from "./SettingsProvider";
import { isColumnVisible } from "../utils/displaySettings";
import ColumnPicker from "./ColumnPicker";
import { timezoneLabel } from "../utils/dateTime";

import { formatIntegration } from "../utils/format";

const SessionTable: Component<{
  sessions: SessionSummary[];
  onDeepDive: (date: string) => void;
}> = (props) => {
  const ctx = useSettingsContext();
  const tzLabel = () => timezoneLabel(ctx.timezone());

  const sessionCustomCols = () => (ctx.customColumns() ?? []).filter(c => c.applies_to === "session");

  function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
    const vis = ctx.columnVisibility() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} } };
    const updated = structuredClone(vis);
    if (!updated.session_table) updated.session_table = { builtin: {}, custom: {} };
    if (!updated.session_table[kind]) updated.session_table[kind] = {};
    updated.session_table[kind][key] = visible;
    ctx.saveColumnVisibility(updated);
  }

  return (
    <div class="border-t border-theme-border mt-2 overflow-x-auto">
      <div class="flex items-center justify-end px-2 py-1">
        <ColumnPicker
          table="session_table"
          builtinColumns={[
            { key: "date", label: "Date", alwaysVisible: true },
            { key: "frames", label: "Frames" },
            { key: "integration", label: "Integration" },
            { key: "filters", label: "Filters" },
          ]}
          customColumns={sessionCustomCols()}
          visibility={ctx.columnVisibility()}
          onToggle={handleColumnToggle}
        />
      </div>
      <table class="w-full text-xs min-w-[400px]">
        <thead>
          <tr class="text-theme-text-secondary border-b border-theme-border">
            <th class="text-left py-1.5 px-2 font-normal">Date ({tzLabel()})</th>
            <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "frames")}>
              <th class="text-right py-1.5 px-2 font-normal">Frames</th>
            </Show>
            <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "integration")}>
              <th class="text-right py-1.5 px-2 font-normal">Integration</th>
            </Show>
            <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "filters")}>
              <th class="text-left py-1.5 px-2 font-normal">Filters</th>
            </Show>
            <For each={sessionCustomCols()}>
              {(col) => (
                <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "custom", col.slug)}>
                  <th class="py-1.5 px-2 text-right font-normal">{col.name}</th>
                </Show>
              )}
            </For>
            <th class="py-1.5 px-2"></th>
          </tr>
        </thead>
        <tbody>
          <For each={props.sessions}>
            {(session) => (
              <tr class="border-b border-theme-border/50 hover:bg-theme-hover transition-colors duration-150">
                <td class="py-1.5 px-2 text-theme-text-primary">{session.session_date}</td>
                <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "frames")}>
                  <td class="py-1.5 px-2 text-right text-theme-text-primary">{session.frame_count}</td>
                </Show>
                <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "integration")}>
                  <td class="py-1.5 px-2 text-right text-theme-text-primary">{formatIntegration(session.integration_seconds)}</td>
                </Show>
                <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "filters")}>
                  <td class="py-1.5 px-2">
                    <FilterBadges distribution={Object.fromEntries(session.filters_used.map(f => [f, 0]))} compact />
                  </td>
                </Show>
                <For each={sessionCustomCols()}>
                  {(col) => (
                    <Show when={isColumnVisible(ctx.columnVisibility(), "session_table", "custom", col.slug)}>
                      <td class="py-1.5 px-2 text-right text-theme-text-secondary">-</td>
                    </Show>
                  )}
                </For>
                <td class="py-1.5 px-2 text-right">
                  <button
                    onClick={() => props.onDeepDive(session.session_date)}
                    class="text-theme-accent hover:underline text-label"
                  >
                    Deep Dive
                  </button>
                </td>
              </tr>
            )}
          </For>
        </tbody>
      </table>
    </div>
  );
};

export default SessionTable;
