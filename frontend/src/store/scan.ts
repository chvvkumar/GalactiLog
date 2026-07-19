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

const [scanStatus, setScanStatus] = createSignal<ScanStatus>({ ...defaultStatus });
const [scanError, setScanError] = createSignal<string | null>(null);
const [stopping, setStopping] = createSignal(false);

let _subscribers = 0;
let pollInterval: ReturnType<typeof setInterval> | null = null;

async function fetchStatus() {
  try {
    const status = await apiClient.GET("/api/scan/status", {}).then(unwrap) as ScanStatus;
    setScanStatus(status);
    setScanError(null);

    // Stop polling when no longer active
    if (status.state !== "scanning" && status.state !== "ingesting") {
      stopPolling();
      setStopping(false);
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

// Module-scope exports for the always-mounted job monitor: the monitor needs
// the status accessor and stop action without owning a useScan() lifecycle,
// and a way to bootstrap the 2s poller when its slow idle check discovers a
// scan started elsewhere (auto-scan, another tab).
export { scanStatus };

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
  const s = scanStatus();
  if (s.state === "scanning" || s.state === "ingesting") {
    startPolling(true);
  }
}

export function useScan() {
  // On every mount, check server state - resume polling if scan is active
  onMount(async () => {
    _subscribers++;
    await fetchStatus();
    const s = scanStatus();
    if (s.state === "scanning" || s.state === "ingesting") {
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
