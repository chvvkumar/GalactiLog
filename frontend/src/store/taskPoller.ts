import { api } from "../api/client";
import { registerCeleryJob, unregisterCeleryJob } from "./activeJobs";
import type { ActiveJob } from "../types";

interface PollOptions {
  onSuccess?: (result: any) => void;
  onFailure?: (error: string) => void;
  /**
   * Called when the client-side poller times out. The backend task may still
   * be running healthily; this is purely a client-side give-up signal. Callers
   * should NOT treat this as a task failure.
   */
  onTimeout?: () => void;
  interval?: number;
  timeout?: number;
}

export function pollTask(taskId: string, options: PollOptions = {}): () => void {
  const { onSuccess, onFailure, onTimeout, interval = 2000, timeout = 60000 } = options;
  let timer: ReturnType<typeof setInterval> | null = null;
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const stop = () => {
    stopped = true;
    if (timer) clearInterval(timer);
    if (timeoutTimer) clearTimeout(timeoutTimer);
    timer = null;
    timeoutTimer = null;
  };

  const check = async () => {
    if (stopped) return;
    try {
      const status = await api.getTaskStatus(taskId);
      if (stopped) return;
      if (status.state === "SUCCESS") {
        stop();
        onSuccess?.(status.result);
      } else if (status.state === "FAILURE") {
        stop();
        onFailure?.(status.result?.error ?? "Task failed");
      }
    } catch {
      // Network error - keep polling, it may recover
    }
  };

  timer = setInterval(check, interval);
  timeoutTimer = setTimeout(() => {
    stop();
    // Client poller gave up; the backend task may still be running. Do NOT
    // call onFailure -- that would falsely report failure for a healthy task.
    onTimeout?.();
  }, timeout);

  return stop;
}

interface TrackOptions {
  id: string;
  category: ActiveJob["category"];
  label: string;
  subLabel?: string;
  cancelable?: boolean;
  timeout?: number;
  onSuccess?: (result: any) => void;
  onFailure?: (error: string) => void;
  /**
   * Called when the client poller stops watching due to timeout. The backend
   * task may still be running; the activeJobs entry will already be removed.
   */
  onTimeout?: () => void;
}

/**
 * Track a Celery task: register an activeJobs entry and poll for completion.
 * Returns a cancel function that unregisters the activeJobs entry and stops
 * the underlying poller. Safe to call multiple times.
 */
export function track(opts: TrackOptions): () => void {
  const jobId = `celery:${opts.id}`;

  registerCeleryJob({
    id: jobId,
    category: opts.category,
    label: opts.label,
    subLabel: opts.subLabel,
    progress: undefined,
    startedAt: Date.now(),
    cancelable: opts.cancelable ?? false,
  });

  let canceled = false;
  const stop = pollTask(opts.id, {
    interval: 2000,
    timeout: opts.timeout ?? 300_000,
    onSuccess: (result) => {
      if (canceled) return;
      unregisterCeleryJob(jobId);
      opts.onSuccess?.(result);
    },
    onFailure: (error) => {
      if (canceled) return;
      unregisterCeleryJob(jobId);
      opts.onFailure?.(error);
    },
    onTimeout: () => {
      if (canceled) return;
      // Silently detach the "Now Running" entry; the backend task may still
      // complete, and downstream toast/UI surfaces should not surface this
      // as a failure.
      unregisterCeleryJob(jobId);
      opts.onTimeout?.();
    },
  });

  return () => {
    if (canceled) return;
    canceled = true;
    unregisterCeleryJob(jobId);
    stop();
  };
}
