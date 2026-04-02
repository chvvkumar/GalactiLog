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
      {/* Desktop table row -- hidden below md */}
      <tr
        class="border-b border-theme-border cursor-pointer hover:bg-theme-hover transition-colors duration-150 hidden md:table-row"
        onClick={() => navigate(`/targets/${encodeURIComponent(props.target.target_id)}?view=sessions`)}
      >
        <td class={`py-2.5 px-3 font-bold hover:text-theme-accent transition-colors ${
          props.target.target_id === "obj:__uncategorized__"
            ? "text-theme-text-tertiary italic"
            : "text-theme-text-primary"
        }`}>
          <span class="inline-flex items-center gap-1.5">
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
        </td>
        <td class="py-2.5 px-3 font-mono text-theme-text-secondary text-xs">
          {props.target.target_id === "obj:__uncategorized__" ? "" : props.target.primary_name}
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

      {/* Mobile card -- shown below md */}
      <tr
        class="md:hidden border-b border-theme-border cursor-pointer hover:bg-theme-hover transition-colors duration-150"
        onClick={() => navigate(`/targets/${encodeURIComponent(props.target.target_id)}?view=sessions`)}
      >
        <td colspan="7" class="p-3">
          <div class="space-y-1.5">
            <div class="flex items-start justify-between gap-2">
              <span class={`font-bold text-sm hover:text-theme-accent transition-colors inline-flex items-center gap-1.5 ${
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
              <div class="text-theme-accent text-xs">{props.target.equipment.join(" \u00b7 ")}</div>
            </Show>
            <Show when={props.target.matched_sessions != null}>
              <div class="text-xs text-theme-warning">
                {props.target.matched_sessions} of {props.target.total_sessions} sessions
              </div>
            </Show>
          </div>
        </td>
      </tr>

      {/* Expanded session table (both layouts) */}
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
