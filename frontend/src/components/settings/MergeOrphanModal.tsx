import { Component, Show, For, createSignal, onMount } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { showToast } from "../Toast";
import type { MergeCandidateResponse, TargetSearchResultFuzzy } from "../../api/types";
import Dialog from "../Dialog";

interface Props {
  candidate: MergeCandidateResponse;
  onClose: () => void;
  onResolved: () => void;
}

const MergeOrphanModal: Component<Props> = (props) => {
  const [searchQuery, setSearchQuery] = createSignal(
    props.candidate.suggested_target_name ?? props.candidate.source_name,
  );
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
        const results = await apiClient
          .GET("/api/targets/search", { params: { query: { q: q.trim() } } })
          .then(unwrap);
        setSearchResults(results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  // Search the prefilled name immediately so likely matches appear without
  // retyping the unresolved name.
  onMount(() => {
    const q = searchQuery().trim();
    if (q.length >= 2) handleSearch(q);
  });

  const handleMerge = async () => {
    const target = selectedTarget();
    if (!target) return;
    setMerging(true);
    try {
      await apiClient
        .POST("/api/targets/merge", {
          body: { winner_id: target.id, loser_name: props.candidate.source_name },
        })
        .then(unwrap);
      showToast(`Merged "${props.candidate.source_name}" into "${target.primary_name}"`);
      props.onResolved();
    } catch {
      showToast("Merge failed", "error");
    } finally {
      setMerging(false);
    }
  };

  const inputClass = "w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:border-theme-accent focus:outline-none";
  const labelClass = "block text-xs text-theme-text-secondary mb-1";

  return (
    <Dialog open aria-labelledby="merge-orphan-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 id="merge-orphan-title" class="text-theme-text-primary font-medium">
            Merge "{props.candidate.source_name}" into existing target
          </h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            {props.candidate.source_image_count} images will move to the selected target and "{props.candidate.source_name}" becomes one of its aliases
          </p>
        </div>

        <div class="p-4 space-y-3">
          <div>
            <label class={labelClass}>Search for target</label>
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
    </Dialog>
  );
};

export default MergeOrphanModal;
