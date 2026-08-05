import { createSignal } from "solid-js";
import type { ActiveJob, ScanStatus, RebuildStatus } from "../api/types";
import { phd2FirstSeenAt, phd2Phase, type Phd2Phase } from "./scan";
import { serverJobs } from "./serverJobs";

const [celeryJobs, setCeleryJobs] = createSignal<Map<string, ActiveJob>>(new Map());

export function scanStatusToJob(
  s: ScanStatus,
  onStop: () => Promise<void>,
  phd2: Phd2Phase
): ActiveJob | null {
  const scanActive = s.state === "scanning" || s.state === "ingesting";
  const phd2Active = phd2 === "processing";
  if (!scanActive && !phd2Active) return null;

  // phd2_found is published once the candidate list is known, and
  // phd2_ingested / phd2_failed increment per file as the pass runs, with the
  // end-of-pass write authoritative. A counted label is therefore the expected
  // steady state. The countless branch still earns its keep: it covers a
  // status snapshot from a backend that predates the counters, and the window
  // between dispatch and the first published count, where printing "0 of 0"
  // would be worse than saying nothing about totals.
  const phd2Total = s.phd2_found ?? 0;
  const phd2Done = (s.phd2_ingested ?? 0) + (s.phd2_failed ?? 0);

  if (!scanActive) {
    // Elapsed time for this row must count up from when the pass began, so
    // completed_at comes first here. In this branch the image scan is by
    // definition finished, which makes completed_at both present and a stable
    // proxy for dispatch. phd2_state_at cannot lead: the backend renews it on
    // every per-file progress write, so using it would reset the elapsed
    // label to zero with each ingested log. The stall guard in store/scan.ts
    // deliberately keeps the opposite precedence, where that renewal is the
    // whole point.
    const startedAt =
      s.completed_at != null
        ? s.completed_at * 1000
        : s.phd2_state_at != null
        ? s.phd2_state_at * 1000
        : Date.now();

    return {
      id: "scan",
      category: "scan",
      label: "Processing guide logs",
      subLabel:
        phd2Total > 0
          ? `${phd2Done.toLocaleString()} of ${phd2Total.toLocaleString()} logs`
          : undefined,
      progress: phd2Total > 0 ? Math.min(1, phd2Done / phd2Total) : undefined,
      startedAt,
      cancelable: false,
    };
  }

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

  const fileLabel =
    s.state === "ingesting" && s.total > 0
      ? `${(s.completed + s.failed).toLocaleString()} / ${s.total.toLocaleString()} files`
      : s.discovered > 0
      ? `${s.discovered.toLocaleString()} files found`
      : undefined;

  const guideLabel = !phd2Active
    ? undefined
    : phd2Total > 0
    ? `Guide logs processing (${phd2Done.toLocaleString()} of ${phd2Total.toLocaleString()})`
    : "Guide logs processing";

  const parts = [fileLabel, guideLabel].filter((p): p is string => !!p);

  return {
    id: "scan",
    category: "scan",
    label: s.state === "scanning" ? "Discovering files" : "Ingesting files",
    subLabel: parts.length > 0 ? parts.join(" · ") : undefined,
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
    const status = _scanStatusAccessor();
    const scanJob = scanStatusToJob(
      status,
      _stopScanFn,
      phd2Phase(status, Date.now(), phd2FirstSeenAt())
    );
    if (scanJob) jobs.push(scanJob);
  }

  if (_rebuildStatusAccessor) {
    const rebuildJob = rebuildStatusToJob(_rebuildStatusAccessor());
    if (rebuildJob) jobs.push(rebuildJob);
  }

  const tracked = celeryJobs();
  tracked.forEach((job) => jobs.push(job));

  // Registry rows share the `celery:<task_id>` key with track()'s rows, so a
  // task the current tab is already watching (with its richer callbacks)
  // appears once, from the tracker.
  serverJobs().forEach((job) => {
    if (!tracked.has(job.id)) jobs.push(job);
  });

  return jobs;
};

export const hasActiveJobs: Accessor<boolean> = () => activeJobs().length > 0;
