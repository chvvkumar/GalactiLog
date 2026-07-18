import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../api/generated/client", () => ({
  apiClient: { GET: vi.fn(), POST: vi.fn() },
}));
vi.mock("../components/Toast", () => ({ showToast: vi.fn() }));

import { apiClient } from "../api/generated/client";
import { showToast } from "../components/Toast";
import {
  checkErrors,
  errorEvents,
  unseenErrorCount,
  setActivitySeenAt,
  markAllErrorsSeen,
} from "./activityErrors";

function okResult<T>(data: T) {
  return { data, error: undefined, response: { ok: true, status: 200 } as Response };
}

// Newest first, matching GET /api/activity ordering.
const items = [
  { id: 2, timestamp: "2026-07-18T12:10:00+00:00", severity: "error", category: "scan", event_type: "ingest_failed", message: "3 files failed to ingest" },
  { id: 1, timestamp: "2026-07-18T12:00:00+00:00", severity: "error", category: "enrichment", event_type: "simbad_timeout", message: "SIMBAD lookup timeout" },
];

describe("activityErrors", () => {
  beforeEach(() => {
    vi.mocked(apiClient.GET).mockReset();
    vi.mocked(apiClient.POST).mockReset();
    vi.mocked(showToast).mockReset();
    localStorage.clear();
  });

  it("stores fetched errors and counts all as unseen when activity_seen_at is null", async () => {
    vi.mocked(apiClient.GET).mockResolvedValue(okResult({ items, next_cursor: null, total: 2 }));
    setActivitySeenAt(null);
    await checkErrors();
    expect(errorEvents().length).toBe(2);
    expect(unseenErrorCount()).toBe(2);
    expect(apiClient.GET).toHaveBeenCalledWith("/api/activity", {
      params: { query: { severity: ["error"], limit: 20 } },
    });
  });

  it("counts only errors newer than activity_seen_at", async () => {
    vi.mocked(apiClient.GET).mockResolvedValue(okResult({ items, next_cursor: null, total: 2 }));
    setActivitySeenAt("2026-07-18T12:05:00+00:00");
    await checkErrors();
    expect(unseenErrorCount()).toBe(1);
  });

  it("markAllErrorsSeen posts and advances the seen timestamp to clear the badge", async () => {
    vi.mocked(apiClient.GET).mockResolvedValue(okResult({ items, next_cursor: null, total: 2 }));
    vi.mocked(apiClient.POST).mockResolvedValue(okResult({ activity_seen_at: "2026-07-18T12:30:00+00:00" }));
    setActivitySeenAt(null);
    await checkErrors();
    await markAllErrorsSeen();
    expect(apiClient.POST).toHaveBeenCalledWith("/api/activity/seen", {});
    expect(unseenErrorCount()).toBe(0);
  });

  it("toasts new errors once and never re-toasts on the next poll", async () => {
    // Fresh ids: the module-level session dedupe set persists across the
    // tests in this file, so ids 1 and 2 were already consumed above.
    const toastItems = [
      { id: 102, timestamp: "2026-07-18T13:10:00+00:00", severity: "error", category: "scan", event_type: "ingest_failed", message: "1 file failed to ingest" },
      { id: 101, timestamp: "2026-07-18T13:00:00+00:00", severity: "error", category: "mosaic", event_type: "composite_failed", message: "Composite failed" },
    ];
    vi.mocked(apiClient.GET).mockResolvedValue(okResult({ items: toastItems, next_cursor: null, total: 2 }));
    await checkErrors();
    const toastsAfterFirst = vi.mocked(showToast).mock.calls.length;
    expect(toastsAfterFirst).toBe(2);
    expect(vi.mocked(showToast).mock.calls[0][0]).toContain("Background: [scan]");
    await checkErrors();
    expect(vi.mocked(showToast).mock.calls.length).toBe(toastsAfterFirst);
  });
});
