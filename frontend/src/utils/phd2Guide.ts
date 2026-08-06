// Pure helpers behind the PHD2 guide graph. Typed structurally (not against
// api/types' Phd2Frame/Phd2Event) so they stay unit-testable with plain
// literals; the API shapes satisfy these interfaces with no cast.

export interface GuideFramePoint {
  t: number;
  ra: number | null;
  dec: number | null;
  dropped: boolean;
}

export interface GuideEventPoint {
  type: string;
  t: number;
}

export interface SettleWindow {
  start: number;
  end: number;
  failed: boolean;
}

/**
 * Min/max-preserving bucket downsample. A plain stride would erase exactly the
 * excursions the graph exists to show, so each bucket contributes the frame
 * with the largest |RA| error, the frame with the largest |Dec| error, and the
 * first dropped frame, plus the two endpoints so the time span never shrinks.
 * With three points per bucket the bucket count is maxPoints/3, so the result
 * is always within budget.
 */
export function downsampleGuideFrames<T extends GuideFramePoint>(
  frames: readonly T[],
  maxPoints = 2000,
): T[] {
  if (frames.length <= maxPoints) return [...frames];
  const bucketCount = Math.max(1, Math.floor(maxPoints / 3));
  const bucketSize = frames.length / bucketCount;
  const kept = new Set<number>();

  for (let b = 0; b < bucketCount; b++) {
    const start = Math.floor(b * bucketSize);
    const end = Math.min(frames.length, Math.floor((b + 1) * bucketSize));
    if (end <= start) continue;

    let raIdx = -1;
    let decIdx = -1;
    let dropIdx = -1;
    let raBest = -1;
    let decBest = -1;

    for (let i = start; i < end; i++) {
      const f = frames[i];
      if (f.dropped && dropIdx === -1) dropIdx = i;
      if (f.ra !== null && isFinite(f.ra)) {
        const v = Math.abs(f.ra);
        if (v > raBest) { raBest = v; raIdx = i; }
      }
      if (f.dec !== null && isFinite(f.dec)) {
        const v = Math.abs(f.dec);
        if (v > decBest) { decBest = v; decIdx = i; }
      }
    }

    if (raIdx >= 0) kept.add(raIdx);
    if (decIdx >= 0) kept.add(decIdx);
    if (dropIdx >= 0) kept.add(dropIdx);
    if (raIdx < 0 && decIdx < 0 && dropIdx < 0) kept.add(start);
  }

  kept.add(0);
  kept.add(frames.length - 1);
  return [...kept].sort((a, b) => a - b).map((i) => frames[i]);
}

/**
 * Pairs settle_start events with the settle_done/settle_failed that closes
 * them. A start with no completion (log truncated mid-settle) is closed at
 * endFallback; a completion with no start is dropped.
 */
export function settleWindows(
  events: readonly GuideEventPoint[],
  endFallback: number,
): SettleWindow[] {
  const ordered = [...events].sort((a, b) => a.t - b.t);
  const windows: SettleWindow[] = [];
  let open: number | null = null;

  for (const e of ordered) {
    if (e.type === "settle_start") {
      // Two starts in a row means the first never reported a result.
      if (open !== null) windows.push({ start: open, end: e.t, failed: false });
      open = e.t;
    } else if (e.type === "settle_done" || e.type === "settle_failed") {
      if (open === null) continue;
      windows.push({ start: open, end: e.t, failed: e.type === "settle_failed" });
      open = null;
    }
  }

  if (open !== null) windows.push({ start: open, end: endFallback, failed: false });
  return windows;
}

/** An inclusive time window over the guide series, in elapsed seconds. */
export interface GuideView {
  min: number;
  max: number;
}

/**
 * The range a view is confined to, plus how far outside it the view may be
 * zoomed. Without `maxSpan` the range is its own limit, which is what the time
 * axis wants: there is no session before the first frame or after the last, so
 * scrolling out into blank axis would show nothing. The arcsecond axis is the
 * opposite case and sets it, see `guideYRange`.
 */
export interface GuideBounds extends GuideView {
  maxSpan?: number;
}

/**
 * Narrowest window the graph will zoom to. A guide frame arrives every 1 to 5
 * seconds, so ten seconds is already only a handful of points; below that the
 * axis shows empty space rather than detail.
 */
export const MIN_GUIDE_VIEW_SPAN = 10;

/**
 * Narrowest vertical window, in arcseconds of total span.
 *
 * Guiding error is quoted to two decimals everywhere else in the app
 * (`formatArcsec`) and the graph's own y ticks print one decimal, so a total
 * span of 0.1 covers one whole tick step and five steps of the finest figure
 * the app ever shows. Below that the axis repeats the same label top and
 * bottom and the reading is beyond anything the data supports: a 1.5 arcsec
 * per pixel guide scale cannot resolve 0.02 arcsec of real motion.
 */
export const MIN_GUIDE_Y_SPAN = 0.1;

/**
 * Empty axis kept above and below the data at full zoom, as a fraction of the
 * bound. Without it the tallest peak of the night is drawn exactly on the top
 * edge of the plot, where it reads as a trace that ran off the graph rather
 * than as the night's worst excursion.
 */
export const GUIDE_Y_HEADROOM = 0.08;

/**
 * How far past its own width the arcsecond axis may be zoomed out, as a
 * multiple. Zooming out below the data's own scale is useful: it settles the
 * traces into a flat band and shows how the night compares with a calmer one.
 * The cap only stops a runaway scroll from flattening the traces onto the zero
 * line, where nothing can be read at all.
 */
export const GUIDE_Y_ZOOM_OUT = 10;

/**
 * The vertical extent of the graph at full zoom, which is also the view a
 * reset returns to. The y axis is zero-centred so an RA excursion up reads the
 * same as the same excursion down, which is why the range is built from a
 * single bound rather than from the data's own min and max.
 *
 * The bound is padded by GUIDE_Y_HEADROOM so peaks keep air above them, and
 * the range carries an outer cap so the axis can be zoomed out past the data.
 */
export function guideYRange(bound: number): GuideBounds {
  const edge = bound * (1 + GUIDE_Y_HEADROOM);
  return { min: -edge, max: edge, maxSpan: 2 * edge * GUIDE_Y_ZOOM_OUT };
}

/**
 * Forces a candidate window inside the data range without changing its width,
 * so panning past either end parks against the edge instead of scrolling into
 * empty axis. The width itself is clamped to [minSpan, widest allowed] first,
 * where the widest allowed is the range's own width unless it declares a
 * larger `maxSpan`.
 *
 * A window wider than the range has no edge to park against, so it is centred
 * on the range's own centre. On the zero-centred arcsecond axis that keeps the
 * zoomed-out view symmetric, which is the whole point of that axis; on a range
 * with no `maxSpan` the case is unreachable except at exactly full width,
 * where centring and parking give the same answer.
 */
export function clampGuideView(
  view: GuideView,
  full: GuideBounds,
  minSpan = MIN_GUIDE_VIEW_SPAN,
): GuideView {
  const fullSpan = full.max - full.min;
  if (!(fullSpan > 0)) return { min: full.min, max: full.max };
  const ceiling = Math.max(fullSpan, full.maxSpan ?? fullSpan);
  const floor = Math.min(minSpan, fullSpan);
  const span = Math.min(ceiling, Math.max(floor, view.max - view.min));
  if (span > fullSpan) {
    const centre = (full.min + full.max) / 2;
    return { min: centre - span / 2, max: centre + span / 2 };
  }
  let min = view.min;
  if (min < full.min) min = full.min;
  if (min + span > full.max) min = full.max - span;
  return { min, max: min + span };
}

/**
 * True when a window is the range's own full width, so a caller holding it as
 * an override can drop the override and let the default view take over again.
 *
 * The comparison is on width alone and carries a hair of tolerance, because
 * the width arrives from a chain of multiplications by the zoom step and
 * lands a few ulps off. Width is enough: a clamped window of full width can
 * only be sitting on the range exactly.
 *
 * A window wider than the range is deliberately not full: on the arcsecond
 * axis that is a real zoomed-out state and has to be kept, not collapsed back
 * to the data's own scale.
 */
export function isFullGuideView(view: GuideView, full: GuideBounds): boolean {
  const fullSpan = full.max - full.min;
  if (!(fullSpan > 0)) return true;
  const span = view.max - view.min;
  return Math.abs(span - fullSpan) <= fullSpan * 1e-9;
}

/**
 * Scales the window by `factor` about `cursor`, keeping whatever value sits
 * under the pointer under the pointer. factor < 1 zooms in.
 */
export function zoomGuideView(
  view: GuideView,
  full: GuideBounds,
  cursor: number,
  factor: number,
  minSpan = MIN_GUIDE_VIEW_SPAN,
): GuideView {
  const span = view.max - view.min;
  if (!(span > 0)) return clampGuideView(view, full, minSpan);
  const ratio = Math.min(1, Math.max(0, (cursor - view.min) / span));
  const next = span * factor;
  const min = cursor - ratio * next;
  return clampGuideView({ min, max: min + next }, full, minSpan);
}

/** Slides the window by `delta` seconds, clamped to the data range. */
export function panGuideView(
  view: GuideView,
  full: GuideBounds,
  delta: number,
  minSpan = MIN_GUIDE_VIEW_SPAN,
): GuideView {
  return clampGuideView({ min: view.min + delta, max: view.max + delta }, full, minSpan);
}

/**
 * Frames inside a time window, plus one frame either side so the plotted line
 * still reaches both edges instead of stopping short of them. Frames are
 * emitted in log order, so the bounds are found by binary search and a zoom
 * step costs log n rather than a scan of the whole session.
 */
export function sliceFramesByTime<T extends GuideFramePoint>(
  frames: readonly T[],
  min: number,
  max: number,
): T[] {
  if (frames.length === 0) return [];
  let lo = 0;
  let hi = frames.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t < min) lo = mid + 1;
    else hi = mid;
  }
  const start = Math.max(0, lo - 1);
  lo = 0;
  hi = frames.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t <= max) lo = mid + 1;
    else hi = mid;
  }
  const end = Math.min(frames.length, lo + 1);
  return end > start ? frames.slice(start, end) : [];
}

/** Half-height of a zero-centred arcsec axis: the largest excursion, rounded up to a tenth. */
export function symmetricYBound(frames: readonly GuideFramePoint[], minimum = 1): number {
  let max = 0;
  for (const f of frames) {
    if (f.ra !== null && isFinite(f.ra)) max = Math.max(max, Math.abs(f.ra));
    if (f.dec !== null && isFinite(f.dec)) max = Math.max(max, Math.abs(f.dec));
  }
  if (max === 0) return minimum;
  return Math.max(minimum, Math.ceil(max * 10) / 10);
}
