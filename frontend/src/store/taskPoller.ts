import { api } from "../api/client";

interface PollOptions {
  onSuccess?: (result: any) => void;
  onFailure?: (error: string) => void;
  interval?: number;
  timeout?: number;
}

export function pollTask(taskId: string, options: PollOptions = {}): () => void {
  const { onSuccess, onFailure, interval = 2000, timeout = 60000 } = options;
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
      // Network error — keep polling, it may recover
    }
  };

  timer = setInterval(check, interval);
  timeoutTimer = setTimeout(() => {
    stop();
    onFailure?.("Detection timed out");
  }, timeout);

  return stop;
}
