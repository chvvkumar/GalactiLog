import { Component, For, Show, createSignal } from "solid-js";
import type { Accessor } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { MergeCandidateResponse } from "../../types";

interface MergeHistorySectionProps {
  candidates: Accessor<MergeCandidateResponse[]>;
  onAction: () => void;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

const MergeHistorySection: Component<MergeHistorySectionProps> = (props) => {
  const { isAdmin } = useAuth();
  const [expanded, setExpanded] = createSignal(false);

  const handleUndo = async (candidateId: string) => {
    try {
      await api.revertMergeCandidate(candidateId);
      showToast("Merge reverted");
      props.onAction();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Undo failed", "error");
    }
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)]">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        class="w-full flex items-center justify-between p-4 text-left cursor-pointer select-none"
      >
        <h3 class="text-theme-text-primary font-medium">
          Merge History ({props.candidates().length})
        </h3>

        {/* Chevron */}
        <svg
          class={`w-4 h-4 text-theme-text-secondary transition-transform duration-200 ${
            expanded() ? "rotate-180" : ""
          }`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fill-rule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clip-rule="evenodd"
          />
        </svg>
      </button>

      <div
        class={`grid transition-[grid-template-rows] duration-200 ${
          expanded() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div class="overflow-hidden">
          <div class="px-4 pb-4 space-y-3">
            <Show
              when={props.candidates().length > 0}
              fallback={
                <p class="text-sm text-theme-text-secondary py-2">No merge history.</p>
              }
            >
              <div class="space-y-2">
                <For each={props.candidates()}>
                  {(c) => {
                    const mergedDate = () => c.resolved_at || c.created_at;

                    return (
                      <div class="flex items-start justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                        <div class="flex-1 min-w-0">
                          {/* Names: SOURCE -> TARGET */}
                          <div class="flex items-center gap-1 flex-wrap mb-1">
                            <span class="text-sm font-medium text-theme-text-primary">
                              {c.source_name}
                            </span>
                            <Show when={c.suggested_target_name}>
                              <span class="text-theme-text-tertiary text-xs mx-1">&rarr;</span>
                              <span class="text-sm font-medium text-theme-accent">
                                {c.suggested_target_name}
                              </span>
                            </Show>
                          </div>

                          {/* Date + image count */}
                          <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-xs text-theme-text-secondary">
                              Merged on {formatDate(mergedDate())}
                            </span>
                            <span class="text-xs text-theme-text-secondary">
                              {c.source_image_count} {c.source_image_count === 1 ? "image" : "images"}
                            </span>
                          </div>
                        </div>

                        {/* Admin undo action */}
                        <Show when={isAdmin()}>
                          <div class="flex gap-1.5 ml-3 flex-shrink-0">
                            <button
                              onClick={() => handleUndo(c.id)}
                              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                            >
                              Undo Merge
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
        </div>
      </div>
    </div>
  );
};

export default MergeHistorySection;
