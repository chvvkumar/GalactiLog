import { showToast } from "../components/Toast";
import { api } from "../api/client";

const LS_KEY = "galactilog_last_error_ts";

// Tracks activity item IDs already surfaced as toasts in this browser session so
// the same error never pops again after the user has seen it (or dismissed it).
const seenIds = new Set<number>();

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

    // Filter to only items not yet shown in this session.
    const unseen = res.items.filter((item) => !seenIds.has(item.id));
    if (unseen.length === 0) return;

    const toShow = unseen.slice(0, 3);
    for (const item of toShow) {
      seenIds.add(item.id);
      // Prefix with "Background:" so the user knows these come from the
      // activity poller, not from an action they just triggered.
      const msg = `Background: [${item.category}] ${item.message} (ref #${item.id})`;
      showToast(msg, "error", 0);
    }
    if (unseen.length > 3) {
      const remaining = unseen.slice(3);
      for (const item of remaining) seenIds.add(item.id);
      showToast(`${unseen.length - 3} more background errors, check the Activity log`, "error", 0);
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
