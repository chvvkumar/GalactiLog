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
import { madZ, type GroupBaseline, type MetricBaseline, MIN_GROUP } from "../utils/frameQuality";

export type MetricKey = "hfr" | "ecc" | "fwhm" | "stars" | "rms";
export type ConstraintOp = "lte" | "gte";
export type BaselineMode = "session" | "rig";
export type ThresholdScope = "global" | "session";

// The k in `median +/- k * 1.4826 * MAD`: both the seeding default and the
// per-session multiplier start here. 1.4826 * MAD is the robust sigma estimate,
// so k reads as "sigmas of slack around the group's own typical frame".
export const DEFAULT_SESSION_K = 1.5;
const MAD_SIGMA = 1.4826;

/**
 * Provenance of an auto-seeded constraint: which train+filter group's baseline
 * supplied the pooled `value`, from which night (null when the rig catalog
 * baseline seeded it, which is not tied to a night), and which filters were too
 * small to self-seed and therefore inherited the pooled value.
 */
export interface ConstraintSeed {
  groupKey: string;
  filter: string;
  date: string | null;
  n: number;
  pooledFilters: string[];
}

export interface RawConstraint {
  metric: MetricKey;
  op: ConstraintOp;
  /** Pooled/global threshold; the fallback whenever nothing narrower applies. */
  value: number;
  enabled: boolean;
  /**
   * "global" (default): one absolute threshold (per filter group while
   * auto-seeded, see groupValues). "session": each night derives its own
   * threshold from its own frame distribution via `k`.
   */
  scope?: ThresholdScope;
  /** Per-session multiplier (scope "session"): median +/- k * 1.4826 * MAD. */
  k?: number;
  /**
   * Per-filter-group thresholds keyed by "telescope|camera|filter", present
   * while the constraint is auto-seeded. A frame is judged against its OWN
   * group's entry; a group without one falls back to `value`. Cleared when the
   * user types a value: a manual number is an absolute, cross-filter gate.
   */
  groupValues?: Record<string, number>;
  seed?: ConstraintSeed;
}

/** The filter component of a "telescope|camera|filter" group key, for labels. */
export function filterOfGroupKey(groupKey: string): string {
  return groupKey.split("|")[2] || "—";
}

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
  /** "telescope|camera|filter" group the frame was judged (and colored) under. */
  groupKey: string;
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

export function passesThreshold(op: ConstraintOp, threshold: number, value: number): boolean {
  return op === "gte" ? value >= threshold : value <= threshold;
}

export function constraintPasses(c: RawConstraint, value: number): boolean {
  return passesThreshold(c.op, c.value, value);
}

/**
 * Where a frame's verdict is being computed: its session detail and its
 * train+filter group key. Optional throughout -- without it, resolution falls
 * back to the pooled `value`, which is also the correct answer for callers that
 * genuinely have no group (e.g. relaxation math over a whole selection).
 */
export interface EvalContext {
  detail: SessionDetail;
  groupKey: string;
}

/**
 * A night's own threshold for a session-scoped constraint: that session's
 * per-group baseline, widened by the constraint's k. Null when the group's
 * baseline is missing or too small (n < MIN_GROUP) for a stable MAD -- the
 * caller falls back to the pooled per-filter value and flags it.
 */
export function derivedSessionThreshold(
  c: RawConstraint,
  detail: SessionDetail,
  groupKey: string,
): number | null {
  const b = detail.session_baselines[groupKey]?.[METRIC_DEFS[c.metric].field as string];
  if (!b) return null;
  return thresholdFromBaseline(c.metric, b, c.k ?? DEFAULT_SESSION_K);
}

/** median +/- k * 1.4826 * MAD, rounded to the metric's display decimals. */
function thresholdFromBaseline(metric: MetricKey, b: MetricBaseline, k: number): number | null {
  if (b.median == null || b.mad == null || b.n < MIN_GROUP) return null;
  const def = METRIC_DEFS[metric];
  const spread = k * MAD_SIGMA * b.mad;
  const raw = def.betterWhen === "high" ? b.median - spread : b.median + spread;
  return Math.max(0, Number(raw.toFixed(def.decimals)));
}

/**
 * The one threshold that judges a given frame, resolved through the whole
 * chain: session-derived (scope "session") -> per-filter-group seed ->
 * pooled `value`. `fallback` is true exactly when a session-scoped constraint
 * could NOT derive a threshold for this night+group (too few frames) and the
 * pooled per-filter number stepped in -- the UI marks those rows.
 */
export function effectiveThreshold(
  c: RawConstraint,
  ctx?: Partial<EvalContext>,
): { value: number; fallback: boolean } {
  const grouped = (ctx?.groupKey != null ? c.groupValues?.[ctx.groupKey] : undefined) ?? c.value;
  if ((c.scope ?? "global") === "session" && ctx?.detail && ctx.groupKey != null) {
    const t = derivedSessionThreshold(c, ctx.detail, ctx.groupKey);
    if (t != null) return { value: t, fallback: false };
    return { value: grouped, fallback: true };
  }
  return { value: grouped, fallback: false };
}

export type ThresholdBand = "ok" | "watch" | "reject";

// The "watch" margin under a threshold, as a fraction of the threshold itself.
// Threshold-relative by design: the WBPP grid colors a cell by its distance to
// the gate that would exclude it, so chip and grid speak one language (the raw
// 3.0-MAD bands of frameQuality.ts grade against a baseline the chip may not
// even be using).
export const THRESHOLD_WATCH_MARGIN = 0.08;

/**
 * Cell band relative to the ACTIVE threshold for this frame's context:
 * fails the gate -> "reject"; passes but within the margin of the threshold
 * -> "watch"; comfortably clear -> "ok". A frame sitting exactly at the
 * threshold passes the gate (<=/>=), so it colors "watch", never a red cell
 * beside a green Copy badge.
 */
export function bandForThreshold(
  c: RawConstraint,
  value: number,
  ctx?: Partial<EvalContext>,
): ThresholdBand {
  const t = effectiveThreshold(c, ctx).value;
  if (!passesThreshold(c.op, t, value)) return "reject";
  const margin = Math.abs(t) * THRESHOLD_WATCH_MARGIN;
  const nearGate = c.op === "gte" ? value <= t + margin : value >= t - margin;
  return nearGate ? "watch" : "ok";
}

export function thresholdBandToCellClass(band: ThresholdBand): string {
  switch (band) {
    case "reject": return "text-theme-error";
    case "watch":  return "text-theme-warning";
    default:       return "text-theme-text-primary";
  }
}

/** The failure sentence for a constraint a frame's `actual` violated. */
function rawFailureText(c: RawConstraint, actual: number, threshold: number): string {
  const op = c.op === "gte" ? "<" : ">";
  return `${METRIC_SHORT[c.metric]} ${formatMetric(c.metric, actual)} ${op} ${formatMetric(c.metric, threshold)}`;
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
 *
 * `failedBy` names the FIRST enabled constraint that failed, in the user's own
 * order.
 */
export function evaluateRawDetailed(
  frame: FrameRecord,
  constraints: RawConstraint[],
  ctx?: Partial<EvalContext>,
): { verdict: Verdict; failedBy: string | null } {
  const enabled = constraints.filter((c) => c.enabled);
  if (enabled.length === 0) return { verdict: "pass", failedBy: null };
  let present = 0;
  for (const c of enabled) {
    const v = metricValue(frame, c.metric);
    if (v == null) continue;
    present += 1;
    const t = effectiveThreshold(c, ctx).value;
    if (!passesThreshold(c.op, t, v)) {
      return { verdict: "fail", failedBy: rawFailureText(c, v, t) };
    }
  }
  return { verdict: present === 0 ? "unmeasured" : "pass", failedBy: null };
}

export function evaluateRaw(
  frame: FrameRecord,
  constraints: RawConstraint[],
  ctx?: Partial<EvalContext>,
): Verdict {
  return evaluateRawDetailed(frame, constraints, ctx).verdict;
}

// Verdict for every LIGHT frame across the selected dates: evaluateRawDetailed
// (partial-metric AND over the enabled constraints), each frame judged against
// its OWN train+filter group's threshold -- and, for session-scoped
// constraints, its own night's.
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
      const eq = equipmentForFrame(detail, frame);
      const groupKey = frameGroupKey(frame, eq.telescope, eq.camera);
      const { verdict, failedBy } = evaluateRawDetailed(frame, config.constraints, {
        detail,
        groupKey,
      });
      out.push({
        frame,
        sessionDate: date,
        groupKey,
        keep: verdict === "pass",
        reason: verdict,
        failedBy,
      });
    }
  }
  return out;
}

/**
 * Starting constraint for a newly enabled metric, derived from the SAME
 * baseline stats (median + MAD) the cell coloring uses, respecting
 * config.baseline (signal/detected_stars is always session-scoped, exactly as
 * cellZ colors it).
 *
 * Threshold = median + 1.5 * 1.4826 * MAD for lower-is-better metrics (op
 * "lte"), median - 1.5 * 1.4826 * MAD for detected_stars (op "gte", floored at
 * 0), rounded to the metric's display decimals. 1.4826 * MAD is the robust
 * sigma estimate, so the default admits everything within ~1.5 sigma of the
 * selection's own typical frame -- the user's data supplies the number, not a
 * shipped constant.
 *
 * Seeded PER TRAIN+FILTER GROUP ("telescope|camera|filter"), matching the
 * grading engine's grouping: each group's threshold comes from its OWN
 * baseline (largest-n qualifying night for that group in session mode), stored
 * in `groupValues`, so an Ha-derived number never judges LRGB frames. The
 * pooled `value` -- the single largest-n group across the whole selection --
 * remains the fallback for groups too small to self-seed (n < MIN_GROUP);
 * those filters are listed in `seed.pooledFilters` so the UI can mark them.
 *
 * Guiding RMS has no baseline (as in cellZ), and a selection may have no
 * qualifying baseline at all; both start at 0 with no seeding metadata and the
 * user supplies the value their data implies. Always enabled: enabling is the
 * whole point of asking for a default.
 */
export function defaultConstraintFor(
  metric: MetricKey,
  sessionDetails: Record<string, SessionDetail>,
  dates: string[],
  config: QualityConfig,
): RawConstraint {
  const def = METRIC_DEFS[metric];
  const op: ConstraintOp = def.betterWhen === "high" ? "gte" : "lte";
  const mode: BaselineMode = metric === "stars" ? "session" : config.baseline;

  // Best qualifying baseline PER GROUP (most evidence for that group), plus
  // every group that appears in the selection at all -- the ones with no
  // qualifying baseline are the pooled-fallback set.
  const perGroup = new Map<string, { b: MetricBaseline; date: string }>();
  const groupsSeen = new Set<string>();
  const visited = new Set<string>();
  for (const date of dates) {
    const detail = sessionDetails[date];
    if (!detail) continue;
    for (const frame of detail.frames) {
      const eq = equipmentForFrame(detail, frame);
      const key = frameGroupKey(frame, eq.telescope, eq.camera);
      groupsSeen.add(key);
      const dateKey = `${date}::${key}`;
      if (visited.has(dateKey)) continue;
      visited.add(dateKey);
      const group = baselineFor(detail, frame, eq.telescope, eq.camera, mode);
      const b = group?.[def.field as string];
      if (!b || b.median == null || b.mad == null || b.n < MIN_GROUP) continue;
      const cur = perGroup.get(key);
      if (!cur || b.n > cur.b.n) perGroup.set(key, { b, date });
    }
  }

  // Pooled seed: the single largest-n qualifying group across the selection.
  let pooledKey: string | null = null;
  let pooled: { b: MetricBaseline; date: string } | null = null;
  for (const [key, cand] of perGroup) {
    if (!pooled || cand.b.n > pooled.b.n) {
      pooled = cand;
      pooledKey = key;
    }
  }
  if (!pooled || pooledKey == null) {
    return { metric, op, value: 0, enabled: true };
  }

  const value = thresholdFromBaseline(metric, pooled.b, DEFAULT_SESSION_K)!;
  const groupValues: Record<string, number> = {};
  const pooledFilters: string[] = [];
  for (const key of groupsSeen) {
    const cand = perGroup.get(key);
    const own = cand ? thresholdFromBaseline(metric, cand.b, DEFAULT_SESSION_K) : null;
    if (own != null) {
      groupValues[key] = own;
    } else {
      groupValues[key] = value;
      pooledFilters.push(filterOfGroupKey(key));
    }
  }
  const seed: ConstraintSeed = {
    groupKey: pooledKey,
    filter: filterOfGroupKey(pooledKey),
    // Rig-catalog baselines aggregate every night, so no single night seeded them.
    date: mode === "rig" ? null : pooled.date,
    n: pooled.b.n,
    pooledFilters: [...new Set(pooledFilters)].sort(),
  };
  return { metric, op, value, enabled: true, groupValues, seed };
}

/**
 * One row per (night, train+filter group) for the per-session threshold list:
 * the derived (or fallen-back) threshold, how many measured frames it keeps
 * and cuts, and whether the pooled fallback stepped in (n < MIN_GROUP).
 * Counts cover only frames that carry the metric -- unmeasured frames are the
 * verdict table's "Unmeasured" business, not this row's.
 */
export interface SessionThresholdRow {
  date: string;
  groupKey: string;
  filter: string;
  threshold: number;
  fallback: boolean;
  n: number;
  keep: number;
  cut: number;
}

export function sessionThresholdRows(
  c: RawConstraint,
  sessionDetails: Record<string, SessionDetail>,
  dates: string[],
): SessionThresholdRow[] {
  const rows: SessionThresholdRow[] = [];
  for (const date of dates) {
    const detail = sessionDetails[date];
    if (!detail) continue;
    const byGroup = new Map<string, number[]>();
    for (const frame of detail.frames) {
      const v = metricValue(frame, c.metric);
      if (v == null) continue;
      const eq = equipmentForFrame(detail, frame);
      const key = frameGroupKey(frame, eq.telescope, eq.camera);
      let vals = byGroup.get(key);
      if (!vals) {
        vals = [];
        byGroup.set(key, vals);
      }
      vals.push(v);
    }
    for (const [groupKey, vals] of byGroup) {
      const { value: threshold, fallback } = effectiveThreshold(c, { detail, groupKey });
      const keep = vals.filter((v) => passesThreshold(c.op, threshold, v)).length;
      rows.push({
        date,
        groupKey,
        filter: filterOfGroupKey(groupKey),
        threshold,
        fallback,
        n: vals.length,
        keep,
        cut: vals.length - keep,
      });
    }
  }
  rows.sort((a, b) =>
    a.date === b.date ? a.filter.localeCompare(b.filter) : a.date.localeCompare(b.date),
  );
  return rows;
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
    if (!c.enabled) continue;
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
    // The relaxed gate is a manual absolute: per-filter seeds and per-session
    // derivation are cleared, otherwise the narrower thresholds would keep
    // excluding frames the offer just promised to free.
    const next = constraints.map((o) =>
      o.metric === c.metric
        ? { ...o, value: relaxed, scope: "global" as const, groupValues: undefined, seed: undefined }
        : o,
    );
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
