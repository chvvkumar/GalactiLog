import { Component, Show, createMemo } from "solid-js";
import { A, useNavigate } from "@solidjs/router";
import type { TargetAggregation } from "../types";
import { useCatalog } from "../store/catalog";
import FilterBadges from "./FilterBadges";
import SessionTable from "./SessionTable";

function formatIntegration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h.toString().padStart(2, "0")}h ${m.toString().padStart(2, "0")}m`;
}

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
    return sorted[0]?.session_date ?? "\u2014";
  });

  return (
    <>
      <tr
        class="border-b border-theme-border cursor-pointer hover:bg-theme-hover transition-colors duration-150"
        onClick={() => navigate(`/targets/${encodeURIComponent(props.target.target_id)}?view=sessions`)}
      >
        <td class="py-2.5 px-3 font-bold text-theme-text-primary hover:text-theme-accent transition-colors">
          {displayName()}
        </td>
        <td class="py-2.5 px-3 font-mono text-theme-text-secondary text-xs">
          {props.target.primary_name}
        </td>
        <td class="py-2.5 px-3">
          <FilterBadges distribution={props.target.filter_distribution} compact />
        </td>
        <td class="py-2.5 px-3 text-theme-text-primary text-xs">
          {formatIntegration(props.target.total_integration_seconds)}
        </td>
        <td class="py-2.5 px-3 text-theme-accent text-xs">
          {props.target.equipment.join(" \u00b7 ")}
        </td>
        <td class="py-2.5 px-3 text-theme-accent text-xs">{lastSession()}</td>
        <td class="py-2.5 px-3">
          <button
            class="px-2.5 py-1 border border-theme-border-em rounded text-label text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-accent transition-colors"
            onClick={(e) => { e.stopPropagation(); toggleExpanded(props.target.target_id); }}
          >
            {isOpen() ? "Collapse" : "Expand"}
          </button>
        </td>
        <Show when={props.target.matched_sessions != null}>
          <td class="py-2.5 px-3 text-xs text-theme-warning">
            {props.target.matched_sessions} of {props.target.total_sessions} sessions
          </td>
        </Show>
      </tr>
      <Show when={isOpen()}>
        <tr class="bg-theme-surface">
          <td colspan="7" class="px-3 py-2">
            <SessionTable
              sessions={props.target.sessions}
              onDeepDive={(date) => {
                window.location.href = `/targets/${encodeURIComponent(props.target.target_id)}?session=${date}`;
              }}
            />
          </td>
        </tr>
      </Show>
    </>
  );
};

export default TargetRow;
