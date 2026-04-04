import { Component, Show } from "solid-js";
import type { TargetAggregation } from "../types";
import FilterBadges from "./FilterBadges";
import SessionTable from "./SessionTable";
import { useCatalog } from "../store/catalog";

import { formatIntegration } from "../utils/format";

const TargetCard: Component<{ target: TargetAggregation }> = (props) => {
  const { expandedTargets, toggleExpanded } = useCatalog();
  const isOpen = () => expandedTargets().has(props.target.target_id);

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <div
        class="flex items-center justify-between cursor-pointer"
        onClick={() => toggleExpanded(props.target.target_id)}
      >
        <div>
          <h3 class="text-theme-text-primary font-medium">{props.target.primary_name}</h3>
          <Show when={props.target.aliases.length > 0}>
            <p class="text-xs text-theme-text-secondary">{props.target.aliases.join(", ")}</p>
          </Show>
        </div>
        <div class="text-right text-sm">
          <span class="text-theme-text-primary font-semibold">{formatIntegration(props.target.total_integration_seconds)}</span>
          <span class="text-theme-text-secondary ml-2">{props.target.total_frames} frames</span>
        </div>
      </div>

      <FilterBadges distribution={props.target.filter_distribution} />

      <Show when={props.target.equipment.length > 0}>
        <div class="text-xs text-theme-text-secondary">
          {props.target.equipment.join(" / ")}
        </div>
      </Show>

      <Show when={isOpen()}>
        <SessionTable
          sessions={props.target.sessions}
          onDeepDive={(date) => {
            window.location.href = `/targets/${encodeURIComponent(props.target.target_id)}?session=${date}`;
          }}
        />
      </Show>
    </div>
  );
};

export default TargetCard;
