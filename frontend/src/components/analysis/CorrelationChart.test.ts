import { describe, it, expect } from "vitest";
import { describeCorrelation } from "./CorrelationChart";
import type { CorrelationResponse } from "../../api/types";

const resp = (y_metric: string, slope: number, r: number | null = 0.8): CorrelationResponse => ({
  points: [1, 2, 3].map((x) => ({ x, y: x, date: "2026-01-01", target_id: null, outlier: false })),
  trend: {
    slope, intercept: 0, r_squared: 0.64, pearson_r: r, spearman_rho: r,
    confidence_upper: [], confidence_lower: [],
  },
  x_metric: "humidity", y_metric, granularity: "frame",
  x_stats: null, y_stats: null, target_names: {},
});

describe("describeCorrelation", () => {
  it("treats a rising lower-is-better metric as worse", () => {
    expect(describeCorrelation(resp("hfr", 1))).toContain("negative impact");
    expect(describeCorrelation(resp("hfr", -1))).toContain("improves");
  });

  it("flips polarity for higher-is-better metrics", () => {
    expect(describeCorrelation(resp("detected_stars", 1))).toContain("improves");
    expect(describeCorrelation(resp("detected_stars", -1))).toContain("negative impact");
  });

  it("uses neutral wording for ADU metrics", () => {
    const text = describeCorrelation(resp("adu_mean", 1));
    expect(text).toContain("increases");
    expect(text).not.toMatch(/improves|negative impact/);
  });

  it("renders null coefficients as n/a", () => {
    expect(describeCorrelation(resp("hfr", 1, null))).toContain("Pearson r=n/a");
  });
});
