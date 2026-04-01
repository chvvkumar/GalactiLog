import { Component, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { DbSummary } from "../types";

const DatabaseOverview: Component<{ summary: DbSummary | null }> = (props) => {
  const navigate = useNavigate();

  return (
    <Show when={props.summary}>
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
        <div class="flex flex-wrap gap-4 justify-around">
          <StatTile label="Total Images" value={props.summary!.total_images} />
          <StatTile label="Light Frames" value={props.summary!.light_frames} />
          <StatTile label="Targets" value={props.summary!.resolved_targets} />
          <StatTile
            label="Unresolved"
            value={props.summary!.unresolved_images}
            warn={props.summary!.unresolved_images > 0}
            title="Light frames whose OBJECT name could not be matched to a known target in SIMBAD."
            onClick={() => navigate("/?object_type=Unresolved")}
          />
          <StatTile label="From CSV" value={props.summary!.csv_enriched} info />
        </div>
        <Show when={props.summary!.cached_simbad > 0 || props.summary!.cached_vizier > 0 || props.summary!.pending_merges > 0}>
          <div class="flex gap-4 mt-3 text-xs text-theme-text-secondary justify-center flex-wrap">
            <Show when={props.summary!.cached_simbad > 0}>
              <span title={`${props.summary!.cached_simbad} SIMBAD lookups cached locally. ${props.summary!.cached_negative} returned no match.`}>
                {props.summary!.cached_simbad} SIMBAD cached ({props.summary!.cached_negative} negative)
              </span>
            </Show>
            <Show when={props.summary!.cached_vizier > 0}>
              <span title={`${props.summary!.cached_vizier} VizieR lookups cached locally. ${props.summary!.cached_vizier_negative} returned no data.`}>
                {props.summary!.cached_vizier} VizieR cached ({props.summary!.cached_vizier_negative} negative)
              </span>
            </Show>
            <Show when={props.summary!.pending_merges > 0}>
              <span
                class="text-theme-warning cursor-pointer hover:underline"
                onClick={() => navigate("/settings?tab=merges")}
              >
                {props.summary!.pending_merges} pending merges
              </span>
            </Show>
          </div>
        </Show>
      </div>
    </Show>
  );
};

const StatTile: Component<{
  label: string;
  value: number;
  warn?: boolean;
  info?: boolean;
  title?: string;
  onClick?: () => void;
}> = (props) => {
  const clickable = () => !!props.onClick;
  return (
    <div
      class={`text-center min-w-[5rem] ${clickable() ? "cursor-pointer hover:opacity-80" : ""}`}
      title={props.title}
      onClick={props.onClick}
    >
      <div class={`text-sm font-medium ${
        props.warn ? "text-theme-warning" :
        props.info ? "text-theme-info" :
        "text-theme-text-primary"
      }`}>
        {props.value.toLocaleString()}
      </div>
      <div class={`text-xs text-theme-text-secondary ${clickable() ? "underline decoration-dotted" : ""}`}>
        {props.label}
      </div>
    </div>
  );
};

export default DatabaseOverview;
