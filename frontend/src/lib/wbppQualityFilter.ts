// Client-side quality filter for WBPP export.
//
// Given the selected sessions' details (frames + baselines), decides which LIGHT
// frames to KEEP and which to EXCLUDE, then produces the list of fits-root-relative
// paths for the excluded frames. This is the single source of truth for the
// exclude set consumed by the browser copy and the backend generate/preview calls.
//
// The verdict path is raw metric constraints only: an AND over the ENABLED
// constraints, judged per frame on the metrics that frame actually carries.
// The old composite-score mode is gone; per-cell z coloring (cellZ) still mirrors
// SessionAccordionCard.tsx so a frame's preview coloring matches its row on the
// target detail page.

import type { SessionDetail, FrameRecord } from "../api/types";
import { madZ, type GroupBaseline } from "../utils/frameQuality";

export type MetricKey = "hfr" | "ecc" | "fwhm" | "stars" | "rms";
export type ConstraintOp = "lte" | "gte";
export type BaselineMode = "session" | "rig";

export interface RawConstraint {
  metric: MetricKey;
  op: ConstraintOp;
  /**
   * Absolute threshold. Null means the chip exists but has no number yet --
   * a valueless constraint gates NOTHING (it is not a gate, it is an empty
   * input waiting for one), so adding a chip never silently excludes frames.
   */
  value: number | null;
  enabled: boolean;
}

/**
 * Quick-fill presets for the eccentricity chip. Eccentricity is the one
 * constrained metric with rig-independent meaning (e = sqrt(1 - (b/a)^2)),
 * so fixed constants are defensible: 0.55 is an axis ratio of 0.84 (stars
 * read round), 0.65 is 0.76 (the edge of visible elongation), 0.75 is 0.66
 * (clearly elongated; salvage bar for poor nights). Every other metric
 * depends on the rig and the sky, so only ecc ships presets.
 */
export const ECC_PRESETS: { label: string; value: number }[] = [
  { label: "Strict", value: 0.55 },
  { label: "Balanced", value: 0.65 },
  { label: "Relaxed", value: 0.75 },
];

export interface QualityConfig {
  baseline: BaselineMode;
  constraints: RawConstraint[];
}

// The five constrained metrics: FrameRecord field, chip label, display decimals,
// and polarity. Only detected_stars is higher-is-better; everything else
// (HFR, FWHM, eccentricity, guiding RMS) is lower-is-better.
export const METRIC_DEFS: Record<
  MetricKey,
  { field: keyof FrameRecord; label: string; decimals: number; betterWhen: "low" | "high" }
> = {
  hfr: { field: "median_hfr", label: "HFR", decimals: 2, betterWhen: "low" },
  ecc: { field: "eccentricity", label: "Eccentricity", decimals: 2, betterWhen: "low" },
  fwhm: { field: "fwhm", label: "FWHM", decimals: 2, betterWhen: "low" },
  stars: { field: "detected_stars", label: "Detected stars", decimals: 0, betterWhen: "high" },
  rms: { field: "guiding_rms_arcsec", label: "Guiding RMS", decimals: 2, betterWhen: "low" },
};

export const METRIC_KEYS = Object.keys(METRIC_DEFS) as MetricKey[];

// Short names for the one-line failure reason on a verdict ("ecc 0.62 > 0.55").
// Deliberately terser than METRIC_DEFS labels: this string sits inside a table
// cell beside the badge, where "Eccentricity" would not fit.
const METRIC_SHORT: Record<MetricKey, string> = {
  hfr: "HFR",
  ecc: "ecc",
  fwhm: "FWHM",
  stars: "stars",
  rms: "RMS",
};

// Preview columns mirroring the session frame table's toggled metric columns.
// group/field feed isFieldVisible so the preview honors the user's display
// settings. Lives here rather than in the panel because the column set is the
// metric domain (the same five metrics as METRIC_DEFS), not a rendering choice.
export const METRIC_COLUMNS: {
  metric: MetricKey;
  label: string;
  group: "quality" | "guiding";
  field: string;
  format: (v: number) => string;
}[] = [
  { metric: "hfr", label: "HFR", group: "quality", field: "hfr", format: (v) => v.toFixed(2) },
  { metric: "ecc", label: "Ecc", group: "quality", field: "eccentricity", format: (v) => v.toFixed(2) },
  { metric: "fwhm", label: "FWHM", group: "quality", field: "fwhm", format: (v) => v.toFixed(2) },
  { metric: "stars", label: "Stars", group: "quality", field: "detected_stars", format: (v) => v.toFixed(0) },
  { metric: "rms", label: "RMS", group: "guiding", field: "rms_total", format: (v) => v.toFixed(2) },
];

/** Format a metric value with its METRIC_DEFS decimals. */
export function formatMetric(metric: MetricKey, value: number): string {
  return value.toFixed(METRIC_DEFS[metric].decimals);
}

/** The frame's value for a constrained metric, or null when unmeasured. */
export function metricValue(frame: FrameRecord, metric: MetricKey): number | null {
  const v = frame[METRIC_DEFS[metric].field];
  return typeof v === "number" ? v : null;
}

export type Verdict = "pass" | "fail" | "unmeasured";

export interface FrameVerdict {
  frame: FrameRecord;
  sessionDate: string;
  keep: boolean;
  reason: Verdict;
  /**
   * Which gate excluded this frame, and with what numbers -- "ecc 0.62 > 0.55".
   * Null when the frame passed or was unmeasured (there is no gate to name:
   * nothing was measured to compare).
   *
   * `reason` stays a bare pass/fail/unmeasured because the badge and the exclude
   * set are keyed off it. This is the human sentence beside the badge, and it is
   * the difference between a user learning their rig floors above the threshold
   * and a user staring at a red box.
   */
  failedBy: string | null;
}

// Train+filter group key matching the backend: "telescope|camera|filter".
// Mirrors SessionAccordionCard.tsx frameGroupKey.
export function frameGroupKey(
  frame: FrameRecord,
  telescope?: string | null,
  camera?: string | null,
): string {
  return `${telescope ?? ""}|${camera ?? ""}|${frame.filter_used ?? ""}`;
}

// Resolve the optical train (telescope/camera) for a frame. Multi-rig sessions
// carry it on the rig; single-rig falls back to the session equipment.
// Mirrors SessionAccordionCard.tsx equipmentForFrame.
export function equipmentForFrame(
  detail: SessionDetail,
  frame: FrameRecord,
): { telescope: string | null; camera: string | null } {
  if (frame.rig) {
    const rig = detail.rigs.find((r) => r.rig_label === frame.rig);
    if (rig) return { telescope: rig.telescope, camera: rig.camera };
  }
  return { telescope: detail.equipment.telescope, camera: detail.equipment.camera };
}

// Active baseline group for a frame. The selected mode picks session vs rig for
// the sharpness/roundness baselines; signal (detected_stars) is always session
// scoped (see cellZ). Mirrors SessionAccordionCard.tsx baselineFor.
export function baselineFor(
  detail: SessionDetail,
  frame: FrameRecord,
  telescope: string | null,
  camera: string | null,
  mode: BaselineMode,
): GroupBaseline | undefined {
  const key = frameGroupKey(frame, telescope, camera);
  return mode === "session" ? detail.session_baselines[key] : detail.rig_baselines[key];
}

// Signed robust z for ONE frame metric against the active baseline, mirroring
// SessionAccordionCard row coloring. Signal (detected_stars) is always
// session-scoped, the rest follow `baseline`. Guiding RMS has no baseline,
// hence null.
export function cellZ(
  detail: SessionDetail,
  frame: FrameRecord,
  metric: MetricKey,
  baseline: BaselineMode,
): number | null {
  const eq = equipmentForFrame(detail, frame);
  const active = baselineFor(detail, frame, eq.telescope, eq.camera, baseline);
  const sess = baselineFor(detail, frame, eq.telescope, eq.camera, "session");
  switch (metric) {
    case "hfr": return madZ(frame.median_hfr, active?.median_hfr);
    case "fwhm": return madZ(frame.fwhm, active?.fwhm);
    case "ecc": return madZ(frame.eccentricity, active?.eccentricity);
    case "stars": return madZ(frame.detected_stars, sess?.detected_stars, true);
    case "rms": return null;
  }
}

/** A constraint that can actually judge a frame: enabled AND holds a number. */
export function isActiveConstraint(c: RawConstraint): c is RawConstraint & { value: number } {
  return c.enabled && c.value != null;
}

export function constraintPasses(c: RawConstraint, value: number): boolean {
  if (c.value == null) return true;
  return c.op === "gte" ? value >= c.value : value <= c.value;
}

/** The failure sentence for a constraint a frame's `actual` violated. */
function rawFailureText(c: RawConstraint & { value: number }, actual: number): string {
  const op = c.op === "gte" ? "<" : ">";
  return `${METRIC_SHORT[c.metric]} ${formatMetric(c.metric, actual)} ${op} ${formatMetric(c.metric, c.value)}`;
}

/**
 * Multi-metric AND over the ENABLED constraints, with the partial-metric rule,
 * reporting WHICH constraint fired:
 *   - Disabled constraints do not exist for the verdict. Toggling a chip off
 *     must behave exactly like deleting the constraint, without losing its value.
 *   - Zero enabled constraints -> every frame passes. An empty filter is no
 *     filter, not a filter that quarantines the whole library as "unmeasured".
 *   - Judge a frame only on the enabled constraints it HAS data for.
 *   - A MISSING METRIC IS SKIPPED, NOT an auto-fail. This is deliberate, not an
 *     oversight: a constraint the user added for their guided nights must not
 *     silently delete every unguided frame, and coverage of the metrics is
 *     uneven across a library (a frame from before FWHM was recorded is not a
 *     bad frame). A frame with none of the enabled constrained metrics lands in
 *     "unmeasured", which the panel counts and labels separately, so the skip is
 *     visible rather than a quiet pass.
 *   - Of the metrics present, ALL must pass (AND) -> "pass"; any fails -> "fail".
 *   - A VALUELESS constraint (value null) is treated like a disabled one: an
 *     empty input is not a gate, so a freshly added chip excludes nothing
 *     until the user types a number or picks a preset.
 *
 * `failedBy` names the FIRST enabled constraint that failed, in the user's own
 * order.
 */
export function evaluateRawDetailed(
  frame: FrameRecord,
  constraints: RawConstraint[],
): { verdict: Verdict; failedBy: string | null } {
  const enabled = constraints.filter(isActiveConstraint);
  if (enabled.length === 0) return { verdict: "pass", failedBy: null };
  let present = 0;
  for (const c of enabled) {
    const v = metricValue(frame, c.metric);
    if (v == null) continue;
    present += 1;
    if (!constraintPasses(c, v)) return { verdict: "fail", failedBy: rawFailureText(c, v) };
  }
  return { verdict: present === 0 ? "unmeasured" : "pass", failedBy: null };
}

export function evaluateRaw(frame: FrameRecord, constraints: RawConstraint[]): Verdict {
  return evaluateRawDetailed(frame, constraints).verdict;
}

// Verdict for every LIGHT frame across the selected dates: evaluateRawDetailed
// (partial-metric AND over the enabled constraints).
export function computeVerdicts(
  sessionDetails: Record<string, SessionDetail>,
  dates: string[],
  config: QualityConfig,
): FrameVerdict[] {
  const out: FrameVerdict[] = [];
  for (const date of dates) {
    const detail = sessionDetails[date];
    if (!detail) continue;
    for (const frame of detail.frames) {
      const { verdict, failedBy } = evaluateRawDetailed(frame, config.constraints);
      out.push({ frame, sessionDate: date, keep: verdict === "pass", reason: verdict, failedBy });
    }
  }
  return out;
}

/**
 * Starting constraint for a newly enabled metric: no value. The chip appears
 * with an empty input (and, for ecc, the presets) and gates nothing until the
 * user supplies a number. Deliberately NOT derived from the selection's own
 * statistics: a threshold seeded from the data under judgment always passes
 * most of that data, which reads as authority it does not have. The op follows
 * the metric's polarity (only detected_stars is higher-is-better).
 */
export function emptyConstraintFor(metric: MetricKey): RawConstraint {
  const op: ConstraintOp = METRIC_DEFS[metric].betterWhen === "high" ? "gte" : "lte";
  return { metric, op, value: null, enabled: true };
}

// Fits-root-relative paths of every excluded (not-kept) frame. Same domain as
// WbppCopyOperation.source_relative; consumed by the browser copy and the
// backend excluded_source_relatives field.
export function excludedSourceRelatives(verdicts: FrameVerdict[]): string[] {
  return verdicts.filter((v) => !v.keep).map((v) => v.frame.source_relative);
}

/**
 * Is `sourceRelative` inside the folder level at `relativePath`?
 *
 * Matches at COMPONENT boundaries, never as a bare substring -- the same test the
 * backend makes (services/wbpp_export.py: `fp.startswith(anc + "/") or fp == anc`
 * in compute_session_levels, and `norm == prefix or norm.startswith(prefix + "/")`
 * in map_excluded_to_ops, which has a test asserting the distinction), and the same
 * one wbppBrowserCopy makes implicitly by walking the subtree from the level down.
 * A substring test would claim "M31/2026-07-01/Ha_old/x.fits" for the "Ha" level.
 *
 * An empty `relativePath` is the fits root itself, which contains everything.
 */
export function isUnderRelativePath(sourceRelative: string, relativePath: string): boolean {
  const prefix = relativePath.replace(/^\/+/, "").replace(/\/+$/, "");
  const path = sourceRelative.replace(/^\/+/, "");
  if (!prefix) return true;
  return path === prefix || path.startsWith(`${prefix}/`);
}

/**
 * The excluded frames a copy of the SELECTED levels would actually skip.
 *
 * `verdicts` covers every light in every selected session, but a session's chosen
 * folder level may be narrower than the session (e.g. .../Ha when the session also
 * has .../OIII). Frames outside the chosen subtree are never copied in the first
 * place, so excluding them subtracts nothing. Counting them makes the footer's
 * count and byte total describe two different sets of frames.
 *
 * `relativePathByDate` maps a session date to its selected level's relative_path.
 * A date with no selection contributes nothing. Each verdict is tested only against
 * its OWN session's level, so no frame is counted twice.
 */
export function excludedUnderSelectedLevels(
  verdicts: FrameVerdict[],
  relativePathByDate: Map<string, string>,
): FrameVerdict[] {
  return verdicts.filter((v) => {
    if (v.keep) return false;
    const relativePath = relativePathByDate.get(v.sessionDate);
    if (relativePath === undefined) return false;
    return isUnderRelativePath(v.frame.source_relative, relativePath);
  });
}

export interface QualityTotals {
  total: number;
  copy: number;
  fail: number;
  unmeasured: number;
}

/**
 * A loosening of ONE gate that would let at least one frame through, derived
 * entirely from the user's own frames.
 *
 * `keeps` is counted by re-running the real evaluation with the relaxed value,
 * not estimated, so the offer cannot promise frames it will not deliver.
 */
export interface Relaxation {
  metric: MetricKey;
  value: number;
  label: string;
  keeps: number;
}

/**
 * Rounded in the direction that keeps the best frame passing: out for
 * lower-is-better (0.5519 -> 0.56 at two decimals), down for higher-is-better.
 *
 * The toFixed pass is not decoration. `0.55 * 100` is 55.00000000000001 in
 * binary floating point, so a bare Math.ceil turns an exactly-achievable 0.55
 * into 0.56 -- an offer one hundredth looser than the user's data warrants,
 * from a rounding artifact rather than from anything measured.
 */
function roundOutward(value: number, decimals: number, floorward: boolean): number {
  const scale = Math.pow(10, decimals);
  const scaled = Number((value * scale).toFixed(6));
  return (floorward ? Math.floor(scaled) : Math.ceil(scaled)) / scale;
}

/**
 * What to loosen when a filter excludes every frame.
 *
 * The value is the user's OWN best frame, not a recommended constant: a rig
 * whose eccentricity floors at 0.55 is offered 0.56, because that is what its
 * data says is achievable. Nothing here encodes an opinion about what a good
 * frame is; it only reports what this dataset could pass.
 *
 * Only ONE gate is ever loosened. That is the shape of the problem this exists
 * for -- a single absolute constraint sitting under a rig's achievable floor --
 * and it keeps the offer something the user can read in one line. When two gates
 * each exclude every frame, no single change frees anything and this returns
 * null; the caller says so instead of offering a button that moves zero to zero.
 *
 * Only ENABLED constraints are candidates: a disabled gate excludes nothing, so
 * loosening it frees nothing. Null also when no constrained metric has a value
 * anywhere (nothing was measured, so no threshold lets anything in).
 */
export function suggestRelaxation(
  verdicts: FrameVerdict[],
  constraints: RawConstraint[],
): Relaxation | null {
  let best: Relaxation | null = null;
  for (const c of constraints) {
    // Valueless constraints exclude nothing, so loosening them frees nothing.
    if (!isActiveConstraint(c)) continue;
    const values = verdicts
      .map((v) => metricValue(v.frame, c.metric))
      .filter((n): n is number => n != null);
    if (!values.length) continue;
    const floorward = c.op === "gte";
    const decimals = METRIC_DEFS[c.metric].decimals;
    const relaxed = roundOutward(
      floorward ? Math.max(...values) : Math.min(...values),
      decimals,
      floorward,
    );
    if (relaxed === c.value) continue;
    const next = constraints.map((o) => (o.metric === c.metric ? { ...o, value: relaxed } : o));
    const keeps = verdicts.filter((v) => evaluateRaw(v.frame, next) === "pass").length;
    if (keeps === 0) continue;
    if (!best || keeps > best.keeps) {
      best = {
        metric: c.metric,
        value: relaxed,
        label: `${METRIC_DEFS[c.metric].label} ${floorward ? "≥" : "≤"} ${formatMetric(c.metric, relaxed)}`,
        keeps,
      };
    }
  }
  return best;
}

export function qualityTotals(verdicts: FrameVerdict[]): QualityTotals {
  let copy = 0;
  let fail = 0;
  let unmeasured = 0;
  for (const v of verdicts) {
    if (v.reason === "pass") copy += 1;
    else if (v.reason === "fail") fail += 1;
    else unmeasured += 1;
  }
  return { total: verdicts.length, copy, fail, unmeasured };
}
