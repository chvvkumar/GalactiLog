// Server-side Celery job registry (GET /api/jobs): every queued or running
// task the scan/rebuild status sources do not already cover. Polled by
// JobMonitor; activeJobs() merges these rows in, so the panel shows work the
// server started on its own (settings-save cascades, post-scan correlation,
// beat) - the class of task that was invisible until it failed.
import { createSignal } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import type { ActiveJob } from "../api/types";

export interface ServerJob {
  task_id: string;
  name: string;
  state: string;
  queued_at?: number | null;
  started_at?: number | null;
  eta?: string | null;
}

const [serverJobsRaw, setServerJobsRaw] = createSignal<ServerJob[]>([]);

// Human labels for known task names. Unknown names fall back to a prettified
// form of the final dotted segment, so a task added next year shows up
// legibly with no edit here.
const TASK_LABELS: Record<string, string> = {
  "app.worker.tasks.correlate_phd2_images": "Matching guiding to frames",
  "app.worker.tasks.backfill_dark_hours": "Computing dark hours",
  recompute_session_dates: "Recomputing session dates",
  detect_mosaic_panels_task: "Detecting mosaic panels",
  detect_duplicate_targets: "Checking for duplicate targets",
  detect_filename_targets: "Resolving targets from filenames",
  "app.worker.tasks.backfill_csv_metrics": "Backfilling CSV metrics",
  "app.worker.tasks.run_data_migrations": "Running data migrations",
  "app.worker.tasks.load_reference_catalogs_if_empty": "Loading reference catalogs",
  "app.worker.tasks.enrich_new_target_task": "Enriching new target",
  "app.worker.tasks.backfill_catalog_identity": "Repairing catalog links",
  "app.worker.tasks.auto_scan_tick": "Auto-scan check",
  "app.worker.drain_logs.drain_app_logs": "Collecting app logs",
  "app.worker.prune_activity.prune_activity_events": "Pruning activity feed",
  "app.worker.prune_activity.prune_refresh_tokens": "Pruning login sessions",
};

export function taskLabel(name: string): string {
  const known = TASK_LABELS[name];
  if (known) return known;
  const leaf = name.split(".").pop() ?? name;
  const words = leaf.replace(/_task$/, "").split("_").filter(Boolean);
  if (words.length === 0) return name;
  const sentence = words.join(" ");
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function serverJobToActiveJob(j: ServerJob): ActiveJob {
  const running = j.state === "running";
  const anchor = running ? j.started_at ?? j.queued_at : j.queued_at;
  return {
    // Same key shape taskPoller's track() uses, which is what makes the
    // dedupe in activeJobs() possible: a client-tracked task and its registry
    // row are the same id.
    id: `celery:${j.task_id}`,
    category: "task",
    label: taskLabel(j.name),
    state: running ? "running" : "waiting",
    startedAt: anchor != null ? anchor * 1000 : Date.now(),
    etaMs: j.eta ? Date.parse(j.eta) || undefined : undefined,
    cancelable: false,
  };
}

export const serverJobs = (): ActiveJob[] => serverJobsRaw().map(serverJobToActiveJob);

export async function refreshServerJobs(): Promise<void> {
  try {
    const res = await apiClient.GET("/api/jobs", {}).then(unwrap);
    setServerJobsRaw(res.jobs as ServerJob[]);
  } catch {
    // Poll failure keeps the last known list; the next tick retries. A
    // transient network error must not blank the panel mid-job.
  }
}
