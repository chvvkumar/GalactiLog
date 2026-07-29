import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { QueryClient, QueryClientProvider } from "@tanstack/solid-query";

// The guide graph builds its chart once and then updates it in place, which is
// what makes a zoom gesture smooth. That leaves one trap: the canvas is behind
// the pixel-scale gate, so selecting a session whose log header carries no
// scale unmounts it. The frame count stays high in that state (a null scale
// nulls every ra and dec, it does not remove frames), so nothing else tells the
// component to tear the chart down. Selecting a scaled session again mounts a
// FRESH canvas, and a chart still bound to the detached one draws nowhere: the
// panel stays blank until it is collapsed and reopened.
//
// The component tracks the exact node it bound to and rebuilds when the live
// ref differs. This test drives that path.

const session = (id: string, scale: number | null) => ({
  id,
  started_at: "2026-07-14T21:42:27Z",
  ended_at: "2026-07-14T22:04:27Z",
  duration_s: 1320,
  frame_count: 3,
  equipment_profile: "140APO_AM5N_ASI174MM",
  telescope: "140APO",
  pixel_scale_arcsec: scale,
  rms_ra_arcsec: 0.41,
  rms_dec_arcsec: 0.58,
  rms_total_arcsec: 0.71,
  peak_ra_arcsec: 2.2,
  peak_dec_arcsec: 3.1,
  drop_count: 0,
  max_drop_run: 0,
  unguided_seconds: 0,
  dither_count: 0,
  settle_count: 0,
  settle_failed_count: 0,
  settle_median_s: null,
  snr_mean: 28.4,
  star_mass_mean: 1702,
  last_cal_issue: null,
  pier_side: "West",
  gated: false,
});

const frame = (t: number, v: number | null) => ({
  t,
  ra: v,
  dec: v,
  ra_pulse_ms: 0,
  ra_dir: "",
  dec_pulse_ms: 0,
  dec_dir: "",
  snr: 20,
  mass: 1,
  dropped: false,
});

const framesFor: Record<string, unknown> = {
  // Scaled: plottable.
  "scaled-1": {
    pixel_scale_arcsec: 1.54,
    started_at: "2026-07-14T21:42:27Z",
    frames: [frame(0, 0.1), frame(3, 0.4), frame(6, -0.5)],
    events: [],
  },
  // Unscaled: frames present, every value null, so the panel hides the canvas.
  "unscaled-2": {
    pixel_scale_arcsec: null,
    started_at: "2026-07-14T22:42:27Z",
    frames: [frame(0, null), frame(3, null), frame(6, null)],
    events: [],
  },
};

vi.mock("../api/generated/client", () => ({
  apiClient: {
    GET: vi.fn((path: string, init: { params?: { path?: { id?: string } } }) => {
      if (path === "/api/phd2/sessions") {
        return Promise.resolve({
          data: { sessions: [session("scaled-1", 1.54), session("unscaled-2", null)] },
          response: { ok: true },
        });
      }
      const id = init?.params?.path?.id ?? "";
      return Promise.resolve({ data: framesFor[id], response: { ok: true } });
    }),
  },
}));

/** Display settings the panel reads. Mutable so a test can flip the clock the
 *  same way the Display tab does. */
let use24h = false;

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    timezone: () => "UTC",
    use24hTime: () => use24h,
  }),
}));

type FakeAxis = {
  min: number;
  max: number;
  title?: { display?: boolean; text?: string };
  ticks?: { callback?: (value: number) => string };
};

type FakeOptions = {
  scales: { x: FakeAxis; y: FakeAxis };
  plugins?: {
    tooltip?: {
      callbacks?: {
        title?: (items: { parsed: { x: number } }[]) => string;
        label?: (item: { dataset: { label?: string }; parsed: { y: number } }) => string;
      };
    };
  };
};

/** Every chart the component has constructed, in order, with the canvas it
 *  was handed, its options, per-dataset visibility, and whether it was later
 *  destroyed. */
const built: {
  canvas: HTMLCanvasElement;
  destroyed: boolean;
  axes: { x: { min: number; max: number }; y: { min: number; max: number } };
  options: FakeOptions;
  visibility: Record<number, boolean>;
}[] = [];

/** Plot area the fake chart pretends to occupy, in CSS pixels. jsdom reports a
 *  zero-sized bounding rect, so pointer coordinates land straight on it. */
const PLOT_W = 400;
const PLOT_H = 200;

let resizeCalls = 0;

vi.mock("chart.js", () => {
  type AxisOpts = FakeAxis;
  class FakeChart {
    data: { datasets: unknown };
    options: FakeOptions;
    scales: Record<string, unknown>;
    private entry: (typeof built)[number];
    constructor(
      canvas: HTMLCanvasElement,
      config: { data: { datasets: unknown }; options: FakeOptions },
    ) {
      this.data = config.data;
      this.options = config.options;
      const axis = (name: "x" | "y") => this.options.scales[name];
      // Enough of a scale for the zoom and pan handlers to do real arithmetic:
      // geometry, live min and max, and a pixel-to-value mapping.
      this.scales = {
        x: {
          left: 0,
          right: PLOT_W,
          top: 0,
          bottom: PLOT_H,
          get min() { return axis("x").min; },
          get max() { return axis("x").max; },
          getValueForPixel: (px: number) => {
            const a = axis("x");
            return a.min + (px / PLOT_W) * (a.max - a.min);
          },
        },
        y: {
          left: 0,
          right: PLOT_W,
          top: 0,
          bottom: PLOT_H,
          get min() { return axis("y").min; },
          get max() { return axis("y").max; },
          getValueForPixel: (px: number) => {
            const a = axis("y");
            return a.max - (px / PLOT_H) * (a.max - a.min);
          },
        },
      };
      this.entry = {
        canvas,
        destroyed: false,
        axes: this.options.scales,
        options: this.options,
        visibility: {},
      };
      built.push(this.entry);
    }
    setDatasetVisibility(index: number, visible: boolean) {
      this.entry.visibility[index] = visible;
    }
    update() {}
    resize() {
      resizeCalls += 1;
    }
    destroy() {
      this.entry.destroyed = true;
    }
  }
  return { Chart: FakeChart };
});
vi.mock("../utils/chartRegistry", () => ({}));

import Phd2GuideGraph from "./Phd2GuideGraph";
import { clockTime, clockTimeWithSeconds } from "../utils/phd2Format";

function Harness() {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Phd2GuideGraph sessionDate="2026-07-14" telescope={null} />
    </QueryClientProvider>
  );
}

const settle = async (ticks = 10) => {
  for (let i = 0; i < ticks; i++) {
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => requestAnimationFrame(() => r(null)));
  }
};

describe("Phd2GuideGraph canvas binding", () => {
  it("rebinds the chart after the pixel-scale gate swaps the canvas", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);

    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const first = container.querySelector("canvas") as HTMLCanvasElement;
    expect(first).not.toBeNull();
    expect(built.length).toBe(1);
    expect(built[0].canvas).toBe(first);

    // Select the session with no pixel scale: the canvas is replaced by the
    // explanatory message while the frame count stays at three.
    const select = container.querySelector("select") as HTMLSelectElement;
    expect(select).not.toBeNull();
    fireEvent.change(select, { target: { value: "unscaled-2" } });
    await settle();
    expect(container.querySelector("canvas")).toBeNull();

    // Back to the scaled session: a brand new canvas node is mounted.
    fireEvent.change(select, { target: { value: "scaled-1" } });
    await settle();

    const second = container.querySelector("canvas") as HTMLCanvasElement;
    expect(second).not.toBeNull();
    expect(second).not.toBe(first);

    // The live chart must be bound to the canvas that is actually on screen,
    // and the one bound to the detached node must have been destroyed.
    const live = built.filter((c) => !c.destroyed);
    expect(live.length).toBe(1);
    expect(live[0].canvas).toBe(second);
    expect(live[0].canvas.isConnected).toBe(true);
  });
});

describe("Phd2GuideGraph vertical zoom", () => {
  it("zooms the arcsecond axis on Shift+wheel and leaves time alone", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    const axes = built[0].axes;
    // Largest excursion is 0.5 arcsec, so symmetricYBound floors at 1, and
    // guideYRange pads that by 8 percent so the peak keeps air above it.
    expect(axes.y.min).toBeCloseTo(-1.08, 10);
    expect(axes.y.max).toBeCloseTo(1.08, 10);
    const timeBefore = { ...axes.x };

    // Halfway down the plot area is the zero line, so the window stays centred.
    canvas.dispatchEvent(
      new WheelEvent("wheel", { deltaY: -120, shiftKey: true, clientX: 200, clientY: 100, bubbles: true, cancelable: true }),
    );
    await settle();

    expect(axes.y.max).toBeLessThan(1.08);
    expect(axes.y.max).toBeCloseTo(1.08 * 0.82, 6);
    expect(axes.y.min).toBeCloseTo(-1.08 * 0.82, 6);
    expect(axes.x).toEqual(timeBefore);

    // Double-click puts both axes back, headroom included.
    canvas.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    await settle();
    expect(axes.y.min).toBeCloseTo(-1.08, 10);
    expect(axes.y.max).toBeCloseTo(1.08, 10);
    expect(axes.x).toEqual(timeBefore);

    // Scrolling the other way keeps going past the data, which is what a
    // reader does to see how flat the night was.
    canvas.dispatchEvent(
      new WheelEvent("wheel", { deltaY: 120, shiftKey: true, clientX: 200, clientY: 100, bubbles: true, cancelable: true }),
    );
    await settle();
    expect(axes.y.max).toBeGreaterThan(1.08);
    expect(axes.y.min).toBeCloseTo(-axes.y.max, 10);
    expect(axes.x).toEqual(timeBefore);
  });

  it("never zooms the arcsecond axis past a tenth of an arcsecond", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    const axes = built[0].axes;
    for (let i = 0; i < 40; i++) {
      canvas.dispatchEvent(
        new WheelEvent("wheel", { deltaY: -120, shiftKey: true, clientX: 200, clientY: 100, bubbles: true, cancelable: true }),
      );
    }
    await settle();
    expect(axes.y.max - axes.y.min).toBeCloseTo(0.1, 8);
  });
});

describe("Phd2GuideGraph resize grip", () => {
  it("drags the plot taller without rebuilding the chart", async () => {
    built.length = 0;
    resizeCalls = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const plot = container.querySelector("canvas")!.parentElement as HTMLElement;
    expect(plot.style.height).toBe("220px");
    const canvasBefore = container.querySelector("canvas");

    const grip = container.querySelector(".cursor-nwse-resize") as HTMLElement;
    expect(grip).not.toBeNull();
    grip.dispatchEvent(new MouseEvent("mousedown", { clientY: 500, bubbles: true, cancelable: true }));
    document.dispatchEvent(new MouseEvent("mousemove", { clientY: 620, bubbles: true }));
    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    await settle(2);

    expect(plot.style.height).toBe("340px");
    expect(resizeCalls).toBeGreaterThan(0);
    // Same chart, same canvas: a height change must not detach the binding.
    expect(built.length).toBe(1);
    expect(built[0].destroyed).toBe(false);
    expect(container.querySelector("canvas")).toBe(canvasBefore);
  });

  it("stops shrinking at the floor", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const plot = container.querySelector("canvas")!.parentElement as HTMLElement;
    const grip = container.querySelector(".cursor-nwse-resize") as HTMLElement;
    grip.dispatchEvent(new MouseEvent("mousedown", { clientY: 500, bubbles: true, cancelable: true }));
    document.dispatchEvent(new MouseEvent("mousemove", { clientY: 100, bubbles: true }));
    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    await settle(2);

    expect(plot.style.height).toBe("140px");
  });
});

describe("Phd2GuideGraph clock time axis", () => {
  // The mocked settings put the panel in UTC, so the session that starts at
  // 21:42:27Z reads 21:42 on a 24-hour clock and 09:42 PM on a 12-hour one.
  const START = "2026-07-14T21:42:27Z";
  const TZ = "UTC";

  it("labels the time axis with the clock time of night from the frames response", async () => {
    built.length = 0;
    use24h = true;
    try {
      const { getByRole, container } = render(() => <Harness />);
      fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
      await settle();

      const opts = built[0].options;
      // The domain itself is still elapsed seconds, so zoom and pan arithmetic
      // is unaffected; only the printed label is converted.
      expect(opts.scales.x.min).toBe(0);
      expect(opts.scales.x.max).toBe(6);

      const tick = opts.scales.x.ticks?.callback;
      expect(tick).toBeTypeOf("function");
      expect(tick!(0)).toBe("21:42");
      expect(tick!(180)).toBe(clockTime(START, 180, { hour12: false, timeZone: TZ }));

      expect(opts.scales.x.title?.display).toBe(true);
      expect(opts.scales.x.title?.text).toBe("Time of night");

      const title = opts.plugins?.tooltip?.callbacks?.title;
      expect(title).toBeTypeOf("function");
      expect(title!([{ parsed: { x: 3 } }])).toBe("21:42:30");
      expect(title!([])).toBe("");

      // The caption reads in clock time too, and no longer carries the
      // downsampling note.
      expect(container.textContent).not.toContain("peaks preserved");
      expect(container.textContent).toContain(
        "Error in arcseconds against the clock time of night.",
      );
    } finally {
      use24h = false;
    }
  });

  it("honours the 12-hour display setting, like the session dropdown beside it", async () => {
    built.length = 0;
    use24h = false;
    const { getByRole } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const opts = built[0].options;
    const tick = opts.scales.x.ticks?.callback;
    expect(tick!(0)).toBe(clockTime(START, 0, { hour12: true, timeZone: TZ }));
    expect(tick!(0)).toContain("09:42");
    expect(tick!(0)).not.toBe("21:42");

    const title = opts.plugins?.tooltip?.callbacks?.title;
    expect(title!([{ parsed: { x: 3 } }])).toBe(
      clockTimeWithSeconds(START, 3, { hour12: true, timeZone: TZ }),
    );
    expect(title!([{ parsed: { x: 3 } }])).toContain("09:42:30");
  });
});

describe("Phd2GuideGraph legend", () => {
  it("hides a series on click and restores it on a second click", async () => {
    built.length = 0;
    const { getByRole } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const ra = getByRole("button", { name: "RA" });
    // Nothing hidden yet: the chart is left alone entirely.
    expect(ra.getAttribute("aria-pressed")).toBe("true");
    expect(built[0].visibility).toEqual({});

    fireEvent.click(ra);
    await settle();
    // RA is dataset 0, Dec 1, Star lost 2.
    expect(built[0].visibility[0]).toBe(false);
    expect(built[0].visibility[1]).toBe(true);
    expect(built[0].visibility[2]).toBe(true);
    expect(ra.getAttribute("aria-pressed")).toBe("false");
    expect(ra.className).toContain("line-through");

    fireEvent.click(ra);
    await settle();
    expect(built[0].visibility[0]).toBe(true);
    expect(ra.getAttribute("aria-pressed")).toBe("true");
    expect(ra.className).not.toContain("line-through");
    // Same chart throughout: a legend toggle must not rebuild the canvas.
    expect(built.length).toBe(1);
    expect(built[0].destroyed).toBe(false);
  });

  it("gives every entry, including the plugin overlays, button semantics", async () => {
    built.length = 0;
    const { getByRole } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    for (const label of ["RA", "Dec", "Star lost", "Dither", "Settling"]) {
      const entry = getByRole("button", { name: label });
      expect(entry.getAttribute("type")).toBe("button");
      expect(entry.getAttribute("aria-pressed")).toBe("true");
    }

    // Dither and Settling have no dataset behind them; the plugin reads the
    // same hidden set, so the toggle still has to register.
    const settling = getByRole("button", { name: "Settling" });
    fireEvent.click(settling);
    await settle();
    expect(settling.getAttribute("aria-pressed")).toBe("false");
    expect(settling.className).toContain("line-through");
  });
});

describe("Phd2GuideGraph section help", () => {
  it("shows the glyph only while the section is open", async () => {
    built.length = 0;
    const { getByRole, queryByRole } = render(() => <Harness />);

    // Collapsed, the header must read exactly like its sibling sections in the
    // session card, which carry no glyph at all.
    expect(queryByRole("button", { name: "About the guide graph" })).toBeNull();

    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();
    expect(queryByRole("button", { name: "About the guide graph" })).not.toBeNull();

    // Collapsing takes it away again.
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();
    expect(queryByRole("button", { name: "About the guide graph" })).toBeNull();
  });

  it("opens the help popover from the section header", async () => {
    built.length = 0;
    const { getByRole, queryByRole } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const glyph = getByRole("button", { name: "About the guide graph" });
    expect(queryByRole("dialog")).toBeNull();

    fireEvent.click(glyph);
    const dialog = getByRole("dialog") as HTMLElement;
    expect(dialog.textContent).toContain("guiding error in arcseconds");
    expect(dialog.textContent).toContain("Shift+scroll to zoom the arcsecond axis.");
    expect(dialog.textContent).toContain("Click a legend entry to hide or show that series.");
    expect(dialog.textContent).toContain("Dither");
    expect(dialog.textContent).toContain("Settling");
    expect(dialog.textContent).toContain("Star lost");
  });

  it("opening help must not collapse the section", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();
    expect(container.querySelector("canvas")).not.toBeNull();

    fireEvent.click(getByRole("button", { name: "About the guide graph" }));
    await settle(2);
    // The glyph stops its own click, so the row's toggle never sees it.
    expect(container.querySelector("canvas")).not.toBeNull();
    expect(getByRole("dialog")).toBeTruthy();
  });
});

describe("Phd2GuideGraph header geometry", () => {
  // The header has to be indistinguishable from the sibling sections in the
  // session card (Session Metrics, Per-Frame Data, FITS Headers): one
  // full-width row, title left behind the accent rule, chevron hard against
  // the right edge, hover across the whole row rather than a pill around the
  // title. The glyph is the only addition, and only while open.
  const SIBLING_ROW_CLASSES = [
    "flex",
    "items-center",
    "w-full",
    "text-xs",
    "py-2",
    "px-3",
    "hover:bg-theme-hover",
    "rounded-[var(--radius-sm)]",
    "hover:text-theme-text-primary",
    "transition-colors",
    "cursor-pointer",
  ];

  it("matches the sibling section headers when collapsed", () => {
    const { getByRole, container } = render(() => <Harness />);
    const title = getByRole("button", { name: "Guide Graph (PHD2)" });
    const row = title.parentElement as HTMLElement;

    for (const cls of SIBLING_ROW_CLASSES) expect(row.className).toContain(cls);

    // The title carries no hover background of its own: collapsed, it must not
    // read as a pill sitting inside the row.
    expect(title.className).not.toContain("hover:bg-theme-hover");
    expect(title.className).not.toContain("rounded");
    expect(title.className).toContain("border-l-2");
    expect(title.className).toContain("border-theme-accent");

    // Chevron last in the row and pushed to the right edge.
    const chevron = row.lastElementChild as HTMLElement;
    expect(chevron.tagName.toLowerCase()).toBe("svg");
    expect(chevron.getAttribute("class")).toContain("ml-auto");
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("keeps the chevron at the right edge and the glyph beside the title when open", async () => {
    const { getByRole } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const title = getByRole("button", { name: "Guide Graph (PHD2)" });
    const glyph = getByRole("button", { name: "About the guide graph" });
    const row = title.parentElement as HTMLElement;

    for (const cls of SIBLING_ROW_CLASSES) expect(row.className).toContain(cls);

    // Order in the row: title, glyph, chevron.
    expect(row.contains(glyph)).toBe(true);
    expect(title.nextElementSibling).toBe(glyph.parentElement?.parentElement);
    const chevron = row.lastElementChild as HTMLElement;
    expect(chevron.tagName.toLowerCase()).toBe("svg");
    expect(chevron.getAttribute("class")).toContain("ml-auto");
  });
});

describe("Phd2GuideGraph resize grip placement", () => {
  it("hangs off the section panel, not off the plot", async () => {
    built.length = 0;
    const { getByRole, container } = render(() => <Harness />);
    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle();

    const plot = container.querySelector("canvas")!.parentElement as HTMLElement;
    const grip = container.querySelector(".cursor-nwse-resize") as HTMLElement;
    const panel = container.querySelector(".border-theme-border-em") as HTMLElement;

    // Over the plot the grip covered the last axis label and swallowed the
    // wheel and drag gestures in that corner, so it must live outside it.
    expect(plot.contains(grip)).toBe(false);
    expect(panel.contains(grip)).toBe(true);
    // Absolute positioning only reaches the panel if the panel is positioned.
    expect(panel.className).toContain("relative");
    expect(grip.className).toContain("bottom-1");
    expect(grip.className).toContain("right-1");
  });
});
