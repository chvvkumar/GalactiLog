import { Component, Show } from "solid-js";

type FrameFilter = "all" | "light_only";

const ScanControls: Component<{
  isActive: boolean;
  stopping: boolean;
  frameFilter: FrameFilter;
  onFrameFilterChange: (filter: FrameFilter) => void;
  onStartScan: () => void;
  onStopScan: () => void;
}> = (props) => {
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Scan & Ingest</h3>
        <div class="flex gap-2 flex-shrink-0">
          <Show when={props.isActive}>
            <button
              onClick={props.onStopScan}
              disabled={props.stopping}
              class="px-4 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm font-medium hover:bg-theme-error/20 transition-colors disabled:opacity-50"
            >
              {props.stopping ? "Stopping..." : "Stop"}
            </button>
          </Show>
          <button
            onClick={props.onStartScan}
            disabled={props.isActive}
            class="px-4 py-1.5 bg-theme-accent text-theme-text-primary rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/80 transition-colors"
          >
            {props.isActive ? (props.stopping ? "Stopping..." : "Scanning...") : "Scan Directory"}
          </button>
        </div>
      </div>
      <div class="flex items-center gap-4 text-sm flex-wrap">
        <span class="text-theme-text-secondary text-xs">Include:</span>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="frame-filter"
            checked={props.frameFilter === "all"}
            onChange={() => props.onFrameFilterChange("all")}
            disabled={props.isActive}
            class="accent-astro-accent"
          />
          <span class={`text-xs ${props.frameFilter === "all" ? "text-theme-text-primary" : "text-theme-text-secondary"}`}>
            All frames
          </span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="frame-filter"
            checked={props.frameFilter === "light_only"}
            onChange={() => props.onFrameFilterChange("light_only")}
            disabled={props.isActive}
            class="accent-astro-accent"
          />
          <span class={`text-xs ${props.frameFilter === "light_only" ? "text-theme-text-primary" : "text-theme-text-secondary"}`}>
            Light frames only
          </span>
        </label>
      </div>
    </div>
  );
};

export default ScanControls;
