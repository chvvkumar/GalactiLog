import { Component, For, Show } from "solid-js";

interface FailedTarget {
  name: string;
  reason?: string;
}

const DISPLAY_LIMIT = 10;

const EnrichmentFailureList: Component<{ targets: FailedTarget[] }> = (props) => {
  const shown = () => props.targets.slice(0, DISPLAY_LIMIT);
  const overflow = () => props.targets.length - DISPLAY_LIMIT;

  return (
    <div class="space-y-1 mt-1 max-h-48 overflow-y-auto">
      <For each={shown()}>
        {(t) => (
          <div class="flex items-start gap-2 py-0.5">
            <span class="text-xs text-theme-text-primary font-medium">{t.name}</span>
            <Show when={t.reason}>
              <span class="text-xs text-theme-text-secondary">{t.reason}</span>
            </Show>
          </div>
        )}
      </For>
      <Show when={overflow() > 0}>
        <p class="text-xs text-theme-text-secondary pl-1">
          {overflow()} more target{overflow() > 1 ? "s" : ""}
        </p>
      </Show>
    </div>
  );
};

export default EnrichmentFailureList;
