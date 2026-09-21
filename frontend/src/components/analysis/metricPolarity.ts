// Metric polarity shared by the analysis tabs. Metrics in neither set are
// lower-is-better (HFR, FWHM, eccentricity, guiding RMS).
export const HIGHER_IS_BETTER = new Set(["detected_stars", "sky_quality"]);

// Neither direction is better or worse: ADU level and spread depend on
// exposure, gain, filter and sky background, so verdicts use neutral wording.
export const NO_POLARITY = new Set(["adu_mean", "adu_median", "adu_stdev"]);
