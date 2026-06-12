import { describe, it, expect } from "vitest";
import {
  groupKey,
  madZ,
  bandForZ,
  combinedScore,
  scoreToRowClass,
  bandToCellClass,
  MIN_GROUP,
  type MetricBaseline,
} from "./frameQuality";

describe("groupKey", () => {
  it("builds 'telescope|camera|filter'", () => {
    expect(
      groupKey({ telescope: "WO", camera: "2600", filter_used: "Ha" }),
    ).toBe("WO|2600|Ha");
  });

  it("renders null components as empty strings", () => {
    expect(
      groupKey({ telescope: null, camera: "2600", filter_used: null }),
    ).toBe("|2600|");
  });

  it("renders undefined components as empty strings", () => {
    expect(groupKey({})).toBe("||");
  });
});

describe("madZ", () => {
  const baseline = (median: number, mad: number, n: number): MetricBaseline => ({
    median,
    mad,
    n,
  });

  it("returns null when the value is null", () => {
    expect(madZ(null, baseline(2.1, 0.37, 20))).toBeNull();
  });

  it("returns null when the baseline is missing", () => {
    expect(madZ(2.8, undefined)).toBeNull();
  });

  it("returns null when median is missing", () => {
    expect(madZ(2.8, { median: null, mad: 0.37, n: 20 })).toBeNull();
  });

  it("returns null when mad is missing", () => {
    expect(madZ(2.8, { median: 2.1, mad: null, n: 20 })).toBeNull();
  });

  it("returns null when n < MIN_GROUP", () => {
    expect(madZ(2.8, baseline(2.1, 0.37, MIN_GROUP - 1))).toBeNull();
  });

  it("returns null when mad === 0", () => {
    expect(madZ(2.8, baseline(2.1, 0, 20))).toBeNull();
  });

  it("computes (value - median)/mad for a higher-is-worse metric", () => {
    // HFR: value 2.8, median 2.1, mad 0.37, n 20 -> z ≈ 1.89
    expect(madZ(2.8, baseline(2.1, 0.37, 20))).toBeCloseTo(1.8919, 4);
  });

  it("flips the sign when higherIsBetter is true", () => {
    // detected_stars: value 80, median 100, mad 10, n 20 -> raw z -2 -> flipped +2
    expect(madZ(80, baseline(100, 10, 20), true)).toBe(2);
  });
});

describe("bandForZ", () => {
  it("returns neutral for null", () => {
    expect(bandForZ(null)).toBe("neutral");
  });

  it("returns better for z = -1 (inclusive boundary)", () => {
    expect(bandForZ(-1)).toBe("better");
  });

  it("returns neutral for z = 0", () => {
    expect(bandForZ(0)).toBe("neutral");
  });

  it("returns watch for z = 1.5 (inclusive boundary)", () => {
    expect(bandForZ(1.5)).toBe("watch");
  });

  it("returns reject for z = 3 (inclusive boundary)", () => {
    expect(bandForZ(3)).toBe("reject");
  });

  it("keeps neutral just below the watch boundary", () => {
    expect(bandForZ(1.4999)).toBe("neutral");
  });

  it("keeps watch just below the reject boundary", () => {
    expect(bandForZ(2.9999)).toBe("watch");
  });

  it("returns better just at the better boundary and reject above 3", () => {
    expect(bandForZ(-1.0001)).toBe("better");
    expect(bandForZ(3.5)).toBe("reject");
  });
});

describe("combinedScore", () => {
  it("returns null when all axes are null", () => {
    expect(combinedScore(null, null, null)).toBeNull();
  });

  it("maps a median frame (all z = 0) to 50", () => {
    expect(combinedScore(0, 0, 0)).toBe(50);
  });

  it("applies weights 0.5 / 0.25 / 0.25", () => {
    // zc = (1*0.5 + 1*0.25 + 1*0.25) / 1 = 1 -> 50 - 16.7
    expect(combinedScore(1, 1, 1)).toBeCloseTo(33.3, 5);
  });

  it("renormalizes the remaining weights when an axis is null", () => {
    // only signal present -> wsum 0.5, zc = (2*0.5)/0.5 = 2 -> 50 - 16.7*2
    expect(combinedScore(2, null, null)).toBeCloseTo(50 - 16.7 * 2, 5);
    // sharp + round present -> wsum 0.5, zc = (1*0.25 + 1*0.25)/0.5 = 1
    expect(combinedScore(null, 1, 1)).toBeCloseTo(50 - 16.7, 5);
  });

  it("clamps |z| > 3", () => {
    // very negative (good) clamps to -3 -> 50 + 50.1 = 100.1
    expect(combinedScore(-10, -10, -10)).toBeCloseTo(50 + 16.7 * 3, 5);
    // very positive (bad) clamps to +3 -> 50 - 50.1 = -0.1
    expect(combinedScore(10, 10, 10)).toBeCloseTo(50 - 16.7 * 3, 5);
  });
});

describe("bandToCellClass", () => {
  it("returns the expected theme class per band", () => {
    expect(bandToCellClass("better")).toBe("text-theme-success");
    expect(bandToCellClass("watch")).toBe("text-theme-warning");
    expect(bandToCellClass("reject")).toBe("text-theme-error");
    expect(bandToCellClass("neutral")).toBe("text-theme-text-primary");
  });
});

describe("scoreToRowClass", () => {
  it("returns empty string for null", () => {
    expect(scoreToRowClass(null)).toBe("");
  });

  it("returns the success tint at or above 60", () => {
    expect(scoreToRowClass(60)).toBe("bg-theme-success/10");
    expect(scoreToRowClass(85)).toBe("bg-theme-success/10");
  });

  it("returns empty string in the neutral 45..60 band", () => {
    expect(scoreToRowClass(45)).toBe("");
    expect(scoreToRowClass(50)).toBe("");
    expect(scoreToRowClass(59.9)).toBe("");
  });

  it("returns the warning tint in the 30..45 band", () => {
    expect(scoreToRowClass(30)).toBe("bg-theme-warning/15");
    expect(scoreToRowClass(44.9)).toBe("bg-theme-warning/15");
  });

  it("returns the error tint below 30", () => {
    expect(scoreToRowClass(29.9)).toBe("bg-theme-error/20");
    expect(scoreToRowClass(0)).toBe("bg-theme-error/20");
  });
});
