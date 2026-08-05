import { createSignal, onCleanup, onMount } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
// ScanStatus is the hand-written definition in `../api/types` (narrow
// `state` literal union, vs. the generated `ScanStateResponse`'s plain
// `string`). This store's signal is consumed by store/activeJobs.ts's
// wireActiveJobSources (itself consumed by ScanManager.tsx) via the
// literal-union contract; the field names are otherwise identical to the
// generated ScanStateResponse, so casting the fetch result preserves both
// the migration and the existing contract.
import type { ScanStatus } from "../api/types";
import { queryClient } from "../lib/queryClient";
import { PHD2_QUERY_PREFIX } from "../api/queryKeys";

const defaultStatus: ScanStatus = {
  state: "idle",
  total: 0,
  completed: 0,
  failed: 0,
  csv_enriched: 0,
  discovered: 0,
  started_at: null,
  completed_at: null,
  new_files: 0,
  changed_files: 0,
  removed: 0,
  skipped_calibration: 0,
};

/** How long a guide-log pass may claim to be queued or running before the UI
 *  stops believing it. A worker that dies between dispatch and completion
 *  leaves phd2_state at "pending" in a Redis hash that outlives the scan, so
 *  without a guard the job monitor would show "Processing guide logs" until
 *  the tab reloads and the 2 s poller would never stop. Ten minutes is far
 *  beyond the observed worst case (the 25-file corpus ingests in under a
 *  minute) and short enough that nobody watches a dead row for a session. */
export const PHD2_STALL_MS = 10 * 60_000;

export type Phd2Phase = "idle" | "processing" | "stalled";

/** True while the backend claims a guide-log pass is queued or running. */
export function phd2Reported(s: ScanStatus): boolean {
  return s.phd2_state === "pending" || s.phd2_state === "running";
}

/**
 * The phase of the guide-log pass as the UI should treat it.
 *
 * The window is measured from the LAST state transition, not from the start
 * of the pass, so a pass that moves from queued to running restarts it once
 * and only a pass that stops transitioning ages out.
 *
 * `firstSeenMs` is when this client first observed the flag set. The
 * reference the guard measures against, most authoritative first:
 *   1. `phd2_state_at` from the backend, the normal case: it is written at
 *      every transition and survives a page reload;
 *   2. `firstSeenMs`, the degraded path for a backend that predates the
 *      field or a tab that connected before a transition was visible. It
 *      does not survive a reload but is monotonic within a tab;
 *   3. the completion time of a finished scan, since the pass is dispatched
 *      around scan completion. Only consulted for a completed scan, or a
 *      completed_at left over from the PREVIOUS scan would call a pass that
 *      just started stalled.
 * With no reference at all the answer is "processing": the guard exists to
 * stop a stuck flag, not to invent one.
 */
export function phd2Phase(
  s: ScanStatus,
  nowMs: number,
  firstSeenMs: number | null,
): Phd2Phase {
  if (!phd2Reported(s)) return "idle";
  const referenceMs =
    s.phd2_state_at != null
      ? s.phd2_state_at * 1000
      : firstSeenMs !== null
      ? firstSeenMs
      : s.state === "complete" && s.completed_at != null
      ? s.completed_at * 1000
      : null;
  if (referenceMs === null) return "processing";
  return nowMs - referenceMs > PHD2_STALL_MS ? "stalled" : "processing";
}

const [scanStatus, setScanStatus] = createSignal<ScanStatus>({ ...defaultStatus });
const [scanError, setScanError] = createSignal<string | null>(null);
const [stopping, setStopping] = createSignal(false);

// When this client first saw the guide-log flag set, so the stall guard has a
// reference even against a backend that sends no timestamp. Cleared the
// moment the flag comes down, so the next pass is timed from its own start.
const [phd2FirstSeenAt, setPhd2FirstSeenAt] = createSignal<number | null>(null);

let _subscribers = 0;
let pollInterval: ReturnType<typeof setInterval> | null = null;

async function fetchStatus() {
  try {
    const previous = scanStatus();
    const status = await apiClient.GET("/api/scan/status", {}).then(unwrap) as ScanStatus;
    setScanStatus(status);
    setScanError(null);

    if (phd2Reported(status)) {
      if (phd2FirstSeenAt() === null) setPhd2FirstSeenAt(Date.now());
    } else {
      setPhd2FirstSeenAt(null);
    }

    // A pass that just came down has written new sessions, frames and night
    // summaries, so every cached ["phd2", ...] read now describes the state
    // before the ingest. Nothing else invalidates them: the PHD2 queries are
    // the only TanStack Query reads this store's data can invalidate, and
    // their 5 minute staleTime is far too long to sit on after a scan.
    if (phd2Reported(previous) && !phd2Reported(status)) {
      queryClient.invalidateQueries({ queryKey: PHD2_QUERY_PREFIX });
    }

    // Stop polling when neither the image scan nor the guide-log pass is
    // live. The pass runs AFTER the image scan reports complete, so stopping
    // on the image state alone would blind the monitor to the whole tail.
    const scanActive = status.state === "scanning" || status.state === "ingesting";
    if (!scanActive) setStopping(false);
    if (!scanActive && phd2Phase(status, Date.now(), phd2FirstSeenAt()) !== "processing") {
      stopPolling();
    }
  } catch {
    setScanError("Failed to reach API");
    stopPolling();
  }
}

function startPolling(skipInitialFetch = false) {
  if (pollInterval) return;
  if (!skipInitialFetch) fetchStatus(); // immediate first fetch
  pollInterval = setInterval(fetchStatus, 2000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

/** Whether the 2 s poller has anything left to watch. */
function shouldPoll(s: ScanStatus): boolean {
  return (
    s.state === "scanning" ||
    s.state === "ingesting" ||
    phd2Phase(s, Date.now(), phd2FirstSeenAt()) === "processing"
  );
}

// Module-scope exports for the always-mounted job monitor: the monitor needs
// the status accessor and stop action without owning a useScan() lifecycle,
// and a way to bootstrap the 2s poller when its slow idle check discovers a
// scan started elsewhere (auto-scan, another tab).
export { scanStatus, phd2FirstSeenAt };

export async function stopScan(): Promise<void> {
  setStopping(true);
  try {
    await apiClient.POST("/api/scan/stop", {}).then(unwrap);
  } catch {
    setStopping(false);
    setScanError("Failed to stop scan");
  }
}

// One cheap status check; hands off to the existing 2s poller when active.
export async function refreshScanStatus(): Promise<void> {
  await fetchStatus();
  if (shouldPoll(scanStatus())) {
    startPolling(true);
  }
}

export function useScan() {
  // On every mount, check server state - resume polling if scan is active
  onMount(async () => {
    _subscribers++;
    await fetchStatus();
    if (shouldPoll(scanStatus())) {
      startPolling();
    }
  });

  onCleanup(() => {
    _subscribers--;
    if (_subscribers <= 0) {
      _subscribers = 0;
      stopPolling();
    }
  });

  return {
    scanStatus,
    scanError,
    stopping,

    isActive: () => {
      const s = scanStatus().state;
      return s === "scanning" || s === "ingesting";
    },

    startScan: async (options?: { includeCalibration?: boolean; forceOrphanCleanup?: boolean }) => {
      setScanError(null);
      setStopping(false);
      // Immediately show scanning state so the UI responds instantly
      setScanStatus((prev) => ({ ...prev, state: "scanning", completed: 0, failed: 0, total: 0, discovered: 0 }));
      try {
        await apiClient
          .POST("/api/scan", {
            params: {
              query: {
                include_calibration: options?.includeCalibration === false ? false : undefined,
                force_orphan_cleanup: options?.forceOrphanCleanup ? true : undefined,
              },
            },
          })
          .then(unwrap);
      } catch {
        // POST /scan may timeout on large directories, but scan still starts server-side
      }
      // Start polling after trigger so the server has queued the task;
      // skip initial fetch since we already set state optimistically
      startPolling(true);
    },

    startRegeneration: async (opts: { purge?: boolean } = {}) => {
      setScanError(null);
      setScanStatus((prev) => ({ ...prev, state: "scanning", completed: 0, failed: 0, total: 0 }));
      try {
        await apiClient
          .POST("/api/scan/regenerate-thumbnails", {
            params: {
              query: {
                purge: opts.purge ? true : undefined,
              },
            },
          })
          .then(unwrap);
      } catch {
        // POST may timeout but regeneration still starts server-side
      }
      startPolling(true);
    },

    resetScan: async () => {
      try {
        await apiClient.POST("/api/scan/reset", {}).then(unwrap);
        setScanStatus({ ...defaultStatus });
        setScanError(null);
      } catch {
        setScanError("Failed to reset scan state");
      }
    },

    stopScan,

    stopPolling,
  };
}
