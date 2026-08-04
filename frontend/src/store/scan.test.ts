import { describe, it, expect, vi } from "vitest";

// The store fetches on import-time module init in some call paths, so the
// generated client is stubbed before the module under test is imported. Only
// the pure phase helpers are exercised here; the poller lifecycle is driven
// by setInterval and belongs to a manual smoke, not this suite.
vi.mock("../api/generated/client", () => ({
  apiClient: { GET: vi.fn(), POST: vi.fn() },
}));

import { PHD2_STALL_MS, phd2Phase, phd2Reported } from "./scan";
import type { ScanStatus } from "../api/types";

const base: ScanStatus = {
  state: "complete",
  total: 0,
  completed: 0,
  failed: 0,
  csv_enriched: 0,
  discovered: 0,
  started_at: null,
  completed_at: null,
  new_files: 0,
  changed_files: 0,
  removed: 0,
  skipped_calibration: 0,
};

const NOW = 1_753_800_000_000;

describe("phd2Reported", () => {
  it("is true while the backend claims a pass is queued or running", () => {
    expect(phd2Reported({ ...base, phd2_state: "pending" })).toBe(true);
    expect(phd2Reported({ ...base, phd2_state: "running" })).toBe(true);
  });

  it("is false for the idle empty string and for a snapshot without the field", () => {
    expect(phd2Reported({ ...base, phd2_state: "" })).toBe(false);
    expect(phd2Reported(base)).toBe(false);
  });
});

describe("phd2Phase", () => {
  it("is idle when no pass is reported, whatever the clock says", () => {
    expect(phd2Phase(base, NOW, NOW - 10 * PHD2_STALL_MS)).toBe("idle");
  });

  it("is processing for a pass the backend says transitioned moments ago", () => {
    const s: ScanStatus = { ...base, phd2_state: "running", phd2_state_at: (NOW - 5_000) / 1000 };
    expect(phd2Phase(s, NOW, null)).toBe("processing");
  });

  it("is stalled once the last backend transition is older than the guard window", () => {
    const s: ScanStatus = {
      ...base,
      phd2_state: "pending",
      phd2_state_at: (NOW - PHD2_STALL_MS - 1_000) / 1000,
    };
    expect(phd2Phase(s, NOW, NOW)).toBe("stalled");
  });

  it("prefers the backend transition time over the moment this client first saw the flag", () => {
    // A tab opened long after a stuck pass began must still call it stalled.
    const s: ScanStatus = {
      ...base,
      phd2_state: "pending",
      phd2_state_at: (NOW - 60 * 60_000) / 1000,
    };
    expect(phd2Phase(s, NOW, NOW - 1_000)).toBe("stalled");
  });

  it("restarts the window when a queued pass transitions to running", () => {
    // phd2_state_at is rewritten at the running transition, so a pass that is
    // genuinely progressing is never called stalled for having been queued a
    // long time.
    const queuedLong: ScanStatus = {
      ...base,
      phd2_state: "pending",
      phd2_state_at: (NOW - PHD2_STALL_MS - 1_000) / 1000,
    };
    expect(phd2Phase(queuedLong, NOW, null)).toBe("stalled");

    const nowRunning: ScanStatus = {
      ...queuedLong,
      phd2_state: "running",
      phd2_state_at: (NOW - 1_000) / 1000,
    };
    expect(phd2Phase(nowRunning, NOW, null)).toBe("processing");
  });

  it("falls back to the client-observed timestamp when the backend sends no transition time", () => {
    const s: ScanStatus = { ...base, phd2_state: "pending" };
    expect(phd2Phase(s, NOW, NOW - 1_000)).toBe("processing");
    expect(phd2Phase(s, NOW, NOW - PHD2_STALL_MS - 1_000)).toBe("stalled");
  });

  it("falls back to the completion time of a finished scan when nothing else is known", () => {
    const s: ScanStatus = {
      ...base,
      state: "complete",
      completed_at: (NOW - PHD2_STALL_MS - 1_000) / 1000,
      phd2_state: "pending",
    };
    expect(phd2Phase(s, NOW, null)).toBe("stalled");
  });

  it("reports processing rather than guessing when it has no reference at all", () => {
    const s: ScanStatus = { ...base, state: "ingesting", phd2_state: "pending" };
    expect(phd2Phase(s, NOW, null)).toBe("processing");
  });
});
