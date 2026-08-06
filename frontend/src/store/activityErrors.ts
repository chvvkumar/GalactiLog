// Shared activity-errors store: ONE 10s visibility-gated poll of
// GET /api/activity?severity=error serves both the background-error toasts
// (formerly store/errorToastPoller.ts, behavior unchanged) and the job
// monitor's recent-errors panel + unseen badge.
//
// Two independent "seen" notions live here on purpose:
//   - Toast dedupe: localStorage last-toast timestamp + a session id set,
//     exactly as the old poller did. Controls only whether a toast pops.
//   - activitySeenAt: the SERVER-side per-user users.activity_seen_at,
//     seeded from the auth "me" payload and advanced by markAllErrorsSeen().
//     Controls only the unseen badge count.
import { createSignal } from "solid-js";
import { showToast } from "../components/Toast";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import type { ActivityEvent } from "../api/types";

const LS_KEY = "galactilog_last_error_ts";
const FETCH_LIMIT = 20;

// Activity item IDs already surfaced as toasts in this browser session so the
// same error never pops again after the user has seen it (or dismissed it).
const seenIds = new Set<number>();

const [errorEvents, setErrorEvents] = createSignal<ActivityEvent[]>([]);
const [activitySeenAt, setActivitySeenAt] = createSignal<string | null>(null);

export { errorEvents, activitySeenAt, setActivitySeenAt };

// Errors newer than the per-user seen marker. Drives both the badge count
// and the job monitor's recent-errors panel, so "Mark all seen" dismisses
// rows from the panel while the full feed stays in the Activity log.
export const unseenErrors = (): ActivityEvent[] => {
  const seenAt = activitySeenAt();
  const seenMs = seenAt ? new Date(seenAt).getTime() : 0;
  return errorEvents().filter((e) => new Date(e.timestamp).getTime() > seenMs);
};

export const unseenErrorCount = (): number => unseenErrors().length;

export async function markAllErrorsSeen(): Promise<void> {
  try {
    const res = await apiClient.POST("/api/activity/seen", {}).then(unwrap);
    setActivitySeenAt(res.activity_seen_at);
  } catch {
    // Non-blocking: the badge simply stays until the next successful call.
  }
}

function getLastToastTs(): string {
  try {
    return localStorage.getItem(LS_KEY) ?? new Date(0).toISOString();
  } catch {
    return new Date(0).toISOString();
  }
}

function setLastToastTs(ts: string): void {
  try {
    localStorage.setItem(LS_KEY, ts);
  } catch { /* ignore */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

// Only poll while the tab is visible; a backgrounded tab does not need to
// surface background-error toasts, and re-checks immediately on return.
function pollIfVisible(): void {
  if (document.visibilityState === "visible") void checkErrors();
}

function onVisibilityChange(): void {
  if (document.visibilityState === "visible") void checkErrors();
}

export async function checkErrors(): Promise<void> {
  try {
    const res = await apiClient
      .GET("/api/activity", { params: { query: { severity: ["error"], limit: FETCH_LIMIT } } })
      .then(unwrap);
    setErrorEvents(res.items);
    if (res.items.length === 0) return;

    // Toast behavior unchanged from errorToastPoller: only items newer than
    // the last toasted timestamp, minus those already toasted this session.
    const lastMs = new Date(getLastToastTs()).getTime();
    const unseen = res.items.filter(
      (item) => new Date(item.timestamp).getTime() > lastMs && !seenIds.has(item.id),
    );
    if (unseen.length === 0) return;
    setLastToastTs(res.items[0].timestamp);

    const toShow = unseen.slice(0, 3);
    for (const item of toShow) {
      seenIds.add(item.id);
      // Prefix with "Background:" so the user knows these come from the
      // activity poller, not from an action they just triggered.
      const msg = `Background: [${item.category}] ${item.message} (ref #${item.id})`;
      showToast(msg, "error", 0);
    }
    if (unseen.length > 3) {
      for (const item of unseen.slice(3)) seenIds.add(item.id);
      showToast(`${unseen.length - 3} more background errors, check the Activity log`, "error", 0);
    }
  } catch { /* non-blocking */ }
}

export function startActivityErrorsPoller(): void {
  if (pollTimer) return;
  pollIfVisible();
  pollTimer = setInterval(pollIfVisible, 10_000);
  document.addEventListener("visibilitychange", onVisibilityChange);
}

export function stopActivityErrorsPoller(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  document.removeEventListener("visibilitychange", onVisibilityChange);
}
