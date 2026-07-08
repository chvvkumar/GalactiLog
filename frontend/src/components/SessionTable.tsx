import { Component } from "solid-js";
import type { SessionSummary } from "../api/types";
import FilterBadges from "./FilterBadges";
import { useSettingsContext } from "./SettingsProvider";
import { isColumnVisible } from "../utils/displaySettings";
import DataTable, { type DataTableColumn } from "./DataTable";
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
    const vis = ctx.columnVisibility() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} }, mosaic_table: { builtin: {}, custom: {} } };
    const updated = structuredClone(vis);
    if (!updated.session_table) updated.session_table = { builtin: {}, custom: {} };
    if (!updated.session_table[kind]) updated.session_table[kind] = {};
    updated.session_table[kind][key] = visible;
    ctx.saveColumnVisibility(updated);
  }

  // Resolved key->visible record for DataTable's own body/header gating.
  // Keyed independently from the raw ColumnVisibility storage (passed
  // separately to `columnPicker.visibility` below) per the T4 reviewer note:
  // DataTable never interprets ColumnVisibility itself.
  const resolvedVisibility = () => ({
    frames: isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "frames"),
    integration: isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "integration"),
    filters: isColumnVisible(ctx.columnVisibility(), "session_table", "builtin", "filters"),
    ...Object.fromEntries(
      sessionCustomCols().map((col) => [col.slug, isColumnVisible(ctx.columnVisibility(), "session_table", "custom", col.slug)]),
    ),
  });

  const columns = (): DataTableColumn<SessionSummary>[] => [
    {
      key: "date",
      label: `Date (${tzLabel()})`,
      alwaysVisible: true,
      render: (s) => s.session_date,
    },
    {
      key: "frames",
      label: "Frames",
      align: "right",
      render: (s) => s.frame_count,
    },
    {
      key: "integration",
      label: "Integration",
      align: "right",
      render: (s) => formatIntegration(s.integration_seconds),
    },
    {
      key: "filters",
      label: "Filters",
      render: (s) => <FilterBadges distribution={Object.fromEntries(s.filters_used.map(f => [f, 0]))} compact />,
    },
    ...sessionCustomCols().map((col): DataTableColumn<SessionSummary> => ({
      key: col.slug,
      label: col.name,
      align: "right",
      // Session-level custom values were never editable/populated here in the
      // pre-DataTable table either -- always rendered as a static "-".
      render: () => "-",
    })),
    {
      key: "actions",
      label: "",
      alwaysVisible: true,
      render: (s) => (
        <button
          onClick={() => props.onDeepDive(s.session_date)}
          class="text-theme-accent hover:underline text-label"
        >
          Deep Dive
        </button>
      ),
    },
  ];

  return (
    <div class="border-t border-theme-border mt-2 overflow-x-auto">
      <DataTable
        // Density: the pre-swap SessionTable used py-1.5/px-2 (tighter than
        // DataTable's default py-2/px-3). DataTable hard-codes cell padding
        // per the T4 API, so density is applied here via descendant
        // arbitrary-variant overrides on the `class` prop (the caller-class
        // mechanism the T4 reviewer note prescribes), not a new DataTable prop.
        class="text-xs min-w-[400px] [&_td]:!py-1.5 [&_td]:!px-2 [&_th]:!py-1.5 [&_th]:!px-2"
        columns={columns()}
        rows={props.sessions}
        rowKey={(s) => s.session_date}
        visibility={resolvedVisibility}
        emptyMessage=""
        columnPicker={{
          table: "session_table",
          builtinColumns: [
            { key: "date", label: "Date", alwaysVisible: true },
            { key: "frames", label: "Frames" },
            { key: "integration", label: "Integration" },
            { key: "filters", label: "Filters" },
          ],
          customColumns: sessionCustomCols(),
          visibility: ctx.columnVisibility(),
          onToggle: handleColumnToggle,
        }}
      />
    </div>
  );
};

export default SessionTable;
