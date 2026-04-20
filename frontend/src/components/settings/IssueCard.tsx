import { Component, Show } from "solid-js";
import { useAuth } from "../AuthProvider";

export interface IssueCardCandidate {
  id: string;
  source_name: string;
  source_image_count: number;
  suggested_target_id: string | null;
  suggested_target_name: string | null;
  similarity_score: number;
  method: string;
  status: string;
  reason_text: string | null;
  created_at: string | null;
}

interface IssueCardProps {
  candidate: IssueCardCandidate;
  onPreviewMerge: (candidate: IssueCardCandidate) => void;
  onDismiss: (candidateId: string) => void;
  onRevert?: (candidateId: string) => void;
  onCreateTarget?: (candidate: IssueCardCandidate) => void;
}

function formatMergeDate(isoDate: string | null): string {
  if (!isoDate) return "";
  try {
    const d = new Date(isoDate);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return isoDate;
  }
}

function methodExplanation(candidate: IssueCardCandidate): string {
  if (candidate.reason_text) return candidate.reason_text;
  switch (candidate.method) {
    case "simbad":
      return "SIMBAD resolves both names to the same object";
    case "trigram":
      return `Names are ${Math.round(candidate.similarity_score * 100)}% similar`;
    case "duplicate":
      return "These targets share an alias";
    case "orphan":
      return "No match found in SIMBAD or existing targets";
    default:
      return candidate.method;
  }
}

const IssueCard: Component<IssueCardProps> = (props) => {
  const { isAdmin } = useAuth();
  const c = () => props.candidate;

  const isOrphan = () => c().method === "orphan";
  const isMerged = () => c().status === "accepted";
  const isDuplicate = () => !isOrphan() && !isMerged();

  const issueLabel = () => {
    if (isMerged()) return `Merged ${formatMergeDate(c().created_at)}`;
    if (isOrphan()) return "Unresolved FITS Name";
    return "Potential Duplicate";
  };

  const labelClass = () => {
    if (isMerged()) return "text-theme-text-tertiary bg-theme-base/50 border border-theme-border";
    if (isOrphan()) return "text-yellow-400 bg-yellow-500/10 border border-yellow-500/20";
    return "text-theme-accent bg-theme-accent/10 border border-theme-accent/20";
  };

  const cardClass = () =>
    isMerged()
      ? "flex items-start justify-between p-3 bg-theme-base/30 border border-theme-border rounded-[var(--radius-sm)] opacity-60"
      : "flex items-start justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]";

  return (
    <div class={cardClass()}>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-1 flex-wrap">
          <span class={`text-xs px-1.5 py-0.5 rounded ${labelClass()}`}>
            {issueLabel()}
          </span>
        </div>

        <div class="flex items-center gap-1 flex-wrap">
          <span class={`text-sm font-medium ${isMerged() ? "text-theme-text-secondary" : "text-theme-text-primary"}`}>
            {c().source_name}
          </span>
          <Show when={c().suggested_target_name && !isOrphan()}>
            <span class="text-theme-text-tertiary text-xs mx-1">&rarr;</span>
            <span class={`text-sm ${isMerged() ? "text-theme-text-secondary" : "text-theme-accent"}`}>
              {c().suggested_target_name}
            </span>
          </Show>
        </div>

        <div class="text-xs text-theme-text-secondary mt-0.5">
          {methodExplanation(c())}
          {" \u00b7 "}{c().source_image_count} {c().source_image_count === 1 ? "image" : "images"}
        </div>
      </div>

      <Show when={isAdmin()}>
        <div class="flex gap-1.5 ml-3 flex-shrink-0 flex-wrap justify-end">
          <Show when={isDuplicate()}>
            <button
              onClick={() => props.onPreviewMerge(c())}
              class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
            >
              Preview Merge
            </button>
            <button
              onClick={() => props.onDismiss(c().id)}
              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
            >
              Not a Duplicate
            </button>
          </Show>

          <Show when={isOrphan()}>
            <Show when={c().suggested_target_id}>
              <button
                onClick={() => props.onPreviewMerge(c())}
                class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
              >
                Assign to {c().suggested_target_name ?? "target"}
              </button>
            </Show>
            <Show when={props.onCreateTarget}>
              <button
                onClick={() => props.onCreateTarget!(c())}
                class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
              >
                Create New Target
              </button>
            </Show>
            <button
              onClick={() => props.onDismiss(c().id)}
              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
            >
              Dismiss
            </button>
          </Show>

          <Show when={isMerged() && props.onRevert}>
            <button
              onClick={() => props.onRevert!(c().id)}
              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
            >
              Undo Merge
            </button>
          </Show>
        </div>
      </Show>
    </div>
  );
};

export default IssueCard;
