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

export interface RawConstraint {
  metric: RawMetric;
  value: number;
}

export type Verdict = "pass" | "fail" | "unmeasured";

export interface FrameVerdict {
  frame: FrameRecord;
  sessionDate: string;
  score: number | null;
  keep: boolean;
  reason: Verdict;
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

// Raw multi-metric AND with the partial-metric rule (spec #5):
//   - Judge a frame only on the active constraints it HAS data for.
//   - A missing metric is skipped (not an auto-fail).
//   - Of the metrics present, ALL must pass (AND) -> "pass"; any fails -> "fail".
//   - Zero present active metrics (or zero constraints) -> "unmeasured".
export function evaluateRaw(frame: FrameRecord, constraints: RawConstraint[]): Verdict {
  let present = 0;
  for (const c of constraints) {
    const v = frame[c.metric];
    if (v == null) continue;
    present += 1;
    const passes = HIGHER_IS_BETTER[c.metric] ? v >= c.value : v <= c.value;
    if (!passes) return "fail";
  }
  return present === 0 ? "unmeasured" : "pass";
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
      if (mode === "score") {
        if (score == null) reason = "unmeasured";
        else reason = score >= scoreThreshold ? "pass" : "fail";
      } else {
        reason = evaluateRaw(frame, constraints);
      }
      out.push({ frame, sessionDate: date, score, keep: reason === "pass", reason });
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

export interface QualityTotals {
  total: number;
  copy: number;
  fail: number;
  unmeasured: number;
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
