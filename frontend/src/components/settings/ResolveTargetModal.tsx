import { Component, Show, createSignal, createEffect, For } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import type { MergeCandidateResponse, OrphanPreviewResponse, TargetSearchResultFuzzy } from "../../types";
import Dialog from "../Dialog";
import TargetCreateForm, { TargetFormValues } from "./TargetCreateForm";
import { getErrorMessage } from "../../utils/errors";

interface Props {
  candidate: MergeCandidateResponse;
  initialMode?: "create" | "merge";
  onClose: () => void;
  onResolved: () => void;
}

const ResolveTargetModal: Component<Props> = (props) => {
  const isOrphan = () => props.candidate.suggested_target_id === null;
  const [mode, setMode] = createSignal<"create" | "merge">(
    props.initialMode ?? (isOrphan() ? "create" : "merge"),
  );

  // Create New Target state
  const [preview, setPreview] = createSignal<OrphanPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = createSignal(false);
  const [creating, setCreating] = createSignal(false);

  // Merge into Existing state
  const [searchQuery, setSearchQuery] = createSignal(
    props.candidate.suggested_target_name ?? props.candidate.source_name,
  );
  const [searchResults, setSearchResults] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [selectedTarget, setSelectedTarget] = createSignal<TargetSearchResultFuzzy | null>(null);
  const [searching, setSearching] = createSignal(false);
  const [merging, setMerging] = createSignal(false);

  createEffect(() => {
    if (mode() === "create" && !preview()) {
      loadPreview();
    }
  });

  // Run the prefilled search once when the merge tab first becomes active, so
  // likely matches appear without retyping the unresolved name.
  let searchedOnce = false;
  createEffect(() => {
    if (mode() === "merge" && !searchedOnce) {
      searchedOnce = true;
      const q = searchQuery().trim();
      if (q.length >= 2) handleSearch(q);
    }
  });

  const loadPreview = async () => {
    setLoadingPreview(true);
    try {
      const res = await api.orphanPreview(props.candidate.source_name);
      setPreview(res);
    } catch {
      showToast("Failed to load preview", "error");
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleCreate = async (values: TargetFormValues) => {
    setCreating(true);
    try {
      await api.orphanCreate({
        candidate_id: props.candidate.id,
        ...values,
      });
      showToast(`Created target "${values.primary_name}"`);
      props.onResolved();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Failed to create target"), "error");
    } finally {
      setCreating(false);
    }
  };

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
        setSearchResults(results);
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
      await api.mergeTargets(target.id, undefined, props.candidate.source_name);
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
    <Dialog open aria-labelledby="resolve-target-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 id="resolve-target-title" class="text-theme-text-primary font-medium">
            Resolve "{props.candidate.source_name}"
          </h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            {props.candidate.source_image_count} images
          </p>
        </div>

        <div class="flex border-b border-theme-border">
          <button
            onClick={() => setMode("create")}
            class={`flex-1 px-4 py-2 text-sm transition-colors ${
              mode() === "create"
                ? "text-theme-accent border-b-2 border-theme-accent font-medium"
                : "text-theme-text-secondary hover:text-theme-text-primary"
            }`}
          >
            Create New Target
          </button>
          <button
            onClick={() => setMode("merge")}
            class={`flex-1 px-4 py-2 text-sm transition-colors ${
              mode() === "merge"
                ? "text-theme-accent border-b-2 border-theme-accent font-medium"
                : "text-theme-text-secondary hover:text-theme-text-primary"
            }`}
          >
            Merge into Existing
          </button>
        </div>

        <div class="p-4">
          <Show when={mode() === "create"}>
            <Show when={!loadingPreview()} fallback={
              <div class="text-sm text-theme-text-secondary py-4 text-center">Querying SIMBAD...</div>
            }>
              <Show when={preview()}>
                {(p) => (
                  <div class="space-y-3">
                    <div class={`text-xs px-2 py-1 rounded ${
                      p().resolved
                        ? "bg-green-500/10 text-green-400 border border-green-500/20"
                        : "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"
                    }`}>
                      {p().resolved
                        ? `SIMBAD resolved as: ${p().primary_name}`
                        : "No catalog match, coordinates from FITS headers"}
                    </div>

                    <TargetCreateForm
                      initial={{
                        primary_name: p().primary_name,
                        ra: p().ra,
                        dec: p().dec,
                        object_type: p().object_type,
                        catalog_id: p().catalog_id,
                        user_defined: !p().resolved,
                      }}
                      submitLabel={creating() ? "Creating..." : "Create Target"}
                      submitting={creating()}
                      onSubmit={handleCreate}
                      onCancel={props.onClose}
                    />
                  </div>
                )}
              </Show>
            </Show>
          </Show>

          <Show when={mode() === "merge"}>
            <div class="space-y-3">
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
          </Show>
        </div>
      </div>
    </Dialog>
  );
};

export default ResolveTargetModal;
