import { Component, For, createMemo } from "solid-js";
import type { TimelineEntry } from "../types";

const ImagingTimeline: Component<{ timeline: TimelineEntry[] }> = (props) => {
  const maxVal = () => Math.max(...props.timeline.map((t) => t.integration_seconds), 1);

  const labelInterval = createMemo(() => {
    const len = props.timeline.length;
    if (len <= 12) return 1;
    if (len <= 18) return 2;
    if (len <= 30) return 3;
    return 4;
  });

  const formatLabel = (month: string) => {
    // "2023-02" → "Feb 23"
    const [y, m] = month.split("-");
    const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${names[parseInt(m, 10) - 1]} ${y}`;
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <h3 class="text-white font-medium text-sm">Imaging Timeline</h3>
      <div>
        {/* Bars */}
        <div class="flex items-end gap-[2px] h-36">
          <For each={props.timeline}>
            {(entry) => {
              const pct = () => (entry.integration_seconds / maxVal()) * 100;
              return (
                <div
                  class="flex-1 h-full flex items-end"
                  title={`${formatLabel(entry.month)}: ${(entry.integration_seconds / 3600).toFixed(1)}h`}
                >
                  <div
                    class="w-full bg-theme-accent rounded-t min-h-[2px]"
                    style={{ height: `${pct()}%` }}
                  />
                </div>
              );
            }}
          </For>
        </div>
        {/* Labels */}
        <div class="flex gap-[2px] mt-1">
          <For each={props.timeline}>
            {(entry, i) => (
              <div class="flex-1 text-center">
                <span class="text-[7px] text-theme-text-secondary whitespace-nowrap">
                  {i() % labelInterval() === 0 ? formatLabel(entry.month) : ""}
                </span>
              </div>
            )}
          </For>
        </div>
      </div>
    </div>
  );
};

export default ImagingTimeline;
