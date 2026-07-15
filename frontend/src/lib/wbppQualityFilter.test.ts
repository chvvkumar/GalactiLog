import { describe, it, expect } from "vitest";
import {
  evaluateRaw,
  evaluateRawDetailed,
  computeVerdicts,
  defaultConstraintValue,
  excludedSourceRelatives,
  excludedUnderSelectedLevels,
  isUnderRelativePath,
  scoreFrame,
  suggestRelaxation,
  RAW_METRIC_DEFAULTS,
  RAW_METRICS,
  type FrameVerdict,
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
    file_size: null,
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

  // The skip is a decision, not an accident. A constraint on a metric the
  // library only records for some frames (guiding on guided nights, FWHM after
  // the field was added) must not delete every frame that predates it. The
  // frames it would have deleted are visible as "unmeasured" instead, so the
  // skip is never silent.
  it("skips a missing metric deliberately rather than failing the frame", () => {
    const unguided = frame({ median_hfr: 2.0, eccentricity: 0.4 });
    // An impossible guiding constraint: if a missing metric auto-failed, this
    // would exclude the frame outright.
    const cons: RawConstraint[] = [{ metric: "guiding_rms_arcsec", value: 0.0001 }];
    expect(evaluateRaw(unguided, cons)).toBe("unmeasured");
    expect(evaluateRaw(unguided, [...cons, { metric: "median_hfr", value: 3.0 }])).toBe("pass");
    // ...while a frame that DOES carry the metric is still judged on it.
    expect(evaluateRaw(frame({ guiding_rms_arcsec: 0.8 }), cons)).toBe("fail");
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

describe("defaultConstraintValue", () => {
  // 0.6 is a starting point, not a standard. It sits at the top of the range
  // practitioners quote precisely so it does not reject rigs whose achievable
  // floor is genuinely high (a well-sampled short refractor can median above
  // 0.55), which a 0.42 or 0.5 default would do on their first export.
  it("starts eccentricity at 0.6", () => {
    expect(defaultConstraintValue("eccentricity")).toBe(0.6);
    expect(RAW_METRIC_DEFAULTS.eccentricity).toBe(0.6);
  });

  // Only eccentricity is dimensionless and rig-independent enough to carry a
  // constant. HFR/FWHM/RMS/ADU scale with pixel scale, focal length and
  // exposure, so shipping a number for them would be an invention.
  it("leaves every scale-dependent metric at 0", () => {
    for (const m of RAW_METRICS) {
      if (m === "eccentricity") continue;
      expect(defaultConstraintValue(m)).toBe(0);
      expect(RAW_METRIC_DEFAULTS[m]).toBe(undefined);
    }
  });
});

describe("verdict failedBy", () => {
  const dates = ["2026-03-15"];

  it("names the score gate and both numbers", () => {
    const verdicts = computeVerdicts({ "2026-03-15": detail([badFrame]) }, dates, "score", "session", 60, []);
    // badFrame scores well under 60; the reason must carry the arithmetic.
    expect(verdicts[0].failedBy).toMatch(/^score \d+ < 60$/);
  });

  it("names which raw constraint fired, with the frame's value and the limit", () => {
    const f = frame({ source_relative: "e.fits", eccentricity: 0.62 });
    const verdicts = computeVerdicts({ "2026-03-15": detail([f]) }, dates, "raw", "session", 60, [
      { metric: "eccentricity", value: 0.55 },
    ]);
    expect(verdicts[0].reason).toBe("fail");
    expect(verdicts[0].failedBy).toBe("ecc 0.62 > 0.55");
  });

  it("flips the comparison for a higher-is-better metric", () => {
    const f = frame({ detected_stars: 80 });
    const verdicts = computeVerdicts({ "2026-03-15": detail([f]) }, dates, "raw", "session", 60, [
      { metric: "detected_stars", value: 100 },
    ]);
    expect(verdicts[0].failedBy).toBe("stars 80 < 100");
  });

  it("leaves failedBy null for a passing or unmeasured frame", () => {
    const verdicts = computeVerdicts(
      { "2026-03-15": detail([goodFrame, unscorableFrame]) },
      dates, "score", "session", 60, [],
    );
    expect(verdicts.find((v) => v.reason === "pass")!.failedBy).toBeNull();
    expect(verdicts.find((v) => v.reason === "unmeasured")!.failedBy).toBeNull();
  });

  it("reports the first failing constraint in the user's own order", () => {
    const f = frame({ median_hfr: 5.0, eccentricity: 0.9 });
    const { failedBy } = evaluateRawDetailed(f, [
      { metric: "eccentricity", value: 0.5 },
      { metric: "median_hfr", value: 3.0 },
    ]);
    expect(failedBy).toBe("ecc 0.90 > 0.50");
  });
});

describe("suggestRelaxation", () => {
  const dates = ["2026-03-15"];
  const verdictsFor = (frames: FrameRecord[], cons: RawConstraint[]) =>
    computeVerdicts({ "2026-03-15": detail(frames) }, dates, "raw", "session", 60, cons);

  // The 10Micron case: a rig whose eccentricity genuinely floors around 0.55
  // meets a 0.5 constraint and loses every frame. The offer must come from its
  // own data, not from a table of conventions.
  it("offers the user's own best frame when an absolute constraint excludes everything", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.5519 }),
      frame({ source_relative: "b.fits", eccentricity: 0.58 }),
      frame({ source_relative: "c.fits", eccentricity: 0.61 }),
    ];
    const cons: RawConstraint[] = [{ metric: "eccentricity", value: 0.5 }];
    const r = suggestRelaxation(verdictsFor(frames, cons), "raw", 60, cons)!;
    expect(r).not.toBeNull();
    expect(r.metric).toBe("eccentricity");
    // Rounded outward so the best frame actually passes: 0.5519 -> 0.56.
    expect(r.value).toBe(0.56);
    expect(r.label).toBe("Eccentricity ≤ 0.56");
    expect(r.keeps).toBe(1);
  });

  it("counts keeps by re-running the real evaluation, not by estimating", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.55 }),
      frame({ source_relative: "b.fits", eccentricity: 0.55 }),
      frame({ source_relative: "c.fits", eccentricity: 0.9 }),
    ];
    const cons: RawConstraint[] = [{ metric: "eccentricity", value: 0.5 }];
    expect(suggestRelaxation(verdictsFor(frames, cons), "raw", 60, cons)!.keeps).toBe(2);
  });

  // `keeps` is verified against the real evaluator, so a relaxation that another
  // still-firing gate would cancel out reports 0 and is never offered. The
  // offer names the gate that actually frees frames, not the first in the list.
  it("skips a relaxation another gate would cancel out", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.55, median_hfr: 2.0 }),
      frame({ source_relative: "b.fits", eccentricity: 0.9, median_hfr: 2.0 }),
    ];
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 3.0 }, // both already pass this
      { metric: "eccentricity", value: 0.5 }, // both fail this: the binding gate
    ];
    const r = suggestRelaxation(verdictsFor(frames, cons), "raw", 60, cons)!;
    expect(r.metric).toBe("eccentricity");
    expect(r.value).toBe(0.55);
    expect(r.keeps).toBe(1);
  });

  // Two gates that each exclude every frame: loosening either one alone still
  // copies nothing. Saying so beats offering a button that changes the number
  // from zero to zero.
  it("returns null when no single relaxation frees anything", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.55, median_hfr: 2.0 }),
      frame({ source_relative: "b.fits", eccentricity: 0.55, median_hfr: 2.0 }),
    ];
    const cons: RawConstraint[] = [
      { metric: "median_hfr", value: 1.0 },
      { metric: "eccentricity", value: 0.5 },
    ];
    expect(suggestRelaxation(verdictsFor(frames, cons), "raw", 60, cons)).toBeNull();
  });

  it("offers the best achieved score in score mode", () => {
    const verdicts = computeVerdicts(
      { "2026-03-15": detail([badFrame]) }, dates, "score", "session", 90, [],
    );
    const r = suggestRelaxation(verdicts, "score", 90, [])!;
    expect(r.metric).toBeNull();
    expect(r.value).toBe(Math.floor(verdicts[0].score!));
    expect(r.label).toBe(`score ≥ ${r.value}`);
    expect(r.keeps).toBe(1);
  });

  // Nothing was measured, so no threshold lets anything in. Offering a button
  // here would be offering a fix that cannot work.
  it("returns null when every frame is unmeasured", () => {
    const verdicts = computeVerdicts(
      { "2026-03-15": detail([unscorableFrame]) }, dates, "score", "session", 60, [],
    );
    expect(suggestRelaxation(verdicts, "score", 60, [])).toBeNull();
  });

  it("returns null when no frame carries the constrained metric", () => {
    const cons: RawConstraint[] = [{ metric: "guiding_rms_arcsec", value: 0.1 }];
    expect(suggestRelaxation(verdictsFor([goodFrame], cons), "raw", 60, cons)).toBeNull();
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

describe("isUnderRelativePath", () => {
  it("matches the level itself and anything beneath it", () => {
    expect(isUnderRelativePath("M31/2026-07-01/Ha/a.fits", "M31/2026-07-01/Ha")).toBe(true);
    expect(isUnderRelativePath("M31/2026-07-01/Ha/sub/a.fits", "M31/2026-07-01/Ha")).toBe(true);
    expect(isUnderRelativePath("M31/2026-07-01/Ha", "M31/2026-07-01/Ha")).toBe(true);
    expect(isUnderRelativePath("M31/2026-07-01/Ha/a.fits", "M31/2026-07-01")).toBe(true);
  });

  it("matches on component boundaries, never as a bare substring", () => {
    // The distinction the backend's map_excluded_to_ops test asserts: a sibling
    // whose name merely starts with the level's name is NOT inside it.
    expect(isUnderRelativePath("M31/2026-07-01/Ha_old/a.fits", "M31/2026-07-01/Ha")).toBe(false);
    expect(isUnderRelativePath("M31/2026-07-01/Halpha/a.fits", "M31/2026-07-01/Ha")).toBe(false);
    expect(isUnderRelativePath("M31/2026-07-01/OIII/a.fits", "M31/2026-07-01/Ha")).toBe(false);
  });

  it("treats an empty level as the fits root, which contains everything", () => {
    expect(isUnderRelativePath("M31/2026-07-01/Ha/a.fits", "")).toBe(true);
  });

  it("tolerates leading and trailing slashes on either side", () => {
    expect(isUnderRelativePath("/M31/2026-07-01/Ha/a.fits", "M31/2026-07-01/Ha/")).toBe(true);
  });
});

describe("excludedUnderSelectedLevels", () => {
  const verdict = (sessionDate: string, source_relative: string, keep: boolean): FrameVerdict =>
    ({ frame: frame({ source_relative }), sessionDate, score: null, keep, reason: keep ? "pass" : "fail", failedBy: null });

  it("drops excluded frames that sit outside the session's selected level", () => {
    const verdicts = [
      verdict("2026-07-01", "M31/2026-07-01/Ha/bad.fits", false),
      verdict("2026-07-01", "M31/2026-07-01/OIII/bad.fits", false),
      verdict("2026-07-01", "M31/2026-07-01/Ha/good.fits", true),
    ];
    const result = excludedUnderSelectedLevels(
      verdicts,
      new Map([["2026-07-01", "M31/2026-07-01/Ha"]]),
    );
    // The OIII frame is excluded by the filter but the Ha copy never touches it,
    // so it must not be deducted from Ha's count or bytes.
    expect(result.map((v) => v.frame.source_relative)).toEqual(["M31/2026-07-01/Ha/bad.fits"]);
  });

  it("tests each verdict only against its own session's level", () => {
    const verdicts = [
      verdict("2026-07-01", "M31/2026-07-01/Ha/bad.fits", false),
      verdict("2026-07-02", "M31/2026-07-02/Ha/bad.fits", false),
    ];
    const result = excludedUnderSelectedLevels(
      verdicts,
      new Map([
        ["2026-07-01", "M31/2026-07-01/Ha"],
        ["2026-07-02", "M31/2026-07-02/Ha"],
      ]),
    );
    // One each, counted once -- not cross-matched against the other's level.
    expect(result).toHaveLength(2);
  });

  it("ignores sessions with no selected level", () => {
    const verdicts = [verdict("2026-07-01", "M31/2026-07-01/Ha/bad.fits", false)];
    expect(excludedUnderSelectedLevels(verdicts, new Map())).toEqual([]);
  });
});
