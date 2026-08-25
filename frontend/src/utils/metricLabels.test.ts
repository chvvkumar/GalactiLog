import { describe, it, expect } from "vitest";
import { METRIC_LABELS, METRIC_UNITS, PHD2_X_METRICS, metricLabel, metricOptions } from "./metricLabels";
import { ARCSEC } from "./format";

// Verification only. The Analysis tabs have carried the three guiding metrics
// since they were built for the NINA CSV source, and the PHD2 correlation
// pass fills the same Image columns, so those tabs light up with no new
// metric code. What is asserted here is that the shared label layer every tab
// builds its options from still knows all three, so a future edit cannot drop
// one without a red test.
describe("guiding metrics in the shared Analysis label layer", () => {
  it("labels the total, RA and Dec guiding metrics", () => {
    expect(METRIC_LABELS.guiding_rms).toBe(`Guiding RMS (${ARCSEC})`);
    expect(METRIC_LABELS.guiding_rms_ra).toBe(`Guiding RA RMS (${ARCSEC})`);
    expect(METRIC_LABELS.guiding_rms_dec).toBe(`Guiding DEC RMS (${ARCSEC})`);
  });

  it("gives all three the arcsecond unit suffix", () => {
    expect(METRIC_UNITS.guiding_rms).toBe(ARCSEC);
    expect(METRIC_UNITS.guiding_rms_ra).toBe(ARCSEC);
    expect(METRIC_UNITS.guiding_rms_dec).toBe(ARCSEC);
  });

  it("builds selector options for them through the shared helper", () => {
    const options = metricOptions(["guiding_rms", "guiding_rms_ra", "guiding_rms_dec"]);
    expect(options.map((o) => o.value)).toEqual([
      "guiding_rms",
      "guiding_rms_ra",
      "guiding_rms_dec",
    ]);
    expect(options[0].label).toBe(metricLabel("guiding_rms"));
  });
});

describe("PHD2 night-level metrics for the Correlation X axis", () => {
  it("labels and units all five keys", () => {
    expect(PHD2_X_METRICS).toEqual([
      "phd2_rms_total", "phd2_rms_ra", "phd2_rms_dec", "phd2_star_lost_pct", "phd2_snr_mean",
    ]);
    expect(METRIC_LABELS.phd2_rms_total).toBe(`PHD2 RMS Total (${ARCSEC})`);
    expect(METRIC_LABELS.phd2_rms_ra).toBe(`PHD2 RMS RA (${ARCSEC})`);
    expect(METRIC_LABELS.phd2_rms_dec).toBe(`PHD2 RMS Dec (${ARCSEC})`);
    expect(METRIC_LABELS.phd2_star_lost_pct).toBe("PHD2 Star Lost (%)");
    expect(METRIC_LABELS.phd2_snr_mean).toBe("PHD2 Guide SNR");
    expect(METRIC_UNITS.phd2_rms_total).toBe(ARCSEC);
    expect(METRIC_UNITS.phd2_rms_ra).toBe(ARCSEC);
    expect(METRIC_UNITS.phd2_rms_dec).toBe(ARCSEC);
    expect(METRIC_UNITS.phd2_star_lost_pct).toBe("%");
    expect(METRIC_UNITS.phd2_snr_mean).toBeUndefined();
  });

  it("builds selector options for all five through the shared helper", () => {
    const options = metricOptions(PHD2_X_METRICS);
    expect(options.map((o) => o.value)).toEqual(PHD2_X_METRICS);
    expect(options.every((o) => o.label !== o.value)).toBe(true);
  });
});
