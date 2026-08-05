import { describe, it, expect } from "vitest";
import {
  RMS_PHD2_GLYPH,
  rmsSourceTitle,
  sessionRmsSourceTitle,
  summarizeRmsSources,
} from "./SessionAccordionCard";

describe("rmsSourceTitle", () => {
  it("names the guide log behind a correlated value", () => {
    expect(rmsSourceTitle("RMS", "phd2")).toBe("RMS from PHD2 guide log");
  });

  it("names the CSV sidecar behind an imported value", () => {
    expect(rmsSourceTitle("RMS RA", "csv")).toBe("RMS RA from NINA CSV sidecar");
  });

  it("says nothing at all when the row predates provenance", () => {
    expect(rmsSourceTitle("RMS", null)).toBeUndefined();
    expect(rmsSourceTitle("RMS", undefined)).toBeUndefined();
  });
});

describe("summarizeRmsSources", () => {
  it("reports the single source when every frame agrees", () => {
    expect(summarizeRmsSources([{ guiding_rms_source: "csv" }, { guiding_rms_source: "csv" }])).toBe("csv");
    expect(summarizeRmsSources([{ guiding_rms_source: "phd2" }])).toBe("phd2");
  });

  it("reports a mix when a session was filled from both pipelines", () => {
    expect(
      summarizeRmsSources([
        { guiding_rms_source: "csv" },
        { guiding_rms_source: "phd2" },
        { guiding_rms_source: null },
      ])
    ).toBe("mixed");
  });

  it("reports nothing for frames that carry no provenance", () => {
    expect(summarizeRmsSources([{ guiding_rms_source: null }, {}])).toBeNull();
    expect(summarizeRmsSources([])).toBeNull();
  });
});

describe("sessionRmsSourceTitle", () => {
  it("describes each summary in words, and stays silent when there is none", () => {
    expect(sessionRmsSourceTitle("phd2")).toBe("Median RMS from PHD2 guide logs");
    expect(sessionRmsSourceTitle("csv")).toBe("Median RMS from NINA CSV sidecars");
    expect(sessionRmsSourceTitle("mixed")).toBe(
      "Median RMS from a mix of NINA CSV sidecars and PHD2 guide logs"
    );
    expect(sessionRmsSourceTitle(null)).toBeUndefined();
  });
});

describe("RMS_PHD2_GLYPH", () => {
  it("is a dagger, not an emoji, so it survives a monospace numeric column", () => {
    expect(RMS_PHD2_GLYPH).toBe("†");
    expect(RMS_PHD2_GLYPH).toHaveLength(1);
  });
});
