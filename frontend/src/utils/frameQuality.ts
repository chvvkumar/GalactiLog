// Shared frame-quality deviation utility.
//
// Grades a single frame metric against a learned MAD-based baseline and turns it
// into a signed robust z-score, a color band, and a combined 0-100 quality score.
// The group-key format ("telescope|camera|filter") matches the backend exactly so
// frontend and backend index the same baseline maps.

export type QualityBand = "better" | "neutral" | "watch" | "reject";

export interface MetricBaseline {
  median: number | null;
  mad: number | null;
  n: number;
}

export type GroupBaseline = Record<string, MetricBaseline>;
export type Baselines = Record<string, GroupBaseline>;

export const MIN_GROUP = 8;
const EPS = 1e-9;

export function groupKey(f: {
  telescope?: string | null;
  camera?: string | null;
  filter_used?: string | null;
}): string {
  return `${f.telescope ?? ""}|${f.camera ?? ""}|${f.filter_used ?? ""}`;
}

// MAD-based robust z-score. higherIsBetter flips the sign so that "worse than
// baseline" is always positive regardless of metric polarity.
// Returns null (treated as neutral) when the baseline is too sparse, uniform
// (mad === 0), or the value/baseline is missing.
export function madZ(
  value: number | null | undefined,
  b: MetricBaseline | undefined,
  higherIsBetter = false,
): number | null {
  if (value == null || !b || b.median == null || b.mad == null || b.n < MIN_GROUP || b.mad === 0) return null;
  const z = (value - b.median) / Math.max(b.mad, EPS);
  return higherIsBetter ? -z : z;
}

export function bandForZ(z: number | null): QualityBand {
  if (z == null) return "neutral";
  if (z <= -1.0) return "better";
  if (z < 1.5) return "neutral";
  if (z < 3.0) return "watch";
  return "reject";
}

// Combined 0-100 score from up to three axes (signal/sharpness/roundness).
// Weights 0.5 / 0.25 / 0.25; when an axis is null it is dropped and the
// remaining weights are renormalized to sum to 1. All-null -> null (neutral row).
export function combinedScore(
  zSignal: number | null,
  zSharp: number | null,
  zRound: number | null,
): number | null {
  const axes = [
    [zSignal, 0.5],
    [zSharp, 0.25],
    [zRound, 0.25],
  ].filter(([z]) => z != null) as [number, number][];
  if (axes.length === 0) return null;
  const wsum = axes.reduce((s, [, w]) => s + w, 0);
  const zc = axes.reduce((s, [z, w]) => s + z * w, 0) / wsum;
  const clamped = Math.max(-3, Math.min(3, zc));
  return 50 - 16.7 * clamped;
}

export function bandToCellClass(band: QualityBand): string {
  switch (band) {
    case "better": return "text-theme-success";
    case "watch":  return "text-theme-warning";
    case "reject": return "text-theme-error";
    default:       return "text-theme-text-primary";
  }
}

export function scoreToRowClass(score: number | null): string {
  if (score == null) return "";
  if (score >= 60) return "bg-theme-success/10";
  if (score >= 45) return "";
  if (score >= 30) return "bg-theme-warning/15";
  return "bg-theme-error/20";
}

// Worked examples (sanity checks for the math above):
//
// 1. Higher-is-worse metric (HFR): value 2.8, baseline median 2.1, mad 0.37.
//    z = (2.8 - 2.1) / 0.37 = 0.7 / 0.37 ≈ 1.89  ->  bandForZ -> "watch".
//
// 2. Higher-is-better metric (detected_stars): value 80, baseline median 100,
//    mad 10, higherIsBetter = true.
//    raw z = (80 - 100) / 10 = -2; sign-flipped -> +2  ->  bandForZ -> "watch".
//    (Fewer stars than baseline is worse, so the flipped z is positive.)
