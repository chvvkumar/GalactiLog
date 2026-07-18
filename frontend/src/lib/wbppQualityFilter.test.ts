import { describe, it, expect } from "vitest";
import {
  evaluateRaw,
  evaluateRawDetailed,
  computeVerdicts,
  emptyConstraintFor,
  ECC_PRESETS,
  excludedSourceRelatives,
  excludedUnderSelectedLevels,
  isUnderRelativePath,
  suggestRelaxation,
  qualityTotals,
  METRIC_DEFS,
  METRIC_KEYS,
  type FrameVerdict,
  type QualityConfig,
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

// Constraint factory: enabled by default so tests read as "an active gate".
function con(
  metric: RawConstraint["metric"],
  op: RawConstraint["op"],
  value: number,
  enabled = true,
): RawConstraint {
  return { metric, op, value, enabled };
}

function config(constraints: RawConstraint[], baseline: QualityConfig["baseline"] = "session"): QualityConfig {
  return { baseline, constraints };
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

// Rig-scoped baselines deliberately different from session, so a test can
// prove defaultConstraintFor honored config.baseline.
const rigBaselines: Baselines = {
  "T|C|Ha": {
    median_hfr: { median: 3.0, mad: 0.1, n: 40 },
    eccentricity: { median: 0.5, mad: 0.02, n: 40 },
    detected_stars: { median: 200, mad: 20, n: 40 },
    fwhm: { median: 3.5, mad: 0.1, n: 40 },
  },
};

function detail(frames: FrameRecord[]): SessionDetail {
  return {
    session_date: "2026-03-15",
    equipment: { telescope: "T", camera: "C" },
    rigs: [],
    frames,
    session_baselines: baselines,
    rig_baselines: rigBaselines,
  } as unknown as SessionDetail;
}

const goodFrame = frame({
  source_relative: "good.fits",
  median_hfr: 1.7,
  eccentricity: 0.35,
  detected_stars: 130,
});
const badFrame = frame({
  source_relative: "bad.fits",
  median_hfr: 2.6,
  eccentricity: 0.5,
  detected_stars: 80,
});
// A frame carrying none of the constrained metrics.
const blankFrame = frame({ source_relative: "blank.fits" });

const dates = ["2026-03-15"];
const verdictsFor = (frames: FrameRecord[], constraints: RawConstraint[]) =>
  computeVerdicts({ "2026-03-15": detail(frames) }, dates, config(constraints));

describe("evaluateRaw (partial-metric AND over enabled constraints)", () => {
  it("passes when all present metrics satisfy their constraints", () => {
    const f = frame({ median_hfr: 2.0, detected_stars: 100 });
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0), con("stars", "gte", 50)])).toBe("pass");
  });

  it("fails when one present metric violates its constraint", () => {
    const f = frame({ median_hfr: 2.0, detected_stars: 100 });
    expect(evaluateRaw(f, [con("hfr", "lte", 1.5), con("stars", "gte", 50)])).toBe("fail");
  });

  it("judges only on present metrics (missing metric skipped)", () => {
    const f = frame({ median_hfr: 2.0 }); // guiding_rms_arcsec is null
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0), con("rms", "lte", 1.0)])).toBe("pass");
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
    const cons = [con("rms", "lte", 0.0001)];
    expect(evaluateRaw(unguided, cons)).toBe("unmeasured");
    expect(evaluateRaw(unguided, [...cons, con("hfr", "lte", 3.0)])).toBe("pass");
    // ...while a frame that DOES carry the metric is still judged on it.
    expect(evaluateRaw(frame({ guiding_rms_arcsec: 0.8 }), cons)).toBe("fail");
  });

  it("fails on a present metric even when another is missing", () => {
    const f = frame({ median_hfr: 5.0 }); // fails; guiding missing
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0), con("rms", "lte", 1.0)])).toBe("fail");
  });

  it("is unmeasured when none of the enabled constrained metrics are present", () => {
    const f = frame({ median_hfr: 2.0 }); // constraint only on a missing metric
    expect(evaluateRaw(f, [con("rms", "lte", 1.0)])).toBe("unmeasured");
  });

  it("honors op direction for detected_stars (gte)", () => {
    const cons = [con("stars", "gte", 100)];
    expect(evaluateRaw(frame({ detected_stars: 120 }), cons)).toBe("pass");
    expect(evaluateRaw(frame({ detected_stars: 80 }), cons)).toBe("fail");
  });
});

describe("enabled flag", () => {
  it("passes every frame when zero constraints are enabled", () => {
    // An empty filter is no filter -- not a filter that quarantines the whole
    // library as unmeasured.
    expect(evaluateRaw(frame({ median_hfr: 2.0 }), [])).toBe("pass");
    expect(evaluateRaw(blankFrame, [])).toBe("pass");
    expect(evaluateRaw(frame({ median_hfr: 99 }), [con("hfr", "lte", 1.0, false)])).toBe("pass");
  });

  it("treats a disabled constraint exactly like a deleted one", () => {
    const f = frame({ median_hfr: 5.0, eccentricity: 0.4 });
    // Enabled: the HFR gate fails the frame.
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0), con("ecc", "lte", 0.6)])).toBe("fail");
    // Disabled: only the ecc gate judges, and it passes.
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0, false), con("ecc", "lte", 0.6)])).toBe("pass");
  });

  it("does not count a disabled constraint's metric toward 'present'", () => {
    // The frame carries HFR, but the only ENABLED gate is on a missing metric,
    // so the frame is unmeasured -- the disabled gate must not smuggle it in.
    const f = frame({ median_hfr: 2.0 });
    expect(evaluateRaw(f, [con("hfr", "lte", 3.0, false), con("rms", "lte", 1.0)])).toBe("unmeasured");
  });
});

describe("computeVerdicts", () => {
  it("keeps passing frames and excludes failing ones", () => {
    const verdicts = verdictsFor([goodFrame, badFrame], [con("ecc", "lte", 0.45)]);
    const good = verdicts.find((v) => v.frame.source_relative === "good.fits")!;
    const bad = verdicts.find((v) => v.frame.source_relative === "bad.fits")!;
    expect(good.reason).toBe("pass");
    expect(good.keep).toBe(true);
    expect(bad.reason).toBe("fail");
    expect(bad.keep).toBe(false);
  });

  it("marks a frame with none of the constrained metrics as unmeasured (excluded)", () => {
    const verdicts = verdictsFor([blankFrame], [con("ecc", "lte", 0.45)]);
    expect(verdicts[0].reason).toBe("unmeasured");
    expect(verdicts[0].keep).toBe(false);
  });

  it("passes everything when the config has no enabled constraints", () => {
    const verdicts = verdictsFor([goodFrame, badFrame, blankFrame], []);
    expect(verdicts.every((v) => v.keep && v.reason === "pass")).toBe(true);
  });
});

describe("verdict failedBy", () => {
  it("names which constraint fired, with the frame's value and the limit", () => {
    const f = frame({ source_relative: "e.fits", eccentricity: 0.62 });
    const verdicts = verdictsFor([f], [con("ecc", "lte", 0.55)]);
    expect(verdicts[0].reason).toBe("fail");
    expect(verdicts[0].failedBy).toBe("ecc 0.62 > 0.55");
  });

  it("flips the comparison for a gte constraint", () => {
    const verdicts = verdictsFor([frame({ detected_stars: 80 })], [con("stars", "gte", 100)]);
    expect(verdicts[0].failedBy).toBe("stars 80 < 100");
  });

  it("leaves failedBy null for a passing or unmeasured frame", () => {
    const verdicts = verdictsFor([goodFrame, blankFrame], [con("ecc", "lte", 0.6)]);
    expect(verdicts.find((v) => v.reason === "pass")!.failedBy).toBeNull();
    expect(verdicts.find((v) => v.reason === "unmeasured")!.failedBy).toBeNull();
  });

  it("reports the first failing enabled constraint in the user's own order", () => {
    const f = frame({ median_hfr: 5.0, eccentricity: 0.9 });
    const { failedBy } = evaluateRawDetailed(f, [
      con("ecc", "lte", 0.5),
      con("hfr", "lte", 3.0),
    ]);
    expect(failedBy).toBe("ecc 0.90 > 0.50");
  });

  it("collects EVERY violated gate in failures, failedBy staying the first", () => {
    const f = frame({ median_hfr: 5.0, eccentricity: 0.9 });
    const { failedBy, failures } = evaluateRawDetailed(f, [
      con("ecc", "lte", 0.5),
      con("hfr", "lte", 3.0),
    ]);
    expect(failures).toEqual([
      { metric: "ecc", text: "ecc 0.90 > 0.50" },
      { metric: "hfr", text: "HFR 5.00 > 3.00" },
    ]);
    expect(failedBy).toBe("ecc 0.90 > 0.50");
  });

  it("never blames a disabled constraint", () => {
    const f = frame({ median_hfr: 5.0, eccentricity: 0.9 });
    const { failedBy } = evaluateRawDetailed(f, [
      con("ecc", "lte", 0.5, false),
      con("hfr", "lte", 3.0),
    ]);
    expect(failedBy).toBe("HFR 5.00 > 3.00");
  });
});

describe("emptyConstraintFor", () => {
  it("starts every chip valueless and enabled, with polarity-correct op", () => {
    for (const m of METRIC_KEYS) {
      const c = emptyConstraintFor(m);
      expect(c.value).toBeNull();
      expect(c.enabled).toBe(true);
      expect(c.op).toBe(m === "stars" ? "gte" : "lte");
    }
  });
});

describe("valueless constraints (value null)", () => {
  const empty: RawConstraint = { metric: "ecc", op: "lte", value: null, enabled: true };

  it("gates nothing: a freshly added chip must not exclude frames", () => {
    expect(evaluateRaw(frame({ eccentricity: 0.99 }), [empty])).toBe("pass");
  });

  it("does not count its metric toward 'present'", () => {
    // The frame carries ecc, but the only VALUED gate is on a missing metric,
    // so the frame is unmeasured -- the valueless gate must not smuggle it in.
    const f = frame({ eccentricity: 0.4 });
    expect(evaluateRaw(f, [empty, con("rms", "lte", 1.0)])).toBe("unmeasured");
  });

  it("passes every frame when the only constraints are valueless", () => {
    expect(evaluateRaw(blankFrame, [empty])).toBe("pass");
  });

  it("is never offered as a relaxation", () => {
    const frames = [frame({ source_relative: "a.fits", eccentricity: 0.9, median_hfr: 5.0 })];
    const cons: RawConstraint[] = [empty, con("hfr", "lte", 1.0)];
    const r = suggestRelaxation(verdictsFor(frames, cons), cons)!;
    expect(r.metric).toBe("hfr");
  });
});

describe("ECC_PRESETS", () => {
  it("ships the strict/balanced/relaxed ladder", () => {
    expect(ECC_PRESETS.map((p) => p.value)).toEqual([0.55, 0.65, 0.75]);
    expect(ECC_PRESETS.map((p) => p.label)).toEqual(["Strict", "Balanced", "Relaxed"]);
  });
});

describe("METRIC_DEFS", () => {
  it("maps the five metric keys to the contract's fields and polarity", () => {
    expect(METRIC_DEFS.hfr).toMatchObject({ field: "median_hfr", decimals: 2, betterWhen: "low" });
    expect(METRIC_DEFS.ecc).toMatchObject({ field: "eccentricity", decimals: 2, betterWhen: "low" });
    expect(METRIC_DEFS.fwhm).toMatchObject({ field: "fwhm", decimals: 2, betterWhen: "low" });
    expect(METRIC_DEFS.stars).toMatchObject({ field: "detected_stars", decimals: 0, betterWhen: "high" });
    expect(METRIC_DEFS.rms).toMatchObject({ field: "guiding_rms_arcsec", decimals: 2, betterWhen: "low" });
  });
});

describe("suggestRelaxation", () => {
  // The 10Micron case: a rig whose eccentricity genuinely floors around 0.55
  // meets a 0.5 constraint and loses every frame. The offer must come from its
  // own data, not from a table of conventions.
  it("offers the user's own best frame when an absolute constraint excludes everything", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.5519 }),
      frame({ source_relative: "b.fits", eccentricity: 0.58 }),
      frame({ source_relative: "c.fits", eccentricity: 0.61 }),
    ];
    const cons = [con("ecc", "lte", 0.5)];
    const r = suggestRelaxation(verdictsFor(frames, cons), cons)!;
    expect(r).not.toBeNull();
    expect(r.metric).toBe("ecc");
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
    const cons = [con("ecc", "lte", 0.5)];
    expect(suggestRelaxation(verdictsFor(frames, cons), cons)!.keeps).toBe(2);
  });

  // `keeps` is verified against the real evaluator, so a relaxation that another
  // still-firing gate would cancel out reports 0 and is never offered. The
  // offer names the gate that actually frees frames, not the first in the list.
  it("skips a relaxation another gate would cancel out", () => {
    const frames = [
      frame({ source_relative: "a.fits", eccentricity: 0.55, median_hfr: 2.0 }),
      frame({ source_relative: "b.fits", eccentricity: 0.9, median_hfr: 2.0 }),
    ];
    const cons = [
      con("hfr", "lte", 3.0), // both already pass this
      con("ecc", "lte", 0.5), // both fail this: the binding gate
    ];
    const r = suggestRelaxation(verdictsFor(frames, cons), cons)!;
    expect(r.metric).toBe("ecc");
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
    const cons = [con("hfr", "lte", 1.0), con("ecc", "lte", 0.5)];
    expect(suggestRelaxation(verdictsFor(frames, cons), cons)).toBeNull();
  });

  it("returns null when no frame carries the constrained metric", () => {
    const cons = [con("rms", "lte", 0.1)];
    expect(suggestRelaxation(verdictsFor([goodFrame], cons), cons)).toBeNull();
  });

  it("never offers to loosen a disabled constraint", () => {
    // The enabled ecc gate excludes everything; the disabled hfr gate would be
    // trivially loosenable but excludes nothing, so it must not be offered.
    const frames = [frame({ source_relative: "a.fits", eccentricity: 0.9, median_hfr: 2.0 })];
    const cons = [con("hfr", "lte", 1.0, false), con("ecc", "lte", 0.5)];
    const r = suggestRelaxation(verdictsFor(frames, cons), cons)!;
    expect(r.metric).toBe("ecc");
  });
});

describe("qualityTotals", () => {
  it("splits verdicts into copy/fail/unmeasured", () => {
    const verdicts = verdictsFor([goodFrame, badFrame, blankFrame], [con("ecc", "lte", 0.45)]);
    expect(qualityTotals(verdicts)).toEqual({ total: 3, copy: 1, fail: 1, unmeasured: 1 });
  });
});

describe("excludedSourceRelatives", () => {
  it("returns the source_relative of every non-kept frame", () => {
    const verdicts = verdictsFor([goodFrame, badFrame, blankFrame], [con("ecc", "lte", 0.45)]);
    const excluded = excludedSourceRelatives(verdicts);
    expect(excluded).toContain("bad.fits");
    expect(excluded).toContain("blank.fits");
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
    ({ frame: frame({ source_relative }), sessionDate, keep, reason: keep ? "pass" : "fail", failedBy: null, failures: [] });

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
