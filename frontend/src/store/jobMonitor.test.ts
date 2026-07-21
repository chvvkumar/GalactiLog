import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./wbppCopyJob", () => ({ wbppCopyActiveJob: vi.fn(() => null) }));

import { wbppCopyActiveJob } from "./wbppCopyJob";
import { aggregateProgress, monitorJobs, stripProgress } from "./jobMonitor";
import type { ActiveJob } from "../api/types";

const job = (progress?: number): ActiveJob => ({
  id: "x",
  category: "scan",
  label: "Job",
  progress,
  startedAt: 0,
  cancelable: false,
});

describe("aggregateProgress", () => {
  it("returns null for an empty job list", () => {
    expect(aggregateProgress([])).toBeNull();
  });

  it("returns null when every job is indeterminate", () => {
    expect(aggregateProgress([job(), job()])).toBeNull();
  });

  it("averages determinate jobs and ignores indeterminate ones", () => {
    expect(aggregateProgress([job(0.2), job(0.6), job()])).toBeCloseTo(0.4, 5);
  });

  it("clamps to the [0, 1] range", () => {
    expect(aggregateProgress([job(1.4)])).toBe(1);
  });
});

describe("monitorJobs", () => {
  beforeEach(() => {
    vi.mocked(wbppCopyActiveJob).mockReturnValue(null);
  });

  it("appends the WBPP copy job when one is running", () => {
    vi.mocked(wbppCopyActiveJob).mockReturnValue({
      ...job(0.5),
      id: "wbpp-copy",
      category: "wbpp_copy",
    });
    expect(monitorJobs().some((j) => j.id === "wbpp-copy")).toBe(true);
    expect(stripProgress()).toBeCloseTo(0.5, 5);
  });

  it("omits the WBPP copy job when idle", () => {
    expect(monitorJobs().some((j) => j.id === "wbpp-copy")).toBe(false);
  });
});
