import { describe, it, expect } from "vitest";
import {
  clampGuideView,
  downsampleGuideFrames,
  guideYRange,
  isFullGuideView,
  panGuideView,
  settleWindows,
  sliceFramesByTime,
  symmetricYBound,
  zoomGuideView,
  GUIDE_Y_HEADROOM,
  MIN_GUIDE_VIEW_SPAN,
  MIN_GUIDE_Y_SPAN,
  type GuideFramePoint,
} from "./phd2Guide";

const frame = (t: number, ra: number | null, dec: number | null, dropped = false): GuideFramePoint =>
  ({ t, ra, dec, dropped });

describe("downsampleGuideFrames", () => {
  it("returns the input untouched when it already fits", () => {
    const frames = [frame(0, 0.1, -0.2), frame(1, 0.3, 0.4)];
    expect(downsampleGuideFrames(frames, 2000)).toEqual(frames);
  });

  it("never exceeds the point budget", () => {
    const frames = Array.from({ length: 50_000 }, (_, i) =>
      frame(i, Math.sin(i / 10), Math.cos(i / 7))
    );
    expect(downsampleGuideFrames(frames, 2000).length).toBeLessThanOrEqual(2000);
  });

  it("keeps the extremes of each axis instead of a blind stride", () => {
    const frames = Array.from({ length: 300 }, (_, i) => frame(i, 0.1, 0.1));
    frames[137] = frame(137, 9.9, 0.1);   // RA spike on an index a stride would skip
    frames[138] = frame(138, 0.1, -8.8);  // Dec spike
    const kept = downsampleGuideFrames(frames, 30);
    expect(kept.some((f) => f.ra === 9.9)).toBe(true);
    expect(kept.some((f) => f.dec === -8.8)).toBe(true);
  });

  it("keeps a dropped frame from every bucket that has one, and the endpoints", () => {
    const frames = Array.from({ length: 300 }, (_, i) => frame(i, 0.1, 0.1));
    frames[200] = frame(200, null, null, true);
    const kept = downsampleGuideFrames(frames, 30);
    expect(kept.some((f) => f.dropped)).toBe(true);
    expect(kept[0].t).toBe(0);
    expect(kept[kept.length - 1].t).toBe(299);
  });

  it("returns frames in ascending time order with no duplicates", () => {
    const frames = Array.from({ length: 5000 }, (_, i) => frame(i, Math.sin(i), Math.cos(i)));
    const kept = downsampleGuideFrames(frames, 200);
    const times = kept.map((f) => f.t);
    expect([...times].sort((a, b) => a - b)).toEqual(times);
    expect(new Set(times).size).toBe(times.length);
  });
});

describe("settleWindows", () => {
  it("pairs each start with its completion and flags failures", () => {
    expect(
      settleWindows(
        [
          { type: "dither", t: 10 },
          { type: "settle_start", t: 11 },
          { type: "settle_done", t: 18 },
          { type: "settle_start", t: 60 },
          { type: "settle_failed", t: 75 },
        ],
        100
      )
    ).toEqual([
      { start: 11, end: 18, failed: false },
      { start: 60, end: 75, failed: true },
    ]);
  });

  it("closes a trailing unfinished settle at the fallback time", () => {
    expect(settleWindows([{ type: "settle_start", t: 90 }], 120)).toEqual([
      { start: 90, end: 120, failed: false },
    ]);
  });

  it("ignores a completion with no matching start", () => {
    expect(settleWindows([{ type: "settle_done", t: 5 }], 100)).toEqual([]);
  });

  it("sorts out-of-order events before pairing", () => {
    expect(
      settleWindows(
        [
          { type: "settle_done", t: 18 },
          { type: "settle_start", t: 11 },
        ],
        100
      )
    ).toEqual([{ start: 11, end: 18, failed: false }]);
  });
});

describe("symmetricYBound", () => {
  it("rounds the largest excursion up to a tenth", () => {
    expect(symmetricYBound([frame(0, 1.23, -0.4), frame(1, null, 2.71)])).toBe(2.8);
  });

  it("falls back to the minimum for a quiet or empty session", () => {
    expect(symmetricYBound([])).toBe(1);
    expect(symmetricYBound([frame(0, 0.2, -0.3)])).toBe(1);
  });
});

const FULL = { min: 0, max: 1000 };

describe("clampGuideView", () => {
  it("leaves a window that already fits alone", () => {
    expect(clampGuideView({ min: 200, max: 400 }, FULL)).toEqual({ min: 200, max: 400 });
  });

  it("parks a window that ran off the start against the start", () => {
    expect(clampGuideView({ min: -300, max: -100 }, FULL)).toEqual({ min: 0, max: 200 });
  });

  it("parks a window that ran off the end against the end", () => {
    expect(clampGuideView({ min: 950, max: 1150 }, FULL)).toEqual({ min: 800, max: 1000 });
  });

  it("never lets the window grow past the data", () => {
    expect(clampGuideView({ min: -500, max: 5000 }, FULL)).toEqual(FULL);
  });

  it("refuses to zoom below the minimum span", () => {
    const v = clampGuideView({ min: 500, max: 502 }, FULL);
    expect(v.max - v.min).toBe(MIN_GUIDE_VIEW_SPAN);
  });

  it("allows a session shorter than the minimum span to show whole", () => {
    expect(clampGuideView({ min: 0, max: 1 }, { min: 0, max: 4 })).toEqual({ min: 0, max: 4 });
  });
});

describe("zoomGuideView", () => {
  it("keeps the value under the cursor under the cursor", () => {
    const v = zoomGuideView({ min: 0, max: 1000 }, FULL, 250, 0.5);
    expect(v.max - v.min).toBe(500);
    // 250 sat a quarter of the way in and still does.
    expect((250 - v.min) / (v.max - v.min)).toBeCloseTo(0.25, 6);
  });

  it("zooming out never leaves the data range", () => {
    const v = zoomGuideView({ min: 400, max: 600 }, FULL, 500, 10);
    expect(v).toEqual(FULL);
  });

  it("stops at the minimum span however hard it is zoomed", () => {
    let v = { min: 0, max: 1000 };
    for (let i = 0; i < 40; i++) v = zoomGuideView(v, FULL, 500, 0.5);
    expect(v.max - v.min).toBe(MIN_GUIDE_VIEW_SPAN);
  });
});

describe("panGuideView", () => {
  it("slides the window without changing its width", () => {
    expect(panGuideView({ min: 100, max: 300 }, FULL, 50)).toEqual({ min: 150, max: 350 });
  });

  it("stops at the start of the session", () => {
    expect(panGuideView({ min: 100, max: 300 }, FULL, -500)).toEqual({ min: 0, max: 200 });
  });

  it("stops at the end of the session", () => {
    expect(panGuideView({ min: 700, max: 900 }, FULL, 500)).toEqual({ min: 800, max: 1000 });
  });
});

describe("sliceFramesByTime", () => {
  const series = Array.from({ length: 100 }, (_, i) => frame(i * 10, 0.1, 0.2));

  it("keeps one frame either side so the line reaches both edges", () => {
    const slice = sliceFramesByTime(series, 200, 300);
    expect(slice[0].t).toBe(190);
    expect(slice[slice.length - 1].t).toBe(310);
  });

  it("does not run off the ends of the series", () => {
    expect(sliceFramesByTime(series, -50, 20)[0].t).toBe(0);
    expect(sliceFramesByTime(series, 980, 2000).slice(-1)[0].t).toBe(990);
  });

  it("returns nothing for an empty series", () => {
    expect(sliceFramesByTime([], 0, 100)).toEqual([]);
  });

  it("sharpens a spike that the full-session downsample had flattened", () => {
    // 30k frames is well past the 2000-point budget, so a spike shares its
    // bucket with hundreds of quiet frames until the view narrows onto it.
    const long = Array.from({ length: 30_000 }, (_, i) =>
      frame(i, i === 15_000 ? 4.2 : 0.1, 0.1)
    );
    const wide = downsampleGuideFrames(long, 2000);
    const near = downsampleGuideFrames(sliceFramesByTime(long, 14_990, 15_010), 2000);
    expect(near.length).toBeLessThan(wide.length);
    expect(near.some((f) => f.ra === 4.2)).toBe(true);
    // The narrow view carries every frame around the spike, not one per bucket.
    expect(near.filter((f) => f.t >= 14_990 && f.t <= 15_010).length).toBe(21);
  });
});

// The vertical axis reuses the same window maths as the horizontal one, with a
// zero-centred range and a much finer floor. These cases pin the parts the
// x-axis cases never reach: a range whose minimum is negative, and the
// arcsecond floor.
const Y_BOUND = 2;
const Y_FULL = guideYRange(Y_BOUND);
/** Top of the padded range: the bound plus its headroom. */
const Y_EDGE = Y_FULL.max;
const Y_SPAN = Y_FULL.max - Y_FULL.min;

describe("guideYRange", () => {
  it("centres the vertical extent on zero", () => {
    const r = guideYRange(1.4);
    expect(r.min).toBe(-r.max);
  });

  it("leaves headroom above the largest excursion so peaks never touch the edge", () => {
    expect(guideYRange(1.4).max).toBeCloseTo(1.4 * (1 + GUIDE_Y_HEADROOM), 10);
    expect(guideYRange(1.4).max).toBeGreaterThan(1.4);
  });

  it("is the view a reset returns to, so a peak keeps its air", () => {
    // symmetricYBound floors at 1 for a quiet night; the padded range clears it.
    const bound = symmetricYBound([frame(0, 0.5, -0.4)]);
    expect(guideYRange(bound).max).toBeGreaterThan(bound);
  });

  it("carries an outer cap ten times its own width", () => {
    const r = guideYRange(1.4);
    expect(r.maxSpan).toBeCloseTo((r.max - r.min) * 10, 10);
  });
});

describe("vertical view window", () => {
  it("keeps a zoomed window inside a range that starts negative", () => {
    const low = clampGuideView({ min: -3, max: -2.5 }, Y_FULL, MIN_GUIDE_Y_SPAN);
    expect(low.min).toBeCloseTo(-Y_EDGE, 10);
    expect(low.max).toBeCloseTo(-Y_EDGE + 0.5, 10);
    const high = clampGuideView({ min: Y_EDGE - 0.36, max: Y_EDGE + 0.24 }, Y_FULL, MIN_GUIDE_Y_SPAN);
    expect(high.min).toBeCloseTo(Y_EDGE - 0.6, 10);
    expect(high.max).toBeCloseTo(Y_EDGE, 10);
  });

  it("refuses to zoom below a tenth of an arcsecond of total span", () => {
    let v: { min: number; max: number } = Y_FULL;
    for (let i = 0; i < 60; i++) v = zoomGuideView(v, Y_FULL, 0.3, 0.5, MIN_GUIDE_Y_SPAN);
    expect(v.max - v.min).toBeCloseTo(MIN_GUIDE_Y_SPAN, 10);
  });

  it("keeps the arcsecond value under the cursor under the cursor", () => {
    const before = (1 - Y_FULL.min) / Y_SPAN;
    const v = zoomGuideView(Y_FULL, Y_FULL, 1, 0.5, MIN_GUIDE_Y_SPAN);
    expect(v.max - v.min).toBeCloseTo(Y_SPAN / 2, 10);
    expect((1 - v.min) / (v.max - v.min)).toBeCloseTo(before, 10);
  });

  it("zooms out past the data range instead of stopping at it", () => {
    const v = zoomGuideView(Y_FULL, Y_FULL, 0, 2, MIN_GUIDE_Y_SPAN);
    expect(v.max - v.min).toBeCloseTo(Y_SPAN * 2, 10);
    expect(v.max).toBeGreaterThan(Y_EDGE);
  });

  it("stays centred on zero once it is wider than the data", () => {
    const v = zoomGuideView({ min: -0.4, max: 0.4 }, Y_FULL, 0.4, 20, MIN_GUIDE_Y_SPAN);
    expect(v.min).toBeCloseTo(-v.max, 10);
  });

  it("stops at the outer cap however far it is zoomed out", () => {
    let v: { min: number; max: number } = Y_FULL;
    for (let i = 0; i < 40; i++) v = zoomGuideView(v, Y_FULL, 0, 2, MIN_GUIDE_Y_SPAN);
    expect(v.max - v.min).toBeCloseTo(Y_FULL.maxSpan!, 10);
    expect(v.max - v.min).toBeCloseTo(Y_SPAN * 10, 10);
  });

  it("pans vertically and stops at the top and the bottom", () => {
    expect(panGuideView({ min: -0.5, max: 0.5 }, Y_FULL, 0.25, MIN_GUIDE_Y_SPAN)).toEqual({
      min: -0.25,
      max: 0.75,
    });
    const up = panGuideView({ min: -0.5, max: 0.5 }, Y_FULL, 99, MIN_GUIDE_Y_SPAN);
    expect(up.min).toBeCloseTo(Y_EDGE - 1, 10);
    expect(up.max).toBeCloseTo(Y_EDGE, 10);
    const down = panGuideView({ min: -0.5, max: 0.5 }, Y_FULL, -99, MIN_GUIDE_Y_SPAN);
    expect(down.min).toBeCloseTo(-Y_EDGE, 10);
    expect(down.max).toBeCloseTo(-Y_EDGE + 1, 10);
  });

  it("has nowhere to pan to once it is wider than the data", () => {
    const wide = { min: -Y_SPAN, max: Y_SPAN };
    expect(panGuideView(wide, Y_FULL, 5, MIN_GUIDE_Y_SPAN)).toEqual(wide);
  });

  it("leaves a quiet night that fits inside the floor alone", () => {
    const tiny = guideYRange(0.03);
    expect(clampGuideView({ min: -0.01, max: 0.01 }, tiny, MIN_GUIDE_Y_SPAN)).toEqual({
      min: tiny.min,
      max: tiny.max,
    });
  });
});

describe("horizontal view window is unaffected by the vertical cap", () => {
  it("still refuses to grow past the session", () => {
    expect(clampGuideView({ min: -500, max: 5000 }, FULL)).toEqual(FULL);
    expect(zoomGuideView({ min: 400, max: 600 }, FULL, 500, 50)).toEqual(FULL);
  });
});

describe("isFullGuideView", () => {
  it("recognises the full range whatever rounding the zoom step left behind", () => {
    expect(isFullGuideView(Y_FULL, Y_FULL)).toBe(true);
    expect(isFullGuideView({ min: -Y_EDGE, max: Y_EDGE * (1 + 1e-12) }, Y_FULL)).toBe(true);
    expect(isFullGuideView(FULL, FULL)).toBe(true);
  });

  it("does not call a zoomed-in window full", () => {
    expect(isFullGuideView({ min: -0.5, max: 0.5 }, Y_FULL)).toBe(false);
    expect(isFullGuideView({ min: 0, max: 500 }, FULL)).toBe(false);
  });

  it("does not call a window wider than the data full, so zoom-out survives", () => {
    expect(isFullGuideView({ min: -Y_SPAN, max: Y_SPAN }, Y_FULL)).toBe(false);
  });
});
