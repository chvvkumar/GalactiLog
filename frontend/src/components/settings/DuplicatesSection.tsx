import { Component, For, Show, createSignal } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import type { MergeCandidateResponse } from "../../types";
import MergePreviewModal from "../MergePreviewModal";

interface DuplicatesSectionProps {
  candidates: () => MergeCandidateResponse[];
  onAction: () => void;
}

/** Extract a percentage number from a method string like "similar (87%)" or "trigram_87" */
function extractSimilarityPct(method: string, score: number): string {
  const pctMatch = method.match(/(\d+)%/);
  if (pctMatch) return `${pctMatch[1]}%`;
  // Fall back to the numeric similarity_score field
  if (score > 0 && score <= 1) return `${Math.round(score * 100)}%`;
  if (score > 1) return `${Math.round(score)}%`;
  return "";
}

interface BadgeInfo {
  label: string;
  subtitle: string;
  colorClasses: string;
}

function methodBadge(candidate: MergeCandidateResponse): BadgeInfo {
  const m = candidate.method.toLowerCase();

  if (m.includes("simbad") || m.includes("resolves")) {
    return {
      label: "Catalog Match",
      subtitle: "SIMBAD resolves both names to the same catalog object",
      colorClasses: "text-green-400 bg-green-500/10 border border-green-500/20",
    };
  }

  if (m.includes("similar") || m === "trigram") {
    const pct = extractSimilarityPct(candidate.method, candidate.similarity_score);
    return {
      label: pct ? `Name Similarity ${pct}` : "Name Similarity",
      subtitle: pct
        ? `Names are ${pct} similar by text matching`
        : "Names are similar by text matching",
      colorClasses: "text-yellow-400 bg-yellow-500/10 border border-yellow-500/20",
    };
  }

  if (m.includes("alias") || m === "duplicate") {
    const aliasText = candidate.reason_text || "Both targets share a common alias";
    return {
      label: "Shared Alias",
      subtitle: aliasText,
      colorClasses: "text-blue-400 bg-blue-500/10 border border-blue-500/20",
    };
  }

  return {
    label: candidate.method,
    subtitle: candidate.reason_text || candidate.method,
    colorClasses: "text-theme-text-secondary bg-theme-base/50 border border-theme-border",
  };
}

const DuplicatesSection: Component<DuplicatesSectionProps> = (props) => {
  const { isAdmin } = useAuth();

  const [mergePreview, setMergePreview] = createSignal<{
    winnerId: string;
    loserName: string;
  } | null>(null);

  const handlePreviewMerge = (c: MergeCandidateResponse) => {
    if (!c.suggested_target_id) return;
    setMergePreview({ winnerId: c.suggested_target_id, loserName: c.source_name });
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

  return (
    <>
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">
          Duplicates ({props.candidates().length})
        </h3>

        <Show
          when={props.candidates().length > 0}
          fallback={
            <p class="text-sm text-theme-text-secondary py-2">No duplicates found.</p>
          }
        >
          <div class="space-y-2">
            <For each={props.candidates()}>
              {(c) => {
                const badge = methodBadge(c);
                return (
                  <div class="flex items-start justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                    <div class="flex-1 min-w-0">
                      {/* Names: SOURCE → TARGET */}
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

                      {/* Badge + image count */}
                      <div class="flex items-center gap-2 flex-wrap">
                        <span
                          class={`text-xs px-1.5 py-0.5 rounded ${badge.colorClasses}`}
                          title={badge.subtitle}
                        >
                          {badge.label}
                        </span>
                        <span class="text-xs text-theme-text-secondary">
                          {c.source_image_count} {c.source_image_count === 1 ? "image" : "images"}
                        </span>
                      </div>
                    </div>

                    {/* Admin actions */}
                    <Show when={isAdmin()}>
                      <div class="flex gap-1.5 ml-3 flex-shrink-0">
                        <button
                          onClick={() => handlePreviewMerge(c)}
                          class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                        >
                          Preview Merge
                        </button>
                        <button
                          onClick={() => handleDismiss(c.id)}
                          class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                        >
                          Not a Duplicate
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

      {/* MergePreviewModal */}
      <Show when={mergePreview()}>
        {(mp) => (
          <MergePreviewModal
            winnerId={mp().winnerId}
            loserName={mp().loserName}
            onClose={() => setMergePreview(null)}
            onMerged={async () => {
              setMergePreview(null);
              props.onAction();
              window.dispatchEvent(new Event("merges-changed"));
            }}
          />
        )}
      </Show>
    </>
  );
};

export default DuplicatesSection;
