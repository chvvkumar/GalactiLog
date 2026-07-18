// Module-level rebuild status, extracted from ScanManager so the job monitor
// can show a stats rebuild from any page, not only while Settings is open.
// Same polling shape as store/scan.ts: a 2s poll that stops itself when the
// rebuild leaves "running".
import { createSignal } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
// Hand-written RebuildStatus (narrow state literal union) rather than the
// generated RebuildStatusResponse, matching the existing contract threaded
// into store/activeJobs.ts wireActiveJobSources. See ScanManager.tsx's
// original import note; the field names are identical, so the cast below
// preserves the migration and the contract.
import type { RebuildStatus } from "../api/types";

const defaultStatus: RebuildStatus = {
  state: "idle",
  mode: "",
  message: "",
  started_at: null,
  completed_at: null,
  details: {},
};

const [rebuildStatus, setRebuildStatus] = createSignal<RebuildStatus>({ ...defaultStatus });

export { rebuildStatus };

let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopRebuildPolling(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export async function fetchRebuildStatus(): Promise<void> {
  try {
    const status = await apiClient.GET("/api/scan/rebuild-status").then(unwrap) as RebuildStatus;
    setRebuildStatus(status);
    if (status.state !== "running") stopRebuildPolling();
  } catch { /* ignore - transient network errors must not kill the poll loop */ }
}

export function startRebuildPolling(): void {
  // Clear any previous timer so we can restart.
  stopRebuildPolling();
  // Optimistic running state so the UI shows feedback immediately
  // (the Celery task may not have updated Redis yet).
  setRebuildStatus((prev) => ({
    ...prev,
    state: "running",
    message: "Starting...",
    started_at: Date.now() / 1000,
    completed_at: null,
  }));
  // Give the Celery task a moment to pick up before the first poll.
  setTimeout(fetchRebuildStatus, 1000);
  pollTimer = setInterval(fetchRebuildStatus, 2000);
}

// One cheap status check; resumes the 2s poll if a rebuild started elsewhere.
export async function refreshRebuildStatus(): Promise<void> {
  await fetchRebuildStatus();
  if (rebuildStatus().state === "running" && !pollTimer) {
    pollTimer = setInterval(fetchRebuildStatus, 2000);
  }
}
