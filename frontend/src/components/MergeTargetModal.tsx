import { Component, Show, createSignal, For } from "solid-js";
import { api } from "../api/client";
import { showToast } from "./Toast";
import type { TargetSearchResultFuzzy } from "../types";

interface Props {
  targetId: string;
  targetName: string;
  onClose: () => void;
  onMerged: () => void;
}

const MergeTargetModal: Component<Props> = (props) => {
  const [searchQuery, setSearchQuery] = createSignal("");
  const [searchResults, setSearchResults] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [selectedTarget, setSelectedTarget] = createSignal<TargetSearchResultFuzzy | null>(null);
  const [searching, setSearching] = createSignal(false);
  const [merging, setMerging] = createSignal(false);

  let searchTimeout: ReturnType<typeof setTimeout>;

  const handleSearch = (q: string) => {
    setSearchQuery(q);
    setSelectedTarget(null);
    clearTimeout(searchTimeout);
    if (q.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    searchTimeout = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await api.searchTargets(q.trim());
        setSearchResults(results.filter((t) => t.id !== props.targetId));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const handleMerge = async () => {
    const target = selectedTarget();
    if (!target) return;
    setMerging(true);
    try {
      await api.mergeTargets(props.targetId, target.id);
      showToast(`Merged "${target.primary_name}" into "${props.targetName}"`);
      props.onMerged();
    } catch {
      showToast("Merge failed", "error");
    } finally {
      setMerging(false);
    }
  };

  const inputClass =
    "w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:border-theme-accent focus:outline-none";
  const labelClass = "block text-xs text-theme-text-secondary mb-1";

  return (
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 class="text-theme-text-primary font-medium">
            Merge into "{props.targetName}"
          </h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            Select a target to merge into this one. All images and sessions from the selected target will be moved here, and the selected target will be removed.
          </p>
        </div>

        <div class="p-4 space-y-3">
          <div class="text-xs px-2 py-1.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
            The selected target's images and sessions will be moved into "{props.targetName}". You can revert this later from Settings &gt; Target Merges.
          </div>

          <div>
            <label class={labelClass}>Search for target to merge</label>
            <input
              type="text"
              class={inputClass}
              value={searchQuery()}
              onInput={(e) => handleSearch(e.currentTarget.value)}
              placeholder="Type to search targets..."
            />
          </div>

          <Show when={searching()}>
            <p class="text-xs text-theme-text-secondary">Searching...</p>
          </Show>

          <Show when={searchResults().length > 0}>
            <div class="border border-theme-border rounded-[var(--radius-sm)] max-h-48 overflow-y-auto">
              <For each={searchResults()}>
                {(t) => (
                  <button
                    onClick={() => setSelectedTarget(t)}
                    class={`w-full text-left px-3 py-2 text-sm border-b border-theme-border last:border-b-0 transition-colors ${
                      selectedTarget()?.id === t.id
                        ? "bg-theme-accent/10 text-theme-accent"
                        : "text-theme-text-primary hover:bg-theme-hover"
                    }`}
                  >
                    <span class="font-medium">{t.primary_name}</span>
                    <Show when={t.object_type}>
                      <span class="text-xs text-theme-text-secondary ml-2">{t.object_type}</span>
                    </Show>
                  </button>
                )}
              </For>
            </div>
          </Show>

          <Show when={searchQuery().trim().length >= 2 && !searching() && searchResults().length === 0}>
            <p class="text-xs text-theme-text-secondary">No targets found</p>
          </Show>

          <div class="flex justify-end gap-2 pt-2">
            <button
              onClick={props.onClose}
              class="px-3 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleMerge}
              disabled={merging() || !selectedTarget()}
              class="px-3 py-1.5 text-sm bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded-[var(--radius-sm)] hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
            >
              {merging() ? "Merging..." : "Merge"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MergeTargetModal;
