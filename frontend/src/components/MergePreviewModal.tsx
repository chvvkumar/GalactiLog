import { Component, Show, createSignal, For } from "solid-js";
import { useQuery, useMutation, useQueryClient } from "@tanstack/solid-query";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { queryKeys } from "../api/queryKeys";
import { showToast } from "./Toast";
import Dialog from "./Dialog";
import Button from "./ui/Button";
import { formatIntegration } from "../utils/format";
import { getErrorMessage } from "../utils/errors";

interface MergePreviewModalProps {
  winnerId?: string;
  loserId?: string;
  loserName?: string;
  onClose: () => void;
  onMerged: () => void;
}

const MergePreviewModal: Component<MergePreviewModalProps> = (props) => {
  const queryClient = useQueryClient();
  const [swapped, setSwapped] = createSignal(false);

  const effectiveWinnerId = () => swapped() ? props.loserId : props.winnerId;
  const effectiveLoserId = () => swapped() ? props.winnerId : props.loserId;

  // Reactive on effectiveWinnerId/effectiveLoserId, so toggling `swapped`
  // (the winner/loser radio) re-derives the query key and refetches --
  // replacing the old code's explicit `loadPreview()` call inside
  // `handleSwap` (and the `onMount` call for the initial load).
  const previewQuery = useQuery(() => ({
    queryKey: queryKeys.mergePreview(effectiveWinnerId() ?? "", effectiveLoserId(), props.loserName),
    queryFn: () =>
      apiClient
        .POST("/api/targets/merge-preview", {
          body: {
            winner_id: effectiveWinnerId()!,
            ...(effectiveLoserId() ? { loser_id: effectiveLoserId() } : {}),
            ...(props.loserName ? { loser_name: props.loserName } : {}),
          },
        })
        .then(unwrap),
    enabled: !!effectiveWinnerId(),
  }));
  const preview = () => previewQuery.data ?? null;
  const loading = () => previewQuery.isFetching;
  const error = () => (previewQuery.error ? getErrorMessage(previewQuery.error, "Failed to load preview") : null);

  const handleSwap = () => setSwapped((s) => !s);

  const mergeMutation = useMutation(() => ({
    mutationFn: () =>
      apiClient
        .POST("/api/targets/merge", {
          body: {
            winner_id: effectiveWinnerId()!,
            ...(effectiveLoserId() ? { loser_id: effectiveLoserId() } : {}),
            ...(props.loserName ? { loser_name: props.loserName } : {}),
          },
        })
        .then(unwrap),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["targets"] });
      const p = preview();
      showToast(
        p
          ? `Merged "${p.loser.primary_name}" into "${p.winner.primary_name}"`
          : "Merge complete"
      );
      props.onMerged();
    },
    onError: (e: unknown) => {
      showToast(getErrorMessage(e, "Merge failed"), "error");
    },
  }));
  const merging = () => mergeMutation.isPending;
  const handleMerge = () => { mergeMutation.mutate(); };

  const canSwap = () => !!props.loserId;

  const labelClass = "block text-xs text-theme-text-secondary mb-0.5";
  const valueClass = "text-sm text-theme-text-primary";

  return (
    <Dialog open aria-labelledby="merge-preview-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 id="merge-preview-title" class="text-theme-text-primary font-medium">Preview Merge</h3>
          <p class="text-xs text-theme-text-secondary mt-1">
            Review what will happen before confirming the merge.
          </p>
        </div>

        <div class="p-4 space-y-4">
          <Show when={loading()}>
            <div class="text-sm text-theme-text-secondary py-8 text-center">
              Loading preview...
            </div>
          </Show>

          <Show when={error()}>
            <div class="text-sm text-red-400 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded">
              {error()}
            </div>
          </Show>

          <Show when={!loading() && !error() && preview()}>
            {(p) => (
              <>
                <div class="grid grid-cols-2 gap-3">
                  {/* Winner column */}
                  <div class="bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)] p-3 space-y-2">
                    <div class="flex items-center gap-2 mb-1">
                      <Show when={canSwap()}>
                        <input
                          type="radio"
                          id="winner-radio"
                          name="winner-choice"
                          checked={!swapped()}
                          onChange={() => !swapped() || handleSwap()}
                          class="accent-[var(--color-accent)]"
                        />
                      </Show>
                      <span class="text-xs font-medium text-green-400 uppercase tracking-wide">
                        Survives
                      </span>
                    </div>
                    <div>
                      <span class={labelClass}>Name</span>
                      <span class={`${valueClass} font-medium`}>{p().winner.primary_name}</span>
                    </div>
                    <Show when={p().winner.object_type}>
                      <div>
                        <span class={labelClass}>Type</span>
                        <span class={valueClass}>{p().winner.object_type}</span>
                      </div>
                    </Show>
                    <Show when={p().winner.constellation}>
                      <div>
                        <span class={labelClass}>Constellation</span>
                        <span class={valueClass}>{p().winner.constellation}</span>
                      </div>
                    </Show>
                    <div class="grid grid-cols-2 gap-2">
                      <div>
                        <span class={labelClass}>Images</span>
                        <span class={valueClass}>{p().winner.image_count}</span>
                      </div>
                      <div>
                        <span class={labelClass}>Sessions</span>
                        <span class={valueClass}>{p().winner.session_count}</span>
                      </div>
                    </div>
                    <div>
                      <span class={labelClass}>Integration</span>
                      <span class={valueClass}>{formatIntegration(p().winner.integration_seconds)}</span>
                    </div>
                    <Show when={p().winner.aliases.length > 0}>
                      <div>
                        <span class={labelClass}>Aliases</span>
                        <div class="flex flex-wrap gap-1 mt-0.5">
                          <For each={p().winner.aliases}>
                            {(a) => (
                              <span class="text-xs px-1.5 py-0.5 bg-theme-elevated border border-theme-border rounded text-theme-text-secondary">
                                {a}
                              </span>
                            )}
                          </For>
                        </div>
                      </div>
                    </Show>
                  </div>

                  {/* Loser column */}
                  <div class="bg-theme-base/30 border border-theme-border rounded-[var(--radius-sm)] p-3 space-y-2 opacity-80">
                    <div class="flex items-center gap-2 mb-1">
                      <Show when={canSwap()}>
                        <input
                          type="radio"
                          id="loser-radio"
                          name="winner-choice"
                          checked={swapped()}
                          onChange={() => swapped() || handleSwap()}
                          class="accent-[var(--color-accent)]"
                        />
                      </Show>
                      <span class="text-xs font-medium text-theme-text-tertiary uppercase tracking-wide">
                        Merged away
                      </span>
                    </div>
                    <div>
                      <span class={labelClass}>Name</span>
                      <span class={`${valueClass} font-medium`}>{p().loser.primary_name}</span>
                    </div>
                    <Show when={p().loser.object_type}>
                      <div>
                        <span class={labelClass}>Type</span>
                        <span class={valueClass}>{p().loser.object_type}</span>
                      </div>
                    </Show>
                    <Show when={p().loser.constellation}>
                      <div>
                        <span class={labelClass}>Constellation</span>
                        <span class={valueClass}>{p().loser.constellation}</span>
                      </div>
                    </Show>
                    <div class="grid grid-cols-2 gap-2">
                      <div>
                        <span class={labelClass}>Images</span>
                        <span class={valueClass}>{p().loser.image_count}</span>
                      </div>
                      <div>
                        <span class={labelClass}>Sessions</span>
                        <span class={valueClass}>{p().loser.session_count}</span>
                      </div>
                    </div>
                    <div>
                      <span class={labelClass}>Integration</span>
                      <span class={valueClass}>{formatIntegration(p().loser.integration_seconds)}</span>
                    </div>
                    <Show when={p().loser.aliases.length > 0}>
                      <div>
                        <span class={labelClass}>Aliases</span>
                        <div class="flex flex-wrap gap-1 mt-0.5">
                          <For each={p().loser.aliases}>
                            {(a) => (
                              <span class="text-xs px-1.5 py-0.5 bg-theme-elevated border border-theme-border rounded text-theme-text-secondary">
                                {a}
                              </span>
                            )}
                          </For>
                        </div>
                      </div>
                    </Show>
                  </div>
                </div>

                {/* What will happen summary */}
                <div class="bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)] p-3">
                  <p class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide mb-2">
                    What will happen
                  </p>
                  <ul class="space-y-1">
                    <li class="text-sm text-theme-text-primary">
                      {p().images_to_move} {p().images_to_move === 1 ? "image" : "images"} move to "{p().winner.primary_name}"
                    </li>
                    <Show when={p().aliases_to_add.length > 0}>
                      <li class="text-sm text-theme-text-primary">
                        {p().aliases_to_add.length} {p().aliases_to_add.length === 1 ? "alias" : "aliases"} added:{" "}
                        <span class="text-theme-text-secondary">{p().aliases_to_add.join(", ")}</span>
                      </li>
                    </Show>
                    <Show when={p().mosaic_panels_to_move > 0}>
                      <li class="text-sm text-theme-text-primary">
                        {p().mosaic_panels_to_move} mosaic {p().mosaic_panels_to_move === 1 ? "panel" : "panels"} reassigned
                      </li>
                    </Show>
                    <li class="text-sm text-theme-text-secondary">
                      "{p().loser.primary_name}" will be soft-deleted
                    </li>
                  </ul>
                </div>

                <div class="text-xs px-2 py-1.5 rounded bg-theme-warning/10 text-theme-warning border border-theme-warning/20">
                  This merge can be reverted from Settings &gt; Target Merges.
                </div>
              </>
            )}
          </Show>

          <div class="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={props.onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleMerge}
              disabled={merging() || loading() || !!error() || !preview()}
            >
              {merging() ? "Merging..." : "Merge"}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
};

export default MergePreviewModal;
