import { Component, For, Show, createSignal, onMount } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { emitWithToast } from "../../lib/emitWithToast";
import type { MergeCandidateResponse } from "../../types";
import IssueCard from "./IssueCard";
import type { IssueCardCandidate } from "./IssueCard";
import MergePreviewModal from "../MergePreviewModal";
import ResolveTargetModal from "./ResolveTargetModal";

type FilterPill = "all" | "duplicates" | "unresolved" | "recent";

interface ScanSummary {
  completed_at: string;
  files_ingested: number;
  targets_created: number;
  targets_updated: number;
  duplicates_found: number;
  unresolved_names: number;
  errors: number;
}

function toIssueCard(c: MergeCandidateResponse): IssueCardCandidate {
  return {
    id: c.id,
    source_name: c.source_name,
    source_image_count: c.source_image_count,
    suggested_target_id: c.suggested_target_id ?? null,
    suggested_target_name: c.suggested_target_name ?? null,
    similarity_score: c.similarity_score,
    method: c.method,
    status: c.status,
    reason_text: c.reason_text ?? null,
    created_at: c.created_at ?? null,
  };
}

export const TargetHealthTab: Component = () => {
  const { isAdmin } = useAuth();

  const [pending, setPending] = createSignal<MergeCandidateResponse[]>([]);
  const [accepted, setAccepted] = createSignal<MergeCandidateResponse[]>([]);
  const [scanSummary, setScanSummary] = createSignal<ScanSummary | null>(null);
  const [filter, setFilter] = createSignal<FilterPill>("all");
  const [maintenanceOpen, setMaintenanceOpen] = createSignal(false);
  const [showRebuildConfirm, setShowRebuildConfirm] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  // Modal state
  const [mergePreview, setMergePreview] = createSignal<{ winnerId: string; loserName: string } | null>(null);
  const [resolveCandidate, setResolveCandidate] = createSignal<MergeCandidateResponse | null>(null);

  const refresh = async () => {
    try {
      const [p, a] = await Promise.all([
        api.getMergeCandidates("pending"),
        api.getMergeCandidates("accepted"),
      ]);
      setPending(p);
      setAccepted(a);
    } catch {
      // non-blocking
    }
  };

  onMount(async () => {
    refresh();
    try {
      const s = await api.getScanSummary();
      if (s) setScanSummary(s as ScanSummary);
    } catch {
      // non-blocking
    }
  });

  const duplicates = () => pending().filter((c) => c.method !== "orphan");
  const unresolved = () => pending().filter((c) => c.method === "orphan");

  const filteredItems = (): IssueCardCandidate[] => {
    switch (filter()) {
      case "duplicates":
        return duplicates().map(toIssueCard);
      case "unresolved":
        return unresolved().map(toIssueCard);
      case "recent":
        return accepted().map(toIssueCard);
      default:
        return [...duplicates(), ...unresolved(), ...accepted()].map(toIssueCard);
    }
  };

  const handlePreviewMerge = (c: IssueCardCandidate) => {
    if (!c.suggested_target_id) return;
    setMergePreview({ winnerId: c.suggested_target_id, loserName: c.source_name });
  };

  const handleDismiss = async (candidateId: string) => {
    try {
      await api.dismissMergeCandidate(candidateId);
      await refresh();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Dismiss failed", "error");
    }
  };

  const handleRevert = async (candidateId: string) => {
    try {
      await api.revertMergeCandidate(candidateId);
      showToast("Merge reverted");
      await refresh();
      window.dispatchEvent(new Event("merges-changed"));
    } catch {
      showToast("Revert failed", "error");
    }
  };

  const handleCreateTarget = (c: IssueCardCandidate) => {
    // Find the original MergeCandidateResponse to pass to ResolveTargetModal
    const original = pending().find((p) => p.id === c.id);
    if (original) setResolveCandidate(original);
  };

  const handleResolved = async () => {
    setResolveCandidate(null);
    await refresh();
    window.dispatchEvent(new Event("merges-changed"));
  };

  const run = async (fn: () => Promise<void>) => {
    if (busy()) return;
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const handleRepairLinks = () =>
    run(() =>
      emitWithToast({
        action: () => api.smartRebuildTargets() as Promise<{ task_id: string }>,
        pendingLabel: "Repairing target links...",
        successLabel: "Target links repaired",
        errorLabel: "Repair failed",
        category: "rebuild",
        taskLabel: "Repair Target Links",
        timeout: 600_000,
      })
    );

  const handleRetryLookups = () =>
    run(() =>
      emitWithToast({
        action: () => api.retryUnresolved() as Promise<{ task_id: string }>,
        pendingLabel: "Retrying failed lookups...",
        successLabel: "Retry complete",
        errorLabel: "Retry failed",
        category: "enrichment",
        taskLabel: "Retry Failed Lookups",
        timeout: 600_000,
      })
    );

  const handleFullRebuild = () => {
    setShowRebuildConfirm(false);
    run(() =>
      emitWithToast({
        action: () => api.rebuildTargets() as Promise<{ task_id: string }>,
        pendingLabel: "Starting Full Rebuild...",
        successLabel: "Full Rebuild complete",
        errorLabel: "Full Rebuild failed",
        category: "rebuild",
        taskLabel: "Full Rebuild",
        timeout: 3_600_000,
      })
    );
  };

  const pillClass = (pill: FilterPill) =>
    filter() === pill
      ? "px-3 py-1.5 text-sm rounded-[var(--radius-sm)] bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em transition-colors"
      : "px-3 py-1.5 text-sm rounded-[var(--radius-sm)] border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover transition-colors";

  return (
    <div class="space-y-4">

      {/* Post-scan summary banner */}
      <Show when={scanSummary()}>
        {(s) => (
          <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
            <p class="text-xs text-theme-text-secondary mb-2 uppercase tracking-wide font-medium">Last Scan</p>
            <div class="flex flex-wrap gap-4">
              <div class="text-sm">
                <span class="text-theme-text-secondary">Files ingested: </span>
                <span class="text-theme-text-primary font-medium">{s().files_ingested}</span>
              </div>
              <Show when={s().targets_created > 0 || s().targets_updated > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">New targets: </span>
                  <span class="text-green-400 font-medium">{s().targets_created}</span>
                </div>
              </Show>
              <Show when={s().duplicates_found > 0}>
                <button
                  onClick={() => setFilter("duplicates")}
                  class="text-sm hover:underline"
                >
                  <span class="text-theme-text-secondary">Duplicates: </span>
                  <span class="text-yellow-400 font-medium">{s().duplicates_found}</span>
                </button>
              </Show>
              <Show when={s().unresolved_names > 0}>
                <button
                  onClick={() => setFilter("unresolved")}
                  class="text-sm hover:underline"
                >
                  <span class="text-theme-text-secondary">Unresolved: </span>
                  <span class="text-blue-400 font-medium">{s().unresolved_names}</span>
                </button>
              </Show>
              <Show when={s().errors > 0}>
                <div class="text-sm">
                  <span class="text-theme-text-secondary">Errors: </span>
                  <span class="text-red-400 font-medium">{s().errors}</span>
                </div>
              </Show>
            </div>
          </div>
        )}
      </Show>

      {/* Retry banner for unresolved items */}
      <Show when={isAdmin() && unresolved().length > 0}>
        <div class="flex items-center justify-between gap-3 px-4 py-3 bg-blue-500/10 border border-blue-500/20 rounded-[var(--radius-md)]">
          <p class="text-sm text-blue-400">
            {unresolved().length} {unresolved().length === 1 ? "file" : "files"} could not be identified.
          </p>
          <button
            onClick={handleRetryLookups}
            disabled={busy()}
            class="px-3 py-1.5 text-xs border border-blue-500/40 text-blue-400 rounded-[var(--radius-sm)] hover:bg-blue-500/10 transition-colors disabled:opacity-50 flex-shrink-0"
          >
            Retry Failed Lookups
          </button>
        </div>
      </Show>

      {/* Filter pills + issue list */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">Issues</h3>

        <div class="flex flex-wrap gap-2">
          <button onClick={() => setFilter("all")} class={pillClass("all")}>
            All Issues
            <span class="ml-1.5 text-xs text-theme-text-tertiary">
              ({duplicates().length + unresolved().length + accepted().length})
            </span>
          </button>
          <button onClick={() => setFilter("duplicates")} class={pillClass("duplicates")}>
            Duplicates
            <span class="ml-1.5 text-xs text-theme-text-tertiary">({duplicates().length})</span>
          </button>
          <button onClick={() => setFilter("unresolved")} class={pillClass("unresolved")}>
            Unresolved
            <span class="ml-1.5 text-xs text-theme-text-tertiary">({unresolved().length})</span>
          </button>
          <button onClick={() => setFilter("recent")} class={pillClass("recent")}>
            Recent Merges
            <span class="ml-1.5 text-xs text-theme-text-tertiary">({accepted().length})</span>
          </button>
        </div>

        <Show
          when={filteredItems().length > 0}
          fallback={
            <p class="text-sm text-theme-text-secondary py-2">No issues found.</p>
          }
        >
          <div class="space-y-2">
            <For each={filteredItems()}>
              {(c) => (
                <IssueCard
                  candidate={c}
                  onPreviewMerge={handlePreviewMerge}
                  onDismiss={handleDismiss}
                  onRevert={handleRevert}
                  onCreateTarget={handleCreateTarget}
                />
              )}
            </For>
          </div>
        </Show>
      </div>

      {/* Advanced Maintenance section */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)]">
        <button
          onClick={() => setMaintenanceOpen((v) => !v)}
          class="w-full flex items-center justify-between px-4 py-3 text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
        >
          <span class="font-medium">Advanced Maintenance</span>
          <span class="text-theme-text-tertiary text-xs">
            {maintenanceOpen() ? "Hide" : "Show"}
          </span>
        </button>

        <Show when={maintenanceOpen()}>
          <div class="px-4 pb-4 space-y-3 border-t border-theme-border pt-3">
            <p class="text-xs text-theme-text-secondary">
              These operations run automatically after each scan.
            </p>

            <div class="space-y-2">
              {/* Repair Target Links */}
              <div class="flex items-start justify-between gap-4 p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                <div class="flex-1">
                  <p class="text-sm text-theme-text-primary font-medium">Repair Target Links</p>
                  <p class="text-xs text-theme-text-secondary mt-0.5">
                    Repairs image-to-target links and re-derives target names using cached data.
                  </p>
                </div>
                <button
                  onClick={handleRepairLinks}
                  disabled={busy()}
                  class="px-3 py-1.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors disabled:opacity-50 flex-shrink-0"
                >
                  Run
                </button>
              </div>

              {/* Retry Failed Lookups */}
              <div class="flex items-start justify-between gap-4 p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                <div class="flex-1">
                  <p class="text-sm text-theme-text-primary font-medium">Retry Failed Lookups</p>
                  <p class="text-xs text-theme-text-secondary mt-0.5">
                    Clears failed SIMBAD caches and retries all unresolved names.
                  </p>
                </div>
                <button
                  onClick={handleRetryLookups}
                  disabled={busy()}
                  class="px-3 py-1.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors disabled:opacity-50 flex-shrink-0"
                >
                  Run
                </button>
              </div>

              {/* Full Rebuild */}
              <div class="flex items-start justify-between gap-4 p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                <div class="flex-1">
                  <p class="text-sm text-theme-text-primary font-medium text-theme-error">Full Rebuild</p>
                  <p class="text-xs text-theme-text-secondary mt-0.5">
                    Deletes all targets and re-resolves from scratch via SIMBAD.
                  </p>
                </div>
                <Show
                  when={showRebuildConfirm()}
                  fallback={
                    <button
                      onClick={() => setShowRebuildConfirm(true)}
                      disabled={busy()}
                      class="px-3 py-1.5 text-xs border border-theme-error/50 text-theme-error rounded-[var(--radius-sm)] hover:bg-theme-error/20 transition-colors disabled:opacity-50 flex-shrink-0"
                    >
                      Run
                    </button>
                  }
                >
                  <div class="flex gap-2 flex-shrink-0">
                    <button
                      onClick={handleFullRebuild}
                      disabled={busy()}
                      class="px-3 py-1.5 text-xs bg-theme-error text-theme-text-primary rounded-[var(--radius-sm)] hover:opacity-90 transition-colors disabled:opacity-50"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setShowRebuildConfirm(false)}
                      class="px-3 py-1.5 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </Show>
              </div>
            </div>
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
              await refresh();
              window.dispatchEvent(new Event("merges-changed"));
            }}
          />
        )}
      </Show>

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
    </div>
  );
};
