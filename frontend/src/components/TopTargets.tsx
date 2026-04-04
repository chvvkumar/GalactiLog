import { Component, For } from "solid-js";
import type { TopTarget } from "../types";
import { formatIntegration } from "../utils/format";

const TopTargets: Component<{ targets: TopTarget[] }> = (props) => {
  const maxVal = () => Math.max(...props.targets.map((t) => t.integration_seconds), 1);

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <h3 class="text-theme-text-primary font-medium text-sm">Top Targets</h3>
      <For each={props.targets.slice(0, 10)}>
        {(target, i) => (
          <div class="flex items-center gap-2 text-xs">
            <span class="w-4 text-theme-text-secondary text-right">{i() + 1}</span>
            <span class="w-24 text-theme-text-primary truncate">{target.name}</span>
            <div class="flex-1 bg-theme-base rounded-full h-3 overflow-hidden">
              <div
                class="bg-theme-accent h-3 rounded-full"
                style={{ width: `${(target.integration_seconds / maxVal()) * 100}%` }}
              />
            </div>
            <span class="w-16 text-right text-theme-text-secondary">{formatIntegration(target.integration_seconds)}</span>
          </div>
        )}
      </For>
    </div>
  );
};

export default TopTargets;
