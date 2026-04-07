// frontend/src/components/settings/SuggestionsBanner.tsx
import { For, Show, createSignal, type Component } from "solid-js";
import type { SuggestionGroup } from "../../types";

interface Props {
  suggestions: SuggestionGroup[];
  onMerge: (canonical: string, aliases: string[], section?: string) => void;
  onDismiss?: (group: SuggestionGroup) => void;
}

export const SuggestionsBanner: Component<Props> = (props) => {
  return (
    <Show when={props.suggestions.length > 0}>
      <div class="bg-theme-warning/20 border border-theme-warning/50 rounded-[var(--radius-md)] p-4 space-y-3">
        <p class="text-sm text-theme-warning">
          Found {props.suggestions.length} possible duplicate{props.suggestions.length > 1 ? "s" : ""}
        </p>
        <For each={props.suggestions}>
          {(group) => <MergeGroup group={group} onMerge={props.onMerge} onDismiss={props.onDismiss} />}
        </For>
      </div>
    </Show>
  );
};

const MergeGroup: Component<{ group: SuggestionGroup; onMerge: (canonical: string, aliases: string[], section?: string) => void; onDismiss?: (group: SuggestionGroup) => void }> = (
  props,
) => {
  const [selected, setSelected] = createSignal(
    // Default to the variant with the highest count
    props.group.group.reduce((a, b) => ((props.group.counts[a] || 0) >= (props.group.counts[b] || 0) ? a : b)),
  );

  const handleMerge = () => {
    const canonical = selected();
    const aliases = props.group.group.filter((n) => n !== canonical);
    props.onMerge(canonical, aliases, props.group.section);
  };

  return (
    <div class="flex flex-wrap items-center gap-2 text-sm">
      <For each={props.group.group}>
        {(name) => (
          <button
            onClick={() => setSelected(name)}
            class={`px-2 py-1 rounded border text-xs transition-colors ${
              selected() === name
                ? "border-theme-accent bg-theme-accent/20 text-white"
                : "border-theme-border text-theme-text-secondary hover:border-theme-border"
            }`}
          >
            {name}
            <span class="ml-1 text-theme-text-tertiary">({props.group.counts[name] || 0})</span>
          </button>
        )}
      </For>
      <button
        onClick={handleMerge}
        class="px-2 py-1 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 text-xs rounded font-medium hover:bg-theme-accent/25 transition-colors"
      >
        Merge
      </button>
      <Show when={props.onDismiss}>
        <button
          onClick={() => props.onDismiss?.(props.group)}
          class="px-2 py-1 border border-theme-border text-theme-text-secondary text-xs rounded hover:border-theme-error hover:text-theme-error transition-colors"
        >
          Dismiss
        </button>
      </Show>
    </div>
  );
};
