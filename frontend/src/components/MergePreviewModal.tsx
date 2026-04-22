import { Component, Show, createSignal, onMount, For } from "solid-js";
import { api } from "../api/client";
import { showToast } from "./Toast";

interface TargetPreview {
  id?: string;
  primary_name: string;
  object_type?: string | null;
  constellation?: string | null;
  image_count: number;
  session_count: number;
  integration_seconds: number;
  aliases: string[];
}

interface MergePreviewData {
  winner: TargetPreview;
  loser: TargetPreview;
  images_to_move: number;
  aliases_to_add: string[];
  mosaic_panels_to_move: number;
}

interface MergePreviewModalProps {
  winnerId?: string;
  loserId?: string;
  loserName?: string;
  onClose: () => void;
  onMerged: () => void;
}

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  if (h < 1) return `${Math.round(seconds / 60)}m`;
  return `${h.toFixed(1)}h`;
}

const MergePreviewModal: Component<MergePreviewModalProps> = (props) => {
  const [preview, setPreview] = createSignal<MergePreviewData | null>(null);
  const [loading, setLoading] = createSignal(true);
  const [error, setError] = createSignal<string | null>(null);
  const [swapped, setSwapped] = createSignal(false);
  const [merging, setMerging] = createSignal(false);

  const effectiveWinnerId = () => swapped() ? props.loserId : props.winnerId;
  const effectiveLoserId = () => swapped() ? props.winnerId : props.loserId;

  const loadPreview = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.mergePreview(
        effectiveWinnerId()!,
        effectiveLoserId(),
        props.loserName,
      );
      setPreview(data);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load preview");
    } finally {
      setLoading(false);
    }
  };

  onMount(() => {
    loadPreview();
  });

  const handleSwap = async () => {
    setSwapped((s) => !s);
    await loadPreview();
  };

  const handleMerge = async () => {
    setMerging(true);
    try {
      await api.mergeTargets(
        effectiveWinnerId()!,
        effectiveLoserId(),
        props.loserName,
      );
      const p = preview();
      showToast(
        p
          ? `Merged "${p.loser.primary_name}" into "${p.winner.primary_name}"`
          : "Merge complete"
      );
      props.onMerged();
    } catch (e: any) {
      showToast(e?.message ?? "Merge failed", "error");
    } finally {
      setMerging(false);
    }
  };

  const canSwap = () => !!props.loserId;

  const labelClass = "block text-xs text-theme-text-secondary mb-0.5";
  const valueClass = "text-sm text-theme-text-primary";

  return (
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-2xl w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h3 class="text-theme-text-primary font-medium">Preview Merge</h3>
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
                      <span class={valueClass}>{formatHours(p().winner.integration_seconds)}</span>
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
                      <span class={valueClass}>{formatHours(p().loser.integration_seconds)}</span>
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

                <div class="text-xs px-2 py-1.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
                  This merge can be reverted from Settings &gt; Target Merges.
                </div>
              </>
            )}
          </Show>

          <div class="flex justify-end gap-2 pt-1">
            <button
              onClick={props.onClose}
              class="px-3 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleMerge}
              disabled={merging() || loading() || !!error() || !preview()}
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

export default MergePreviewModal;
