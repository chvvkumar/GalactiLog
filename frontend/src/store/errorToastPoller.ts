import { showToast } from "../components/Toast";
import { api } from "../api/client";

const LS_KEY = "galactilog_last_error_ts";

function getLastSeenTs(): string {
  try {
    return localStorage.getItem(LS_KEY) ?? new Date(0).toISOString();
  } catch {
    return new Date(0).toISOString();
  }
}

function setLastSeenTs(ts: string): void {
  try {
    localStorage.setItem(LS_KEY, ts);
  } catch { /* ignore */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

async function checkErrors(): Promise<void> {
  const since = getLastSeenTs();
  try {
    const res = await api.fetchActivityErrorsSince(since);
    if (res.items.length === 0) return;

    setLastSeenTs(res.items[0].timestamp);

    const toShow = res.items.slice(0, 3);
    for (const item of toShow) {
      const msg = `[${item.category}] ${item.message} (ref #${item.id})`;
      showToast(msg, "error", 0);
    }
    if (res.items.length > 3) {
      showToast(`${res.items.length - 3} more errors, check the Activity log`, "error", 0);
    }
  } catch { /* non-blocking */ }
}

export function startErrorToastPoller(): void {
  if (pollTimer) return;
  checkErrors();
  pollTimer = setInterval(checkErrors, 10_000);
}

export function stopErrorToastPoller(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}
