// Client-side quality filter for WBPP export.
//
// Given the selected sessions' details (frames + baselines), decides which LIGHT
// frames to KEEP and which to EXCLUDE, then produces the list of fits-root-relative
// paths for the excluded frames. This is the single source of truth for the
// exclude set consumed by the browser copy and the backend generate/preview calls.
//
// The composite-score path mirrors SessionAccordionCard.tsx's frame scoring exactly
// (frameScore/equipmentForFrame/baselineFor, utils/frameQuality.ts madZ +
// combinedScore) so a frame's verdict in "score" mode matches its row coloring on
// the target detail page.

import type { SessionDetail, FrameRecord } from "../api/types";
import { madZ, combinedScore, type GroupBaseline } from "../utils/frameQuality";

export type FilterMode = "score" | "raw";
export type BaselineMode = "session" | "rig";

// The six graded metrics a raw constraint can target. Field names match
// FrameRecord exactly so a constraint indexes the frame directly.
export const RAW_METRICS = [
  "median_hfr",
  "fwhm",
  "eccentricity",
  "detected_stars",
  "guiding_rms_arcsec",
  "adu_median",
] as const;

export type RawMetric = (typeof RAW_METRICS)[number];

// Direction is automatic per metric: only detected_stars is higher-is-better.
// All others (HFR, FWHM, eccentricity, guiding RMS, ADU median) are lower-is-better.
export const HIGHER_IS_BETTER: Record<RawMetric, boolean> = {
  median_hfr: false,
  fwhm: false,
  eccentricity: false,
  detected_stars: true,
  guiding_rms_arcsec: false,
  adu_median: false,
};

export const RAW_METRIC_LABELS: Record<RawMetric, string> = {
  median_hfr: "HFR",
  fwhm: "FWHM",
  eccentricity: "Eccentricity",
  detected_stars: "Detected stars",
  guiding_rms_arcsec: "Guiding RMS",
  adu_median: "ADU median",
};

// Preview columns mirroring the session frame table's toggled metric columns.
// group/field feed isFieldVisible so the preview honors the user's display
// settings. Lives here rather than in the panel because the column set is the
// metric domain (same six metrics as RAW_METRICS), not a rendering choice.
export const METRIC_COLUMNS: {
  metric: RawMetric;
  label: string;
  group: "quality" | "guiding" | "adu";
  field: string;
  format: (v: number) => string;
}[] = [
  { metric: "median_hfr", label: "HFR", group: "quality", field: "hfr", format: (v) => v.toFixed(2) },
  { metric: "eccentricity", label: "Ecc", group: "quality", field: "eccentricity", format: (v) => v.toFixed(2) },
  { metric: "fwhm", label: "FWHM", group: "quality", field: "fwhm", format: (v) => v.toFixed(2) },
  { metric: "detected_stars", label: "Stars", group: "quality", field: "detected_stars", format: (v) => v.toFixed(0) },
  { metric: "guiding_rms_arcsec", label: "RMS", group: "guiding", field: "rms_total", format: (v) => v.toFixed(2) },
  { metric: "adu_median", label: "ADU", group: "adu", field: "median", format: (v) => v.toFixed(0) },
];

export interface RawConstraint {
  metric: RawMetric;
  value: number;
}

// Short names for the one-line failure reason on a verdict ("ecc 0.62 > 0.55").
// Deliberately terser than RAW_METRIC_LABELS: this string sits inside a table
// cell beside the badge, where "Eccentricity" would not fit.
export const RAW_METRIC_SHORT: Record<RawMetric, string> = {
  median_hfr: "HFR",
  fwhm: "FWHM",
  eccentricity: "ecc",
  detected_stars: "stars",
  guiding_rms_arcsec: "RMS",
  adu_median: "ADU",
};

const METRIC_FORMAT: Record<RawMetric, (v: number) => string> = Object.fromEntries(
  METRIC_COLUMNS.map((c) => [c.metric, c.format]),
) as Record<RawMetric, (v: number) => string>;

/** Format a metric value the way the preview table's column formats it. */
export function formatMetric(metric: RawMetric, value: number): string {
  return METRIC_FORMAT[metric](value);
}

/**
 * Starting value for a newly added raw constraint.
 *
 * Only eccentricity gets one, and that is a deliberate limit rather than an
 * unfinished table. Eccentricity is dimensionless and bounded 0..1, so a number
 * typed here means the same thing on every rig. HFR, FWHM, guiding RMS and ADU
 * median are not: they scale with pixel scale, focal length, seeing and exposure,
 * so any constant shipped for them would be a number invented to look helpful.
 * Those metrics start at 0 and the user supplies the value their own data implies.
 */
export const RAW_METRIC_DEFAULTS: Partial<Record<RawMetric, number>> = {
  eccentricity: 0.6,
};

export function defaultConstraintValue(metric: RawMetric): number {
  return RAW_METRIC_DEFAULTS[metric] ?? 0;
}

export type Verdict = "pass" | "fail" | "unmeasured";

export interface FrameVerdict {
  frame: FrameRecord;
  sessionDate: string;
  score: number | null;
  keep: boolean;
  reason: Verdict;
  /**
   * Which gate excluded this frame, and with what numbers -- "ecc 0.62 > 0.55",
   * "score 41 < 60". Null when the frame passed or was unmeasured (there is no
   * gate to name: nothing was measured to compare).
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
// scoped (see scoreFrame). Mirrors SessionAccordionCard.tsx baselineFor.
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

// Per-frame combined 0-100 score from signal (stars, higher-is-better),
// sharpness (HFR) and roundness (eccentricity) against the active baseline.
// Signal is always session-scoped; sharpness/roundness follow `mode`.
// Mirrors SessionAccordionCard.tsx frameScore exactly.
export function scoreFrame(
  detail: SessionDetail,
  frame: FrameRecord,
  mode: BaselineMode,
): number | null {
  const eq = equipmentForFrame(detail, frame);
  const b = baselineFor(detail, frame, eq.telescope, eq.camera, mode);
  const sb = baselineFor(detail, frame, eq.telescope, eq.camera, "session");
  const zSignal = madZ(frame.detected_stars, sb?.detected_stars, true);
  const zSharp = madZ(frame.median_hfr, b?.median_hfr);
  const zRound = madZ(frame.eccentricity, b?.eccentricity);
  return combinedScore(zSignal, zSharp, zRound);
}

// Signed robust z for ONE frame metric against the active baseline, mirroring
// SessionAccordionCard row coloring. Same baseline lookup as scoreFrame, which is
// why it lives beside it: signal (detected_stars) is always session-scoped, the
// rest follow `baseline`. Guiding RMS has no baseline, hence null.
export function cellZ(
  detail: SessionDetail,
  frame: FrameRecord,
  metric: RawMetric,
  baseline: BaselineMode,
): number | null {
  const eq = equipmentForFrame(detail, frame);
  const active = baselineFor(detail, frame, eq.telescope, eq.camera, baseline);
  const sess = baselineFor(detail, frame, eq.telescope, eq.camera, "session");
  switch (metric) {
    case "median_hfr": return madZ(frame.median_hfr, active?.median_hfr);
    case "fwhm": return madZ(frame.fwhm, active?.fwhm);
    case "eccentricity": return madZ(frame.eccentricity, active?.eccentricity);
    case "detected_stars": return madZ(frame.detected_stars, sess?.detected_stars, true);
    case "guiding_rms_arcsec": return null;
    case "adu_median": return madZ(frame.adu_median, sess?.adu_median);
  }
}

export function constraintPasses(c: RawConstraint, value: number): boolean {
  return HIGHER_IS_BETTER[c.metric] ? value >= c.value : value <= c.value;
}

/** The failure sentence for a constraint a frame's `actual` violated. */
function rawFailureText(c: RawConstraint, actual: number): string {
  const op = HIGHER_IS_BETTER[c.metric] ? "<" : ">";
  return `${RAW_METRIC_SHORT[c.metric]} ${formatMetric(c.metric, actual)} ${op} ${formatMetric(c.metric, c.value)}`;
}

/**
 * Raw multi-metric AND with the partial-metric rule (spec #5), reporting WHICH
 * constraint fired:
 *   - Judge a frame only on the active constraints it HAS data for.
 *   - A MISSING METRIC IS SKIPPED, NOT an auto-fail. This is deliberate, not an
 *     oversight: a constraint the user added for their guided nights must not
 *     silently delete every unguided frame, and coverage of the metrics is
 *     uneven across a library (a frame from before FWHM was recorded is not a
 *     bad frame). A frame with none of the constrained metrics lands in
 *     "unmeasured", which the panel counts and labels separately, so the skip is
 *     visible rather than a quiet pass.
 *   - Of the metrics present, ALL must pass (AND) -> "pass"; any fails -> "fail".
 *   - Zero present active metrics (or zero constraints) -> "unmeasured".
 *
 * `failedBy` names the FIRST constraint that failed, in the user's own order.
 */
export function evaluateRawDetailed(
  frame: FrameRecord,
  constraints: RawConstraint[],
): { verdict: Verdict; failedBy: string | null } {
  let present = 0;
  for (const c of constraints) {
    const v = frame[c.metric];
    if (v == null) continue;
    present += 1;
    if (!constraintPasses(c, v)) return { verdict: "fail", failedBy: rawFailureText(c, v) };
  }
  return { verdict: present === 0 ? "unmeasured" : "pass", failedBy: null };
}

export function evaluateRaw(frame: FrameRecord, constraints: RawConstraint[]): Verdict {
  return evaluateRawDetailed(frame, constraints).verdict;
}

// Verdict for every LIGHT frame across the selected dates.
//   - score mode: null combinedScore -> "unmeasured"; >= threshold -> "pass"; else "fail".
//   - raw mode: evaluateRaw (partial-metric AND).
// The score is always computed for preview coloring even in raw mode.
export function computeVerdicts(
  sessionDetails: Record<string, SessionDetail>,
  dates: string[],
  mode: FilterMode,
  baselineMode: BaselineMode,
  scoreThreshold: number,
  constraints: RawConstraint[],
): FrameVerdict[] {
  const out: FrameVerdict[] = [];
  for (const date of dates) {
    const detail = sessionDetails[date];
    if (!detail) continue;
    for (const frame of detail.frames) {
      const score = scoreFrame(detail, frame, baselineMode);
      let reason: Verdict;
      let failedBy: string | null = null;
      if (mode === "score") {
        if (score == null) reason = "unmeasured";
        else if (score >= scoreThreshold) reason = "pass";
        else {
          reason = "fail";
          failedBy = `score ${score.toFixed(0)} < ${scoreThreshold}`;
        }
      } else {
        const d = evaluateRawDetailed(frame, constraints);
        reason = d.verdict;
        failedBy = d.failedBy;
      }
      out.push({ frame, sessionDate: date, score, keep: reason === "pass", reason, failedBy });
    }
  }
  return out;
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
 * `metric` is null in score mode, where the gate is the threshold itself.
 * `keeps` is counted by re-running the real evaluation with the relaxed value,
 * not estimated, so the offer cannot promise frames it will not deliver.
 */
export interface Relaxation {
  metric: RawMetric | null;
  value: number;
  label: string;
  keeps: number;
}

/**
 * Two decimals, rounded in the direction that keeps the best frame passing: out
 * for lower-is-better (0.5519 -> 0.56), down for higher-is-better.
 *
 * The toFixed pass is not decoration. `0.55 * 100` is 55.00000000000001 in
 * binary floating point, so a bare Math.ceil turns an exactly-achievable 0.55
 * into 0.56 -- an offer one hundredth looser than the user's data warrants,
 * from a rounding artifact rather than from anything measured.
 */
function roundOutward(value: number, higherIsBetter: boolean): number {
  const scaled = Number((value * 100).toFixed(6));
  return (higherIsBetter ? Math.floor(scaled) : Math.ceil(scaled)) / 100;
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
 * Null also when every frame is unmeasured (nothing was measured, so no
 * threshold lets anything in) or no constrained metric has a value anywhere.
 */
export function suggestRelaxation(
  verdicts: FrameVerdict[],
  mode: FilterMode,
  scoreThreshold: number,
  constraints: RawConstraint[],
): Relaxation | null {
  if (mode === "score") {
    const scores = verdicts.map((v) => v.score).filter((s): s is number => s != null);
    if (!scores.length) return null;
    const value = Math.floor(Math.max(...scores));
    if (value >= scoreThreshold) return null;
    return {
      metric: null,
      value,
      label: `score ≥ ${value}`,
      keeps: scores.filter((s) => s >= value).length,
    };
  }

  let best: Relaxation | null = null;
  for (const c of constraints) {
    const values = verdicts
      .map((v) => v.frame[c.metric])
      .filter((n): n is number => n != null);
    if (!values.length) continue;
    const higher = HIGHER_IS_BETTER[c.metric];
    const relaxed = roundOutward(higher ? Math.max(...values) : Math.min(...values), higher);
    if (relaxed === c.value) continue;
    const next = constraints.map((o) => (o.metric === c.metric ? { ...o, value: relaxed } : o));
    const keeps = verdicts.filter((v) => evaluateRaw(v.frame, next) === "pass").length;
    if (keeps === 0) continue;
    if (!best || keeps > best.keeps) {
      best = {
        metric: c.metric,
        value: relaxed,
        label: `${RAW_METRIC_LABELS[c.metric]} ${higher ? "≥" : "≤"} ${formatMetric(c.metric, relaxed)}`,
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
