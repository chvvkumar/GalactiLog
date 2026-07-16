import { describe, it, expect } from "vitest";
import {
  evaluateRaw,
  computeVerdicts,
  excludedSourceRelatives,
  scoreFrame,
  type RawConstraint,
} from "./wbppQualityFilter";
import type { SessionDetail, FrameRecord } from "../api/types";
import type { Baselines } from "../utils/frameQuality";

// Minimal FrameRecord factory: all metrics null unless overridden.
function frame(overrides: Partial<FrameRecord>): FrameRecord {
  return {
    timestamp: "2026-03-15T22:00:00Z",
    filter_used: "Ha",
    exposure_time: 300,
    median_hfr: null,
    eccentricity: null,
    sensor_temp: null,
    gain: null,
    file_name: "light_001.fits",
    image_id: "img-1",
    file_path: "/data/2026/03/15/Target/Ha/light_001.fits",
    source_relative: "2026/03/15/Target/Ha/light_001.fits",
    thumbnail_url: null,
    hfr_stdev: null,
    fwhm: null,
    detected_stars: null,
    guiding_rms_arcsec: null,
    guiding_rms_ra_arcsec: null,
    guiding_rms_dec_arcsec: null,
    adu_stdev: null,
    adu_mean: null,
    adu_median: null,
    adu_min: null,
    adu_max: null,
    focuser_position: null,
    focuser_temp: null,
    rotator_position: null,
    pier_side: null,
    airmass: null,
    ambient_temp: null,
    dew_point: null,
    humidity: null,
    pressure: null,
    wind_speed: null,
    wind_direction: null,
    wind_gust: null,
    cloud_cover: null,
    sky_quality: null,
    rig: null,
    ...overrides,
  };
}

// Baseline group for "T|C|Ha" with n >= MIN_GROUP and non-zero MAD.
const baselines: Baselines = {
  "T|C|Ha": {
    median_hfr: { median: 2.0, mad: 0.3, n: 20 },
    eccentricity: { median: 0.4, mad: 0.05, n: 20 },
    detected_stars: { median: 100, mad: 10, n: 20 },
    fwhm: { median: 2.5, mad: 0.3, n: 20 },
    adu_median: { median: 1000, mad: 50, n: 20 },
  },
};

function detail(frames: FrameRecord[]): SessionDetail {
  return {
    session_date: "2026-03-15",
    equipment: { telescope: "T", camera: "C" },
    rigs: [],
    frames,
    session_baselines: baselines,
    rig_baselines: baselines,
  } as unknown as SessionDetail;
}

// A frame clearly better than baseline on all three axes -> high score.
const goodFrame = frame({
  source_relative: "good.fits",
  median_hfr: 1.7,
  eccentricity: 0.35,
  detected_stars: 130,
});
// A frame clearly worse than baseline on all three axes -> low score.
const badFrame = frame({
  source_relative: "bad.fits",
  median_hfr: 2.6,
  eccentricity: 0.5,
  detected_stars: 80,
});
// A frame whose filter has no baseline -> all axes null -> null score.
const unscorableFrame = frame({
  source_relative: "unscorable.fits",
  filter_used: "OIII",
  median_hfr: 2.0,
  eccentricity: 0.4,
  detected_stars: 100,
});

describe("scoreFrame (composite)", () => {
  it("scores a better-than-baseline frame above 60", () => {
    const s = scoreFrame(detail([goodFrame]), goodFrame, "session");
    expect(s).not.toBeNull();
    expect(s!).toBeGreaterThanOrEqual(60);
  });

  it("scores a worse-than-baseline frame below 60", () => {
    const s = scoreFrame(detail([badFrame]), badFrame, "session");
    expect(s).not.toBeNull();
    expect(s!).toBeLessThan(60);
  });

  it("returns null when no baseline group matches (unmeasured)", () => {
    expect(scoreFrame(detail([unscorableFrame]), unscorableFrame, "session")).toBeNull();
  });
});

describe("computeVerdicts composite mode", () => {
  const dates = ["2026-03-15"];
  it("keeps frames at/above threshold 60 and excludes below", () => {
    const d = detail([goodFrame, badFrame]);
    const verdicts = computeVerdicts({ "2026-03-15": d }, dates, "score", "session", 60, []);
    const good = verdicts.find((v) => v.frame.source_relative === "good.fits")!;
    const bad = verdicts.find((v) => v.frame.source_relative === "bad.fits")!;
    expect(good.reason).toBe("pass");
    expect(good.keep).toBe(true);
    expect(bad.reason).toBe("fail");
    expect(bad.keep).toBe(false);
  });

  it("marks a null composite score as unmeasured (excluded)", () => {
    const d = detail([unscorableFrame]);
    const verdicts = computeVerdicts({ "2026-03-15": d }, dates, "score", "session", 60, []);
    expect(verdicts[0].reason).toBe("unmeasured");
    expect(verdicts[0].keep).toBe(false);
  });
});

describe("evaluateRaw (partial-metric AND)", () => {
  it("passes when all present metrics satisfy their constraints", () => {
    const f = frame({ median_hfr: 2.0, detected_stars: 100 });
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 3.0 },
      { metric: "detected_stars", value: 50 },
    ];
    expect(evaluateRaw(f, cons)).toBe("pass");
  });

  it("fails when one present metric violates its constraint", () => {
    const f = frame({ median_hfr: 2.0, detected_stars: 100 });
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 1.5 }, // 2.0 > 1.5 -> fail (lower-is-better)
      { metric: "detected_stars", value: 50 },
    ];
    expect(evaluateRaw(f, cons)).toBe("fail");
  });

  it("judges only on present metrics (missing metric skipped)", () => {
    const f = frame({ median_hfr: 2.0 }); // guiding_rms_arcsec is null
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 3.0 }, // present, passes
      { metric: "guiding_rms_arcsec", value: 1.0 }, // missing, skipped
    ];
    expect(evaluateRaw(f, cons)).toBe("pass");
  });

  it("fails on a present metric even when another is missing", () => {
    const f = frame({ median_hfr: 5.0 }); // fails; guiding missing
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 3.0 },
      { metric: "guiding_rms_arcsec", value: 1.0 },
    ];
    expect(evaluateRaw(f, cons)).toBe("fail");
  });

  it("is unmeasured when none of the constrained metrics are present", () => {
    const f = frame({ median_hfr: 2.0 }); // constraint only on a missing metric
    const cons: RawConstraint[] = [{ metric: "guiding_rms_arcsec", value: 1.0 }];
    expect(evaluateRaw(f, cons)).toBe("unmeasured");
  });

  it("is unmeasured when there are zero active constraints", () => {
    expect(evaluateRaw(frame({ median_hfr: 2.0 }), [])).toBe("unmeasured");
  });

  it("honors higher-is-better direction for detected_stars", () => {
    const cons: RawConstraint[] = [{ metric: "detected_stars", value: 100 }];
    expect(evaluateRaw(frame({ detected_stars: 120 }), cons)).toBe("pass");
    expect(evaluateRaw(frame({ detected_stars: 80 }), cons)).toBe("fail");
  });
});

describe("excludedSourceRelatives", () => {
  it("returns the source_relative of every non-kept frame", () => {
    const d = detail([goodFrame, badFrame, unscorableFrame]);
    const verdicts = computeVerdicts({ "2026-03-15": d }, ["2026-03-15"], "score", "session", 60, []);
    const excluded = excludedSourceRelatives(verdicts);
    expect(excluded).toContain("bad.fits");
    expect(excluded).toContain("unscorable.fits");
    expect(excluded).not.toContain("good.fits");
    expect(excluded).toHaveLength(2);
  });
});
