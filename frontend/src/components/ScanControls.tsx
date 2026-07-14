import { Component, Show } from "solid-js";
import { useAuth } from "./AuthProvider";
import Button from "./ui/Button";

type FrameFilter = "all" | "light_only";

const ScanControls: Component<{
  isActive: boolean;
  stopping: boolean;
  rebuildRunning: boolean;
  frameFilter: FrameFilter;
  forceOrphanCleanup: boolean;
  onFrameFilterChange: (filter: FrameFilter) => void;
  onForceOrphanCleanupChange: (value: boolean) => void;
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
        <div class="flex flex-col gap-1 w-full">
          <label class="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={props.forceOrphanCleanup}
              onChange={(e) => props.onForceOrphanCleanupChange(e.currentTarget.checked)}
              disabled={props.isActive}
              class="accent-astro-accent"
            />
            <span class={`text-xs ${props.forceOrphanCleanup ? "text-theme-text-primary" : "text-theme-text-secondary"}`}>
              Force orphan cleanup
            </span>
          </label>
          <p class="text-xs text-theme-text-tertiary">
            Remove catalogued records for all files missing from disk, even past the 50% safety limit. Use after deleting files on purpose.
          </p>
        </div>
      </Show>
      <Show when={isAdmin()}>
        <div class="flex gap-2 flex-shrink-0 ml-auto">
          <Show when={props.isActive || props.rebuildRunning}>
            <Button variant="danger" onClick={props.onStopScan} disabled={props.stopping}>
              {props.stopping ? "Stopping..." : "Stop"}
            </Button>
          </Show>
          <Button variant="primary" onClick={props.onStartScan} disabled={props.isActive}>
            {props.isActive ? (props.stopping ? "Stopping..." : "Scanning...") : "Scan Directory"}
          </Button>
        </div>
      </Show>
    </>
  );
};

export default ScanControls;
