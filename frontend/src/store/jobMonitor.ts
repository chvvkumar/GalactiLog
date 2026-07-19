// Aggregation layer for the nav-bar job monitor: the existing activeJobs
// registry (scan + rebuild + Celery one-offs) plus the WBPP browser copy,
// reduced to the signals the strip/chip/panel render from.
import { activeJobs, wireActiveJobSources } from "./activeJobs";
import { wbppCopyActiveJob } from "./wbppCopyJob";
import { scanStatus, stopScan } from "./scan";
import { rebuildStatus } from "./rebuild";
import type { ActiveJob } from "../api/types";

let wired = false;

// Global replacement for the wiring ScanManager used to do on mount: the
// monitor mounts on every page, so jobs are visible everywhere. Idempotent.
export function wireGlobalJobSources(): void {
  if (wired) return;
  wired = true;
  wireActiveJobSources(scanStatus, rebuildStatus, stopScan);
}

export const monitorJobs = (): ActiveJob[] => {
  const jobs = [...activeJobs()];
  const copy = wbppCopyActiveJob();
  if (copy) jobs.push(copy);
  return jobs;
};

export const hasMonitorJobs = (): boolean => monitorJobs().length > 0;

// Aggregate strip progress: mean of the determinate jobs' fractions, or null
// when every running job is indeterminate (the strip renders a full-width
// shimmer instead of a bar in that case).
export function aggregateProgress(jobs: ActiveJob[]): number | null {
  const determinate = jobs.filter((j) => j.progress !== undefined);
  if (determinate.length === 0) return null;
  const sum = determinate.reduce((a, j) => a + (j.progress as number), 0);
  return Math.max(0, Math.min(1, sum / determinate.length));
}

export const stripProgress = (): number | null => aggregateProgress(monitorJobs());
