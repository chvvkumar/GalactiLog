import { Component, For, createMemo } from "solid-js";
import { A, useNavigate } from "@solidjs/router";
import { useMutation, useQueryClient } from "@tanstack/solid-query";
// Deliberately kept on the OLD hand-written TargetAggregation (whose
// `user_defined` is optional and `catalog_id` is present) rather than the
// generated-schema alias in `../api/types` (whose `user_defined` is
// required and `catalog_id` is missing -- a real backend/OpenAPI schema
// gap). This mirrors DashboardFilterProvider.tsx's own documented cast:
// `targetData()`/`.latest` (this component's only data source, via
// TargetFeed) is typed against the OLD TargetAggregationResponse for
// exactly this reason, and TargetTable/TargetRow are named in that
// comment as the out-of-scope consumers still expecting the old shape.
// Flagged for Slice 15 (teardown) alongside DashboardFilterProvider's cast.
import type { TargetAggregation } from "../types";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import TargetRow from "./TargetRow";
import FilterBadges from "./FilterBadges";
import InlineEditCell from "./InlineEditCell";
import DataTable, { type DataTableColumn } from "./DataTable";
import { useSettingsContext } from "./SettingsProvider";
import { isColumnVisible } from "../utils/displaySettings";
import { timezoneLabel } from "../utils/dateTime";
import { formatIntegration } from "../utils/format";
import { useDashboardFilters, type SortKey } from "./DashboardFilterProvider";

// NOTE on why this isn't a single, uniform DataTable swap:
// The pre-swap table rendered TWO structurally different views of each
// target -- a desktop `<tr>` (uniform columns, click-to-navigate) and a
// separate mobile "card" `<tr>` with its own Expand/Collapse button and an
// optional expandable session sub-panel directly beneath it. DataTable's
// contract is one `<tr>` per row item built from a flat column list, so it
// can only host the desktop view cleanly. This file therefore renders
// DataTable for the `md:block` desktop table and keeps TargetRow.tsx (now
// mobile-only) for the `md:hidden` card + expand panel, matching the
// original responsive split at the wrapper-div level instead of the `<tr>`
// level. See slice-5-report.md for the full writeup, including the two
// accepted behavior deltas this causes (cell click-area now scoped to cell
// content instead of full cell padding, and desktop no longer mirrors a
// session expand toggled from mobile since desktop never exposed that
// control directly).
function getLastSession(t: TargetAggregation): string {
  if (t.sessions.length === 0) return "";
  return [...t.sessions].sort((a, b) => b.session_date.localeCompare(a.session_date))[0].session_date;
}

function getDisplayName(t: TargetAggregation): string {
  return t.aliases[0] || t.primary_name;
}

const TargetTable: Component<{ targets: TargetAggregation[] }> = (props) => {
  const ctx = useSettingsContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tzLabel = () => timezoneLabel(ctx.timezone());
  const { sortKey, sortDir, toggleSort } = useDashboardFilters();

  const vis = () => ctx.columnVisibility();
  const targetCustomColumns = () => (ctx.customColumns() ?? []).filter(c => c.applies_to === "target");

  function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
    const v = vis() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} }, mosaic_table: { builtin: {}, custom: {} } };
    const updated = structuredClone(v);
    if (!updated.dashboard) updated.dashboard = { builtin: {}, custom: {} };
    if (!updated.dashboard[kind]) updated.dashboard[kind] = {};
    updated.dashboard[kind][key] = visible;
    ctx.saveColumnVisibility(updated);
  }

  const setCustomValueMutation = useMutation(() => ({
    mutationFn: (body: { column_id: string; target_id: string; value: string }) =>
      apiClient.PUT("/api/custom-columns/values", { body }).then(unwrap),
    onSuccess: () => {
      // Custom values are embedded in the target aggregation payload, so the
      // whole targets query (any page/filter/sort variant) must refresh.
      queryClient.invalidateQueries({ queryKey: ["targets"] });
    },
  }));

  const goToTarget = (t: TargetAggregation) =>
    navigate(`/targets/${encodeURIComponent(t.target_id)}?view=sessions`);

  // DataTable's `visibility` record is keyed by whatever column `key` this
  // file chooses -- decoupled from the raw ColumnVisibility storage keys
  // (which stay "last_session" etc. for backward-compat with saved settings
  // and with ColumnPicker's builtinColumns below). Sortable column keys here
  // must equal SortKey's literal values ("lastSession", not "last_session")
  // since DataTable also uses the same `key` for its onSort/sortKey/arrow
  // comparisons -- this mapping is what reconciles the two naming schemes.
  const resolvedVisibility = () => ({
    designation: isColumnVisible(vis(), "dashboard", "builtin", "designation"),
    palette: isColumnVisible(vis(), "dashboard", "builtin", "palette"),
    integration: isColumnVisible(vis(), "dashboard", "builtin", "integration"),
    equipment: isColumnVisible(vis(), "dashboard", "builtin", "equipment"),
    lastSession: isColumnVisible(vis(), "dashboard", "builtin", "last_session"),
    ...Object.fromEntries(
      targetCustomColumns().map((col) => [col.slug, isColumnVisible(vis(), "dashboard", "custom", col.slug)]),
    ),
  });

  // Preserves the pre-swap behavior where the trailing "N of M sessions"
  // cell only ever existed on rows carrying matched_sessions (search-match
  // context) -- the header column itself is only added when at least one
  // visible row needs it, so the common case (no search match context)
  // keeps the exact original column count.
  const hasMatchedSessions = createMemo(() => props.targets.some((t) => t.matched_sessions != null));

  const columns = createMemo<DataTableColumn<TargetAggregation>[]>(() => {
    const cols: DataTableColumn<TargetAggregation>[] = [
      {
        key: "name",
        label: "Target Name",
        sortable: true,
        alwaysVisible: true,
        render: (t) => (
          <span
            class={`inline-flex items-center gap-1.5 cursor-pointer hover:text-theme-accent transition-colors ${
              t.target_id === "obj:__uncategorized__" ? "text-theme-text-tertiary italic" : "text-theme-text-primary"
            }`}
            onClick={() => goToTarget(t)}
          >
            {getDisplayName(t)}
            {t.mosaic_id && (
              <A href={`/mosaics/${t.mosaic_id}`} class="text-theme-accent" title={`Mosaic: ${t.mosaic_name}`} onClick={(e) => e.stopPropagation()}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="2" y="2" width="9" height="9" rx="1" /><rect x="13" y="2" width="9" height="9" rx="1" />
                  <rect x="2" y="13" width="9" height="9" rx="1" /><rect x="13" y="13" width="9" height="9" rx="1" />
                </svg>
              </A>
            )}
          </span>
        ),
      },
      {
        key: "designation",
        label: "Designation",
        render: (t) => (
          <span class="font-mono text-theme-text-secondary text-xs cursor-pointer" onClick={() => goToTarget(t)}>
            {t.target_id === "obj:__uncategorized__" ? "" : t.primary_name}
          </span>
        ),
      },
      {
        key: "palette",
        label: "Palette",
        render: (t) => (
          <span class="cursor-pointer" onClick={() => goToTarget(t)}>
            <FilterBadges distribution={t.filter_distribution} compact />
          </span>
        ),
      },
      {
        key: "integration",
        label: "Integration Time",
        sortable: true,
        align: "right",
        render: (t) => (
          <span class="text-theme-text-primary text-xs cursor-pointer" onClick={() => goToTarget(t)}>
            {formatIntegration(t.total_integration_seconds)}
          </span>
        ),
      },
      {
        key: "equipment",
        label: "Equipment Profile",
        sortable: true,
        render: (t) => (
          <span class="text-theme-accent text-xs cursor-pointer" onClick={() => goToTarget(t)}>
            {t.equipment.join(" · ")}
          </span>
        ),
      },
      {
        key: "lastSession",
        label: `Last Session (${tzLabel()})`,
        sortable: true,
        align: "right",
        render: (t) => (
          <span class="text-theme-accent text-xs cursor-pointer" onClick={() => goToTarget(t)}>
            {getLastSession(t)}
          </span>
        ),
      },
      ...targetCustomColumns().map((col): DataTableColumn<TargetAggregation> => ({
        key: col.slug,
        label: col.name,
        align: "right",
        render: (t) => (
          <div onClick={(e) => e.stopPropagation()}>
            <InlineEditCell
              columnType={col.column_type}
              value={t.custom_values?.[col.slug]}
              dropdownOptions={col.dropdown_options}
              onSave={(val) => setCustomValueMutation.mutateAsync({
                column_id: col.id,
                target_id: t.target_id,
                value: val,
              }).then(() => undefined)}
            />
          </div>
        ),
      })),
    ];
    if (hasMatchedSessions()) {
      cols.push({
        key: "matched_sessions",
        label: "",
        alwaysVisible: true,
        render: (t) =>
          t.matched_sessions != null ? (
            <span class="text-xs text-theme-warning">{t.matched_sessions} of {t.total_sessions} sessions</span>
          ) : null,
      });
    }
    return cols;
  });

  return (
    <>
      <div class="hidden md:block">
        <DataTable
          columns={columns()}
          rows={props.targets}
          rowKey={(t) => t.target_id}
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={(key) => toggleSort(key as SortKey)}
          visibility={resolvedVisibility}
          columnPicker={{
            table: "dashboard",
            builtinColumns: [
              { key: "name", label: "Target Name", alwaysVisible: true },
              { key: "designation", label: "Designation" },
              { key: "palette", label: "Palette" },
              { key: "integration", label: "Integration Time" },
              { key: "equipment", label: "Equipment Profile" },
              { key: "last_session", label: "Last Session" },
            ],
            customColumns: targetCustomColumns(),
            visibility: vis(),
            onToggle: handleColumnToggle,
          }}
        />
      </div>
      <div class="md:hidden">
        <For each={props.targets}>
          {(target) => (
            <TargetRow target={target} />
          )}
        </For>
      </div>
    </>
  );
};

export default TargetTable;
