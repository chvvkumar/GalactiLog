import { Component, For, Show, createSignal, createEffect, on } from "solid-js";
import type { Accessor } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { MergeCandidateResponse, OrphanPreviewResponse } from "../../types";
import ResolveTargetModal from "./ResolveTargetModal";

interface UnresolvedSectionProps {
  candidates: Accessor<MergeCandidateResponse[]>;
  onAction: () => void;
}

interface PreviewState {
  loading: boolean;
  data: OrphanPreviewResponse | null;
  error: boolean;
}

const UnresolvedSection: Component<UnresolvedSectionProps> = (props) => {
  const { isAdmin } = useAuth();

  const [previews, setPreviews] = createSignal<Record<string, PreviewState>>({});
  const [resolveCandidate, setResolveCandidate] = createSignal<MergeCandidateResponse | null>(null);

  // Fetch SIMBAD previews when candidates change
  createEffect(
    on(
      () => props.candidates().map((c) => c.source_name).join(","),
      () => {
        const candidates = props.candidates();
        if (candidates.length === 0) {
          setPreviews({});
          return;
        }

        // Initialize loading state for each candidate
        const initial: Record<string, PreviewState> = {};
        for (const c of candidates) {
          // Preserve existing loaded data if candidate is still present
          const existing = previews()[c.source_name];
          if (existing && !existing.loading && !existing.error) {
            initial[c.source_name] = existing;
          } else {
            initial[c.source_name] = { loading: true, data: null, error: false };
          }
        }
        setPreviews(initial);

        // Fetch previews for candidates that need loading
        for (const c of candidates) {
          const existing = previews()[c.source_name];
          if (existing && !existing.loading && !existing.error) continue;

          api
            .orphanPreview(c.source_name)
            .then((res) => {
              setPreviews((prev) => ({
                ...prev,
                [c.source_name]: { loading: false, data: res, error: false },
              }));
            })
            .catch(() => {
              setPreviews((prev) => ({
                ...prev,
                [c.source_name]: { loading: false, data: null, error: true },
              }));
            });
        }
      },
    ),
  );

  const handleAssign = async (c: MergeCandidateResponse) => {
    if (!c.suggested_target_id) return;
    try {
      await api.mergeTargets(c.suggested_target_id, undefined, c.source_name);
      showToast(`Assigned "${c.source_name}" to "${c.suggested_target_name}"`);
      props.onAction();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Assign failed", "error");
    }
  };

  const handleDismiss = async (candidateId: string) => {
    try {
      await api.dismissMergeCandidate(candidateId);
      props.onAction();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Dismiss failed", "error");
    }
  };

  const handleCreateTarget = (c: MergeCandidateResponse) => {
    setResolveCandidate(c);
  };

  const handleResolved = async () => {
    setResolveCandidate(null);
    props.onAction();
    window.dispatchEvent(new Event("merges-changed"));
  };

  return (
    <>
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">
          Unresolved Names ({props.candidates().length})
        </h3>

        <Show
          when={props.candidates().length > 0}
          fallback={
            <p class="text-sm text-theme-text-secondary py-2">No unresolved names.</p>
          }
        >
          <div class="space-y-2">
            <For each={props.candidates()}>
              {(c) => {
                const preview = () => previews()[c.source_name];

                return (
                  <div class="flex items-start justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                    <div class="flex-1 min-w-0">
                      <span class="text-sm font-medium text-theme-text-primary">
                        {c.source_name}
                      </span>

                      <div class="text-xs text-theme-text-secondary mt-0.5">
                        {c.source_image_count} {c.source_image_count === 1 ? "image" : "images"}
                      </div>

                      {/* Inline SIMBAD preview */}
                      <div class="mt-1">
                        <Show when={preview()?.loading}>
                          <span class="text-xs text-theme-text-tertiary">Checking SIMBAD...</span>
                        </Show>
                        <Show when={preview() && !preview()!.loading && !preview()!.error}>
                          <Show
                            when={preview()!.data?.resolved}
                            fallback={
                              <span class="text-xs text-theme-text-tertiary">
                                No catalog match found
                              </span>
                            }
                          >
                            <span class="text-xs text-green-400">
                              SIMBAD match: {preview()!.data!.primary_name}
                            </span>
                          </Show>
                        </Show>
                        <Show when={preview() && !preview()!.loading && preview()!.error}>
                          <span class="text-xs text-theme-text-tertiary">
                            Lookup failed
                          </span>
                        </Show>
                      </div>
                    </div>

                    <Show when={isAdmin()}>
                      <div class="flex gap-1.5 ml-3 flex-shrink-0 flex-wrap justify-end">
                        <Show when={c.suggested_target_id}>
                          <button
                            onClick={() => handleAssign(c)}
                            class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                          >
                            Assign to {c.suggested_target_name ?? "target"}
                          </button>
                        </Show>
                        <button
                          onClick={() => handleCreateTarget(c)}
                          class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                        >
                          Create New Target
                        </button>
                        <button
                          onClick={() => handleDismiss(c.id)}
                          class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                        >
                          Dismiss
                        </button>
                      </div>
                    </Show>
                  </div>
                );
              }}
            </For>
          </div>
        </Show>
      </div>

      {/* ResolveTargetModal */}
      <Show when={resolveCandidate()}>
        {(c) => (
          <ResolveTargetModal
            candidate={c()}
            onClose={() => setResolveCandidate(null)}
            onResolved={handleResolved}
          />
        )}
      </Show>
    </>
  );
};

export default UnresolvedSection;
