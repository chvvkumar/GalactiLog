import { Component, Show, createMemo } from "solid-js";
import { A, useNavigate } from "@solidjs/router";
// Kept on the OLD hand-written TargetAggregation -- see TargetTable.tsx's
// top-of-file comment (same DashboardFilterProvider precedent/cast).
import type { TargetAggregation } from "../types";
import { useCatalog } from "../store/catalog";
import FilterBadges from "./FilterBadges";
import SessionTable from "./SessionTable";
import { formatIntegration } from "../utils/format";

// Mobile-only card for a single target. Desktop rendering moved into
// TargetTable.tsx's DataTable columns (T5 swap) -- this component now only
// covers the below-`md` card + its expandable session sub-panel, which is
// NOT folded into DataTable: a mobile card followed by an optional
// expand-in-place session table is two stacked blocks per target, a shape
// DataTable's one-row-per-item column model can't represent. See
// TargetTable.tsx's top-of-file comment and the slice-5 report for detail.
const TargetRow: Component<{
  target: TargetAggregation;
}> = (props) => {
  const { expandedTargets, toggleExpanded } = useCatalog();
  const navigate = useNavigate();

  const isOpen = () => expandedTargets().has(props.target.target_id);

  const displayName = () =>
    props.target.aliases[0] || props.target.primary_name;

  const lastSession = createMemo(() => {
    const sorted = [...props.target.sessions].sort(
      (a, b) => b.session_date.localeCompare(a.session_date)
    );
    return sorted[0]?.session_date ?? "—";
  });

  return (
    <>
      <div
        class="border-b border-theme-border cursor-pointer hover:bg-theme-hover transition-colors duration-150"
        onClick={() => navigate(`/targets/${encodeURIComponent(props.target.target_id)}?view=sessions`)}
      >
        <div class="p-3 space-y-1.5">
          <div class="flex items-start justify-between gap-2">
            <span class={`text-sm hover:text-theme-accent transition-colors inline-flex items-center gap-1.5 ${
              props.target.target_id === "obj:__uncategorized__"
                ? "text-theme-text-tertiary italic"
                : "text-theme-text-primary"
            }`}>
              {displayName()}
              {props.target.mosaic_id && (
                <A href={`/mosaics/${props.target.mosaic_id}`} class="text-theme-accent" title={`Mosaic: ${props.target.mosaic_name}`} onClick={(e) => e.stopPropagation()}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="2" y="2" width="9" height="9" rx="1" /><rect x="13" y="2" width="9" height="9" rx="1" />
                    <rect x="2" y="13" width="9" height="9" rx="1" /><rect x="13" y="13" width="9" height="9" rx="1" />
                  </svg>
                </A>
              )}
            </span>
            <button
              class="px-2 py-0.5 border border-theme-border-em rounded text-label text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-accent transition-colors flex-shrink-0"
              onClick={(e) => { e.stopPropagation(); toggleExpanded(props.target.target_id); }}
            >
              {isOpen() ? "Collapse" : "Expand"}
            </button>
          </div>
          <Show when={props.target.target_id !== "obj:__uncategorized__"}>
            <div class="font-mono text-theme-text-secondary text-xs">{props.target.primary_name}</div>
          </Show>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span class="text-theme-text-primary">{formatIntegration(props.target.total_integration_seconds)}</span>
            <span class="text-theme-accent">{lastSession()}</span>
          </div>
          <FilterBadges distribution={props.target.filter_distribution} compact />
          <Show when={props.target.equipment.length > 0}>
            <div class="text-theme-accent text-xs">{props.target.equipment.join(" · ")}</div>
          </Show>
          <Show when={props.target.matched_sessions != null}>
            <div class="text-xs text-theme-warning">
              {props.target.matched_sessions} of {props.target.total_sessions} sessions
            </div>
          </Show>
        </div>
      </div>

      <Show when={isOpen()}>
        <div class="bg-theme-surface px-3 py-2 border-b border-theme-border">
          <SessionTable
            sessions={props.target.sessions}
            onDeepDive={(date) => {
              navigate(`/targets/${encodeURIComponent(props.target.target_id)}?session=${date}`);
            }}
          />
        </div>
      </Show>
    </>
  );
};

export default TargetRow;
