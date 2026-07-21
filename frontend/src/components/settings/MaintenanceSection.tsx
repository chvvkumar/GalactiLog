import { Component, Show, createSignal, onCleanup } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { useAuth } from "../AuthProvider";
import { emitWithToast } from "../../lib/emitWithToast";
import { startRebuildPolling } from "../../store/rebuild";
import type { RebuildStatus } from "../../api/types";

type OpState = "idle" | "running" | "complete" | "error";

interface MaintenanceSectionProps {
  onMaintenanceComplete: () => void;
}

const MaintenanceSection: Component<MaintenanceSectionProps> = (props) => {
  const { isAdmin } = useAuth();

  const [opState, setOpState] = createSignal<OpState>("idle");
  const [activeOp, setActiveOp] = createSignal<string | null>(null);
  const [statusMessage, setStatusMessage] = createSignal("");
  const [statusDetails, setStatusDetails] = createSignal<Record<string, number>>({});
  const [statusPercent, setStatusPercent] = createSignal<number | undefined>(undefined);
  const [errorMessage, setErrorMessage] = createSignal("");
  const [showRebuildConfirm, setShowRebuildConfirm] = createSignal(false);

  let pollTimer: ReturnType<typeof setInterval> | undefined;

  onCleanup(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  const startPolling = () => {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const status = await apiClient.GET("/api/scan/rebuild-status").then(unwrap) as RebuildStatus;
        setStatusMessage(status.message);
        // Generated schema types `details` as a loose `Record<string, unknown>`
        // (backend serializes numeric counters into it); narrow to the numeric
        // shape this component actually reads, matching the old hand-written type.
        setStatusDetails(status.details as Record<string, number>);
        setStatusPercent(status.percent ?? undefined);

        if (status.state === "complete") {
          stopPolling();
          setOpState("complete");
          props.onMaintenanceComplete();
          // Return to idle after a few seconds
          setTimeout(() => {
            if (opState() === "complete") {
              setOpState("idle");
              setActiveOp(null);
              setStatusMessage("");
              setStatusDetails({});
              setStatusPercent(undefined);
            }
          }, 4000);
        } else if (status.state === "error") {
          stopPolling();
          setOpState("error");
          setErrorMessage(status.message || "Operation failed");
        } else if (status.state === "idle" && opState() === "running") {
          // Task completed between polls without explicit "complete" state
          stopPolling();
          setOpState("complete");
          props.onMaintenanceComplete();
          setTimeout(() => {
            if (opState() === "complete") {
              setOpState("idle");
              setActiveOp(null);
              setStatusMessage("");
              setStatusDetails({});
              setStatusPercent(undefined);
            }
          }, 4000);
        }
      } catch {
        // polling error is non-blocking, keep trying
      }
    }, 2000);
  };

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = undefined;
    }
  };

  const runOperation = async (
    opName: string,
    action: () => Promise<{ task_id: string }>,
    pendingLabel: string,
    successLabel: string,
    errorLabel: string,
    category: "rebuild" | "enrichment",
    taskLabel: string,
    timeout: number,
  ) => {
    if (opState() === "running") return;
    setOpState("running");
    setActiveOp(opName);
    setStatusMessage("");
    setStatusDetails({});
    setStatusPercent(undefined);
    setErrorMessage("");

    startPolling();

    try {
      await emitWithToast({
        action,
        pendingLabel,
        successLabel,
        errorLabel,
        category,
        taskLabel,
        timeout,
      });
      // The action started the backend task successfully; kick the shared
      // rebuild store's 2s poll immediately so the nav-bar job monitor
      // reflects it right away instead of waiting for its own 30s idle check.
      startRebuildPolling();
    } catch {
      // emitWithToast handles its own error toasts; we also catch here
      // so the inline state resets if it wasn't already
      if (opState() === "running") {
        stopPolling();
        setOpState("error");
        setErrorMessage(errorLabel);
      }
    }
  };

  const handleRepairLinks = () =>
    runOperation(
      "repair",
      () => apiClient.POST("/api/scan/smart-rebuild-targets").then(unwrap) as Promise<{ task_id: string }>,
      "Repairing target links...",
      "Target links repaired",
      "Repair failed",
      "rebuild",
      "Repair Target Links",
      600_000,
    );

  const handleRetryLookups = () =>
    runOperation(
      "retry",
      () => apiClient.POST("/api/scan/retry-unresolved").then(unwrap) as Promise<{ task_id: string }>,
      "Retrying failed lookups...",
      "Retry complete",
      "Retry failed",
      "enrichment",
      "Retry Failed Lookups",
      600_000,
    );

  const handleBackfillIdentity = () =>
    runOperation(
      "backfill",
      () => apiClient.POST("/api/scan/backfill-catalog-identity").then(unwrap) as Promise<{ task_id: string }>,
      "Re-linking catalog orphans...",
      "Catalog orphans re-linked",
      "Backfill failed",
      "rebuild",
      "Re-link Catalog Orphans",
      1_800_000,
    );

  const handleFullRebuild = () => {
    setShowRebuildConfirm(false);
    runOperation(
      "rebuild",
      () => apiClient.POST("/api/scan/rebuild-targets").then(unwrap) as Promise<{ task_id: string }>,
      "Starting Full Rebuild...",
      "Full Rebuild complete",
      "Full Rebuild failed",
      "rebuild",
      "Full Rebuild",
      3_600_000,
    );
  };

  const isRunning = (op: string) => opState() === "running" && activeOp() === op;
  const isComplete = (op: string) => opState() === "complete" && activeOp() === op;
  const isError = (op: string) => opState() === "error" && activeOp() === op;
  const anyRunning = () => opState() === "running";

  /** Numeric progress bar, shown alongside the spinner once the backend
   *  reports a percent (undefined keeps the section spinner-only, e.g.
   *  before the first poll response or against an older backend). */
  const ProgressBar: Component = () => (
    <Show when={statusPercent() !== undefined}>
      <div class="w-full h-1.5 bg-theme-base rounded-full overflow-hidden mt-2">
        <div
          class="h-full bg-theme-accent rounded-full transition-all duration-300"
          style={{ width: `${statusPercent() ?? 0}%` }}
        />
      </div>
    </Show>
  );

  /** Format detail counts from rebuild status into a readable string */
  const formatDetails = (): string => {
    const d = statusDetails();
    const parts: string[] = [];
    if (d.resolved != null && d.total != null) {
      parts.push(`Resolved ${d.resolved} of ${d.total} targets`);
    } else if (d.resolved != null) {
      parts.push(`Resolved: ${d.resolved}`);
    }
    if (d.failed != null) parts.push(`Failed: ${d.failed}`);
    if (d.remaining != null) parts.push(`Remaining: ${d.remaining}`);
    if (d.linked != null) parts.push(`Linked: ${d.linked}`);
    if (d.skipped != null) parts.push(`Skipped: ${d.skipped}`);
    return parts.join("  ·  ");
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <h3 class="text-theme-text-primary font-medium">Maintenance</h3>

      <div class="space-y-2">
        {/* ---- Repair Target Links ---- */}
        <div class="p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-1">
                <p class="text-sm text-theme-text-primary font-medium">Repair Target Links</p>
                <span class="text-xs px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                  Safe
                </span>
              </div>
              <p class="text-xs text-theme-text-secondary mt-0.5">
                Re-links images to targets using cached data. No network calls. Fixes broken links after merges or name changes.
              </p>
              <p class="text-xs text-theme-text-tertiary mt-1">
                Run this if images appear under the wrong target or are missing from a target.
              </p>
            </div>

            <Show when={isAdmin() && !isRunning("repair") && !isComplete("repair")}>
              <button
                onClick={handleRepairLinks}
                disabled={anyRunning()}
                class="px-3 py-1.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors disabled:opacity-50 flex-shrink-0"
              >
                Run Repair
              </button>
            </Show>
          </div>

          {/* Progress / Complete / Error for repair */}
          <Show when={isRunning("repair")}>
            <div class="mt-3 flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-theme-accent border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <div class="text-xs text-theme-text-secondary">
                <p>{statusMessage() || "Repairing target links..."}</p>
                <Show when={formatDetails()}>
                  <p class="text-theme-text-tertiary mt-0.5">{formatDetails()}</p>
                </Show>
                <ProgressBar />
              </div>
            </div>
          </Show>
          <Show when={isComplete("repair")}>
            <p class="mt-2 text-xs text-green-400">Repair complete.</p>
          </Show>
          <Show when={isError("repair")}>
            <p class="mt-2 text-xs text-theme-error">{errorMessage()}</p>
          </Show>
        </div>

        {/* ---- Retry Failed Lookups ---- */}
        <div class="p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-1">
                <p class="text-sm text-theme-text-primary font-medium">Retry Failed Lookups</p>
                <span class="text-xs px-1.5 py-0.5 rounded bg-theme-warning/15 text-theme-warning border border-theme-warning/20">
                  Moderate
                </span>
              </div>
              <p class="text-xs text-theme-text-secondary mt-0.5">
                Clears failed lookup caches and re-queries SIMBAD for all unresolved names. Requires internet.
              </p>
              <p class="text-xs text-theme-text-tertiary mt-1">
                Run this after correcting FITS headers or if SIMBAD was down during the last scan.
              </p>
            </div>

            <Show when={isAdmin() && !isRunning("retry") && !isComplete("retry")}>
              <button
                onClick={handleRetryLookups}
                disabled={anyRunning()}
                class="px-3 py-1.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors disabled:opacity-50 flex-shrink-0"
              >
                Retry Lookups
              </button>
            </Show>
          </div>

          {/* Progress / Complete / Error for retry */}
          <Show when={isRunning("retry")}>
            <div class="mt-3 flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-theme-accent border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <div class="text-xs text-theme-text-secondary">
                <p>{statusMessage() || "Retrying failed lookups..."}</p>
                <Show when={formatDetails()}>
                  <p class="text-theme-text-tertiary mt-0.5">{formatDetails()}</p>
                </Show>
                <ProgressBar />
              </div>
            </div>
          </Show>
          <Show when={isComplete("retry")}>
            <p class="mt-2 text-xs text-green-400">Retry complete.</p>
          </Show>
          <Show when={isError("retry")}>
            <p class="mt-2 text-xs text-theme-error">{errorMessage()}</p>
          </Show>
        </div>

        {/* ---- Re-link Catalog Orphans ---- */}
        <div class="p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-1">
                <p class="text-sm text-theme-text-primary font-medium">Re-link Catalog Orphans</p>
                <span class="text-xs px-1.5 py-0.5 rounded bg-theme-warning/15 text-theme-warning border border-theme-warning/20">
                  Moderate
                </span>
              </div>
              <p class="text-xs text-theme-text-secondary mt-0.5">
                Repairs SIMBAD cache and re-links unattached frames to existing targets by catalog identity (e.g. NGC 6543). Requires internet for cache repair.
              </p>
              <p class="text-xs text-theme-text-tertiary mt-1">
                Run once after upgrading. Safe to re-run. Frames that match no catalog object stay listed under their object name.
              </p>
            </div>

            <Show when={isAdmin() && !isRunning("backfill") && !isComplete("backfill")}>
              <button
                onClick={handleBackfillIdentity}
                disabled={anyRunning()}
                class="px-3 py-1.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors disabled:opacity-50 flex-shrink-0"
              >
                Re-link Orphans
              </button>
            </Show>
          </div>

          <Show when={isRunning("backfill")}>
            <div class="mt-3 flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-theme-accent border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <div class="text-xs text-theme-text-secondary">
                <p>{statusMessage() || "Re-linking catalog orphans..."}</p>
                <Show when={formatDetails()}>
                  <p class="text-theme-text-tertiary mt-0.5">{formatDetails()}</p>
                </Show>
                <ProgressBar />
              </div>
            </div>
          </Show>
          <Show when={isComplete("backfill")}>
            <p class="mt-2 text-xs text-green-400">Backfill complete.</p>
          </Show>
          <Show when={isError("backfill")}>
            <p class="mt-2 text-xs text-theme-error">{errorMessage()}</p>
          </Show>
        </div>

        {/* ---- Full Rebuild ---- */}
        <div class="p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1">
              <div class="flex items-center gap-2 mb-1">
                <p class="text-sm text-theme-text-primary font-medium text-theme-error">Full Rebuild</p>
                <span class="text-xs px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/20">
                  Destructive
                </span>
              </div>
              <p class="text-xs text-theme-text-secondary mt-0.5">
                Deletes all targets and re-resolves every image from scratch via SIMBAD. This is slow and rate-limited.
              </p>
              <p class="text-xs text-theme-text-tertiary mt-1">
                Only needed if the target catalog is fundamentally broken. All manual edits (notes, locked names) will be lost.
              </p>
            </div>

            <Show when={isAdmin() && !isRunning("rebuild") && !isComplete("rebuild")}>
              <Show
                when={showRebuildConfirm()}
                fallback={
                  <button
                    onClick={() => setShowRebuildConfirm(true)}
                    disabled={anyRunning()}
                    class="px-3 py-1.5 text-xs border border-theme-error/50 text-theme-error rounded-[var(--radius-sm)] hover:bg-theme-error/20 transition-colors disabled:opacity-50 flex-shrink-0"
                  >
                    Full Rebuild
                  </button>
                }
              >
                <div class="flex gap-2 flex-shrink-0">
                  <button
                    onClick={handleFullRebuild}
                    disabled={anyRunning()}
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
            </Show>
          </div>

          {/* Progress / Complete / Error for rebuild */}
          <Show when={isRunning("rebuild")}>
            <div class="mt-3 flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-theme-accent border-t-transparent rounded-full animate-spin flex-shrink-0" />
              <div class="text-xs text-theme-text-secondary">
                <p>{statusMessage() || "Starting full rebuild..."}</p>
                <Show when={formatDetails()}>
                  <p class="text-theme-text-tertiary mt-0.5">{formatDetails()}</p>
                </Show>
                <ProgressBar />
              </div>
            </div>
          </Show>
          <Show when={isComplete("rebuild")}>
            <p class="mt-2 text-xs text-green-400">Full rebuild complete.</p>
          </Show>
          <Show when={isError("rebuild")}>
            <p class="mt-2 text-xs text-theme-error">{errorMessage()}</p>
          </Show>
        </div>
      </div>
    </div>
  );
};

export default MaintenanceSection;
