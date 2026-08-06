import { describe, it, expect } from "vitest";
import type { components } from "./generated/schema";
import type { FrameRecord, ScanStatus } from "./types";

type GeneratedScanState = components["schemas"]["ScanStateResponse"];

// Compile-time guard: the PHD2 counters this mirror declares must be the
// ones the generated ScanStateResponse actually reports. If the backend
// renames one, this object stops compiling and tsc names the field, instead
// of the UI silently reading undefined forever.
const generatedPhd2Fields: Pick<
  GeneratedScanState,
  "phd2_state" | "phd2_found" | "phd2_ingested" | "phd2_failed" | "phd2_checked"
> = {
  phd2_state: "running",
  phd2_found: 3,
  phd2_ingested: 2,
  phd2_failed: 1,
  phd2_checked: 3,
};

describe("ScanStatus mirror", () => {
  it("carries the PHD2 guide-log counters the scan status endpoint reports", () => {
    const status: ScanStatus = {
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
      phd2_state: "running",
      phd2_found: 3,
      phd2_ingested: 2,
      phd2_failed: 1,
      phd2_checked: 3,
      phd2_state_at: 1_753_800_000,
    };

    expect(status.phd2_state).toBe("running");
    expect(status.phd2_found).toBe(generatedPhd2Fields.phd2_found);
    expect(status.phd2_ingested).toBe(2);
    expect(status.phd2_failed).toBe(1);
    expect(status.phd2_checked).toBe(generatedPhd2Fields.phd2_checked);
    expect(status.phd2_state_at).toBe(1_753_800_000);
  });

  it("still describes a status snapshot that predates the PHD2 fields", () => {
    const status: ScanStatus = {
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

    expect(status.phd2_state).toBeUndefined();
  });
});

describe("FrameRecord mirror", () => {
  it("carries the guiding RMS provenance value the correlation pass writes", () => {
    const sources: FrameRecord["guiding_rms_source"][] = ["csv", "phd2", null, undefined];
    expect(sources).toHaveLength(4);
  });
});
