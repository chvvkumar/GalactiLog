import { Component, For, Show, createSignal, onMount, onCleanup } from "solid-js";
import { api } from "../../api/client";
import { showToast, dismissToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { UnresolvedFilesTab } from "./UnresolvedFilesTab";
import { pollTask } from "../../store/taskPoller";
import type { MergeCandidateResponse } from "../../types";

export const MergesTab: Component = () => {
  const { isAdmin } = useAuth();
  const [candidates, setCandidates] = createSignal<MergeCandidateResponse[]>([]);
  const [accepted, setAccepted] = createSignal<MergeCandidateResponse[]>([]);
  const [detecting, setDetecting] = createSignal(false);
  const [view, setView] = createSignal<"suggestions" | "merged" | "unresolved">("suggestions");
  const [unresolvedCount, setUnresolvedCount] = createSignal(0);


  const refresh = async () => {
    try {
      const [c, a] = await Promise.all([
        api.getMergeCandidates("pending"),
        api.getMergeCandidates("accepted"),
      ]);
      setCandidates(c);
      setAccepted(a);
    } catch {
      // Non-blocking
    }
  };

  onMount(() => {
    refresh();
    api.getFilenameCandidateCount().then((r) => setUnresolvedCount(r.count)).catch(() => {});
  });

  const handleMerge = async (candidate: MergeCandidateResponse) => {
    try {
      await api.mergeTargets(
        candidate.suggested_target_id,
        undefined,
        candidate.source_name,
      );
      showToast(`Merged "${candidate.source_name}" into "${candidate.suggested_target_name}"`);
      await refresh();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Merge failed", "error");
    }
  };

  const handleDismiss = async (candidate: MergeCandidateResponse) => {
    try {
      await api.dismissMergeCandidate(candidate.id);
      setCandidates((prev) => prev.filter((c) => c.id !== candidate.id));
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Dismiss failed", "error");
    }
  };

  const handleRevert = async (candidate: MergeCandidateResponse) => {
    setConfirmRevertId(null);
    try {
      await api.revertMergeCandidate(candidate.id);
      showToast(`Reverted merge of "${candidate.source_name}"`);
      await refresh();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Revert failed", "error");
    }
  };

  let stopPolling: (() => void) | null = null;
  onCleanup(() => stopPolling?.());

  const handleDetect = async () => {
    setDetecting(true);
    try {
      const { task_id } = await api.triggerDuplicateDetection();
      showToast("Detecting duplicates...", "info", 60000);
      stopPolling = pollTask(task_id, {
        onSuccess: (result) => {
          dismissToast();
          const count = result?.candidates_found ?? 0;
          showToast(`Detection complete - ${count} candidate(s) found`);
          setDetecting(false);
          refresh();
        },
        onFailure: (error) => {
          dismissToast();
          showToast(error, "error");
          setDetecting(false);
        },
      });
    } catch {
      showToast("Failed to start detection", "error");
      setDetecting(false);
    }
  };

  return (
    <div class="space-y-4">
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <h3 class="text-theme-text-primary font-medium">Target Merges</h3>
          <Show when={isAdmin() && view() !== "unresolved"}>
            <button
              onClick={handleDetect}
              disabled={detecting()}
              class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
            >
              {detecting() ? "Detecting..." : "Run Detection"}
            </button>
          </Show>
        </div>
        <div class="flex gap-2">
          <button
            onClick={() => setView("suggestions")}
            class={`px-3 py-1.5 text-sm rounded-[var(--radius-sm)] transition-colors ${
              view() === "suggestions" ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover"
            }`}
          >
            Suggestions ({candidates().length})
          </button>
          <button
            onClick={() => setView("merged")}
            class={`px-3 py-1.5 text-sm rounded-[var(--radius-sm)] transition-colors ${
              view() === "merged" ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover"
            }`}
          >
            Merged ({accepted().length})
          </button>
          <button
            onClick={() => setView("unresolved")}
            class={`px-3 py-1.5 text-sm rounded-[var(--radius-sm)] transition-colors ${
              view() === "unresolved" ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover"
            }`}
          >
            Unresolved Files ({unresolvedCount()})
          </button>
        </div>

        <Show when={view() === "suggestions"}>
          <Show
            when={candidates().length > 0}
            fallback={<p class="text-sm text-theme-text-secondary">No pending suggestions. Run detection to scan for duplicates.</p>}
          >
            <div class="space-y-2">
              <For each={candidates()}>
                {(c) => (
                  <div class="flex items-center justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                    <div class="flex-1">
                      <span class="text-theme-text-primary text-sm font-medium">{c.source_name}</span>
                      <span class="text-theme-text-secondary text-xs mx-2">&rarr;</span>
                      <span class="text-theme-accent text-sm">{c.suggested_target_name}</span>
                      <div class="text-xs text-theme-text-secondary mt-0.5">
                        {c.method === "simbad" ? "SIMBAD confirmed" : `${Math.round(c.similarity_score * 100)}% match`}
                        {" \u00b7 "}{c.source_image_count} images
                      </div>
                    </div>
                    <Show when={isAdmin()}>
                      <div class="flex gap-2">
                        <button
                          onClick={() => handleMerge(c)}
                          class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                        >
                          Merge
                        </button>
                        <button
                          onClick={() => handleDismiss(c)}
                          class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                        >
                          Dismiss
                        </button>
                      </div>
                    </Show>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>

        <Show when={view() === "merged"}>
          <Show
            when={accepted().length > 0}
            fallback={<p class="text-sm text-theme-text-secondary">No merged targets yet.</p>}
          >
            <div class="space-y-2">
              <For each={accepted()}>
                {(c) => (
                  <div class="flex items-center justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                    <div class="flex-1">
                      <span class="text-theme-text-primary text-sm font-medium">{c.source_name}</span>
                      <span class="text-theme-text-secondary text-xs mx-2">&rarr; merged into &rarr;</span>
                      <span class="text-theme-accent text-sm">{c.suggested_target_name}</span>
                      <div class="text-xs text-theme-text-secondary mt-0.5">
                        {c.method === "simbad" ? "SIMBAD confirmed" : `${Math.round(c.similarity_score * 100)}% match`}
                        {" \u00b7 "}{c.source_image_count} images
                      </div>
                    </div>
                    <Show when={isAdmin()}>
                      <button
                        onClick={() => handleRevert(c)}
                        class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                      >
                        Revert
                      </button>
                    </Show>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>

        <Show when={view() === "unresolved"}>
          <UnresolvedFilesTab />
        </Show>
      </div>
    </div>
  );
};
