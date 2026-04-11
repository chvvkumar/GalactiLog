import { Component, Show } from "solid-js";
import { useAuth } from "./AuthProvider";

type FrameFilter = "all" | "light_only";

const ScanControls: Component<{
  isActive: boolean;
  stopping: boolean;
  frameFilter: FrameFilter;
  onFrameFilterChange: (filter: FrameFilter) => void;
  onStartScan: () => void;
  onStopScan: () => void;
}> = (props) => {
  const { isAdmin } = useAuth();

  return (
    <>
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
      <Show when={isAdmin()}>
        <div class="flex gap-2 flex-shrink-0 ml-auto">
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
            class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
          >
            {props.isActive ? (props.stopping ? "Stopping..." : "Scanning...") : "Scan Directory"}
          </button>
        </div>
      </Show>
    </>
  );
};

export default ScanControls;
