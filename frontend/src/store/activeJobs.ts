import { createSignal } from "solid-js";
import type { ActiveJob, ScanStatus, RebuildStatus } from "../types";

const [celeryJobs, setCeleryJobs] = createSignal<Map<string, ActiveJob>>(new Map());

function scanStatusToJob(
  s: ScanStatus,
  onStop: () => Promise<void>
): ActiveJob | null {
  if (s.state !== "scanning" && s.state !== "ingesting") return null;

  const startedAt = s.started_at != null ? s.started_at * 1000 : Date.now();

  // While ingesting, prefer the server-derived envelope percent (0-100 ->
  // 0-1 fraction); fall back to the hand-computed counter ratio only if the
  // backend hasn't sent a percent yet (e.g. mixed-deploy rolling upgrade
  // window). Discovery ("scanning") has no fixed total, so it stays
  // indeterminate regardless of the envelope, matching prior behavior.
  const progress =
    s.state !== "ingesting"
      ? undefined
      : s.percent !== undefined
      ? Math.min(1, s.percent / 100)
      : s.total > 0
      ? Math.min(1, (s.completed + s.failed) / s.total)
      : undefined;

  const subLabel =
    s.state === "ingesting" && s.total > 0
      ? `${(s.completed + s.failed).toLocaleString()} / ${s.total.toLocaleString()} files`
      : s.discovered > 0
      ? `${s.discovered.toLocaleString()} files found`
      : undefined;

  return {
    id: "scan",
    category: "scan",
    label: s.state === "scanning" ? "Discovering files" : "Ingesting files",
    subLabel,
    progress,
    startedAt,
    cancelable: true,
    onCancel: onStop,
  };
}

function rebuildStatusToJob(r: RebuildStatus): ActiveJob | null {
  if (r.state !== "running") return null;

  const startedAt = r.started_at != null ? r.started_at * 1000 : Date.now();

  const modeLabel: Record<string, string> = {
    smart: "Repairing Target Links",
    full: "Full Rebuild",
    retry: "Retrying Failed Lookups",
    ref_thumbnails: "Fetching Reference Images",
    regen: "Regenerating Thumbnails",
  };

  // Backend percent is 0-100; ActiveJob.progress is a 0-1 fraction expected
  // by ActiveJobRow. Convert explicitly -- do not assume the scales match.
  const progress = r.percent !== undefined ? Math.min(1, r.percent / 100) : undefined;

  return {
    id: "rebuild",
    category: "rebuild",
    label: modeLabel[r.mode] ?? "Rebuild",
    subLabel: r.message || undefined,
    progress,
    startedAt,
    cancelable: false,
  };
}

export function registerCeleryJob(job: ActiveJob): void {
  setCeleryJobs((prev) => {
    const next = new Map(prev);
    next.set(job.id, job);
    return next;
  });
}

export function unregisterCeleryJob(id: string): void {
  setCeleryJobs((prev) => {
    const next = new Map(prev);
    next.delete(id);
    return next;
  });
}

type Accessor<T> = () => T;

let _scanStatusAccessor: Accessor<ScanStatus> | null = null;
let _rebuildStatusAccessor: Accessor<RebuildStatus> | null = null;
let _stopScanFn: (() => Promise<void>) | null = null;

export function wireActiveJobSources(
  scanStatus: Accessor<ScanStatus>,
  rebuildStatus: Accessor<RebuildStatus>,
  stopScan: () => Promise<void>
): void {
  _scanStatusAccessor = scanStatus;
  _rebuildStatusAccessor = rebuildStatus;
  _stopScanFn = stopScan;
}

export const activeJobs: Accessor<ActiveJob[]> = () => {
  const jobs: ActiveJob[] = [];

  if (_scanStatusAccessor && _stopScanFn) {
    const scanJob = scanStatusToJob(_scanStatusAccessor(), _stopScanFn);
    if (scanJob) jobs.push(scanJob);
  }

  if (_rebuildStatusAccessor) {
    const rebuildJob = rebuildStatusToJob(_rebuildStatusAccessor());
    if (rebuildJob) jobs.push(rebuildJob);
  }

  celeryJobs().forEach((job) => jobs.push(job));

  return jobs;
};

export const hasActiveJobs: Accessor<boolean> = () => activeJobs().length > 0;
