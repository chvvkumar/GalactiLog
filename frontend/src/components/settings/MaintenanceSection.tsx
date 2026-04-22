import { Component, Show, createSignal, onCleanup } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { emitWithToast } from "../../lib/emitWithToast";
import type { RebuildStatus } from "../../types";

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
        const status: RebuildStatus = await api.getRebuildStatus();
        setStatusMessage(status.message);
        setStatusDetails(status.details);

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
      () => api.smartRebuildTargets() as Promise<{ task_id: string }>,
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
      () => api.retryUnresolved() as Promise<{ task_id: string }>,
      "Retrying failed lookups...",
      "Retry complete",
      "Retry failed",
      "enrichment",
      "Retry Failed Lookups",
      600_000,
    );

  const handleFullRebuild = () => {
    setShowRebuildConfirm(false);
    runOperation(
      "rebuild",
      () => api.rebuildTargets() as Promise<{ task_id: string }>,
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
                <span class="text-xs px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20">
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
