import { describe, it, expect } from "vitest";
import { wireActiveJobSources, activeJobs, scanStatusToJob } from "./activeJobs";
import type { ScanStatus, RebuildStatus } from "../api/types";

const baseScanStatus: ScanStatus = {
  state: "idle",
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

const baseRebuildStatus: RebuildStatus = {
  state: "idle",
  mode: "full",
  message: "",
  started_at: null,
  completed_at: null,
  details: {},
};

function wire(scan: ScanStatus, rebuild: RebuildStatus) {
  wireActiveJobSources(
    () => scan,
    () => rebuild,
    async () => {}
  );
}

describe("activeJobs percent-to-fraction conversion", () => {
  it("converts scan envelope percent (0-100) to a 0-1 progress fraction while ingesting", () => {
    wire(
      { ...baseScanStatus, state: "ingesting", total: 200, completed: 91, failed: 0, percent: 45.5 },
      baseRebuildStatus
    );

    const scanJob = activeJobs().find((j) => j.category === "scan");
    expect(scanJob?.progress).toBeCloseTo(0.455, 5);
  });

  it("falls back to the counter ratio when percent is absent while ingesting", () => {
    wire(
      { ...baseScanStatus, state: "ingesting", total: 200, completed: 91, failed: 9 },
      baseRebuildStatus
    );

    const scanJob = activeJobs().find((j) => j.category === "scan");
    expect(scanJob?.progress).toBeCloseTo(100 / 200, 5);
  });

  it("stays indeterminate during discovery even though the envelope reports a percent", () => {
    // Discovery has no fixed total; scan_state.py resets the envelope to 0/0
    // (percent 0.0) during this phase, which must not render a stuck 0% bar.
    wire(
      { ...baseScanStatus, state: "scanning", discovered: 12, percent: 0 },
      baseRebuildStatus
    );

    const scanJob = activeJobs().find((j) => j.category === "scan");
    expect(scanJob?.progress).toBeUndefined();
  });

  it("converts rebuild envelope percent (0-100) to a 0-1 progress fraction", () => {
    wire(baseScanStatus, {
      ...baseRebuildStatus,
      state: "running",
      mode: "full",
      step: 62,
      total_steps: 100,
      percent: 62.3,
    });

    const rebuildJob = activeJobs().find((j) => j.category === "rebuild");
    expect(rebuildJob?.progress).toBeCloseTo(0.623, 5);
  });

  it("leaves rebuild progress undefined (indeterminate) when percent is absent", () => {
    wire(baseScanStatus, { ...baseRebuildStatus, state: "running", mode: "smart" });

    const rebuildJob = activeJobs().find((j) => j.category === "rebuild");
    expect(rebuildJob?.progress).toBeUndefined();
  });

  it("keeps the human-readable rebuild message as subLabel, unchanged by the numeric bar", () => {
    wire(baseScanStatus, {
      ...baseRebuildStatus,
      state: "running",
      mode: "retry",
      message: "Resolving 5/12 object names...",
      step: 5,
      total_steps: 12,
      percent: 41.7,
    });

    const rebuildJob = activeJobs().find((j) => j.category === "rebuild");
    expect(rebuildJob?.subLabel).toBe("Resolving 5/12 object names...");
    expect(rebuildJob?.progress).toBeCloseTo(0.417, 5);
  });
});

describe("guide-log pass in the job monitor", () => {
  const noop = async () => {};

  it("adds a guide-log line to the running scan job while a pass is queued", () => {
    const job = scanStatusToJob(
      { ...baseScanStatus, state: "ingesting", total: 200, completed: 100, phd2_state: "pending" },
      noop,
      "processing"
    );

    expect(job?.label).toBe("Ingesting files");
    expect(job?.subLabel).toContain("100 / 200 files");
    expect(job?.subLabel).toContain("Guide logs processing");
  });

  it("counts the guide logs once the backend publishes totals", () => {
    const job = scanStatusToJob(
      {
        ...baseScanStatus,
        state: "ingesting",
        total: 200,
        completed: 100,
        phd2_state: "running",
        phd2_found: 25,
        phd2_ingested: 7,
        phd2_failed: 1,
      },
      noop,
      "processing"
    );

    expect(job?.subLabel).toContain("Guide logs processing (8 of 25)");
  });

  it("keeps a job on screen for the guide-log tail after the image scan finishes", () => {
    const job = scanStatusToJob(
      { ...baseScanStatus, state: "complete", phd2_state: "running", phd2_found: 25, phd2_ingested: 5 },
      noop,
      "processing"
    );

    expect(job?.label).toBe("Processing guide logs");
    expect(job?.subLabel).toBe("5 of 25 logs");
    expect(job?.progress).toBeCloseTo(5 / 25, 5);
    expect(job?.cancelable).toBe(false);
  });

  it("drops the job when the guard calls a pending pass stalled", () => {
    const job = scanStatusToJob(
      { ...baseScanStatus, state: "complete", phd2_state: "pending" },
      noop,
      "stalled"
    );

    expect(job).toBeNull();
  });

  it("is unchanged for an idle scan with no pass at all", () => {
    expect(scanStatusToJob({ ...baseScanStatus, state: "idle" }, noop, "idle")).toBeNull();
  });
});
