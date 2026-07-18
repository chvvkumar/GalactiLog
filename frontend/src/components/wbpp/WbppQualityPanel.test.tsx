import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import WbppQualityPanel from "./WbppQualityPanel";
import {
  defaultConstraintFor,
  type FrameVerdict,
  type QualityConfig,
  type RawConstraint,
} from "../../lib/wbppQualityFilter";
import type { FrameRecord, SessionDetail } from "../../api/types";

const DATE = "2026-07-01";

const DEFAULT_CONFIG: QualityConfig = { baseline: "session", constraints: [] };

function config(constraints: RawConstraint[], over: Partial<QualityConfig> = {}): QualityConfig {
  return { ...DEFAULT_CONFIG, constraints, ...over };
}

function frame(name: string, over: Partial<FrameRecord> = {}): FrameRecord {
  return {
    file_name: name,
    filter_used: "L",
    source_relative: `lights/${name}`,
    timestamp: "2026-07-01T00:00:00",
    median_hfr: null,
    eccentricity: null,
    fwhm: null,
    detected_stars: null,
    guiding_rms_arcsec: null,
    adu_median: null,
    rig: null,
    ...over,
  } as FrameRecord;
}

function verdict(
  name: string,
  keep: boolean,
  reason: FrameVerdict["reason"],
  over: Partial<FrameRecord> = {},
  failedBy: string | null = null,
): FrameVerdict {
  return {
    frame: frame(name, over),
    sessionDate: DATE,
    groupKey: "TS|Cam|L",
    keep,
    reason,
    failedBy,
  };
}

const VERDICTS: FrameVerdict[] = [
  verdict("a.fits", true, "pass", { timestamp: "2026-07-01T01:00:00" }),
  verdict("b.fits", false, "fail", { timestamp: "2026-07-01T02:00:00" }, "HFR 2.80 > 2.00"),
  verdict("c.fits", false, "unmeasured", { timestamp: "2026-07-01T03:00:00" }),
];

// A baseline group needs n >= MIN_GROUP (8) and a non-zero mad, else madZ
// returns null and every cell bands to neutral.
function baseline(median: number, mad: number) {
  return { median, mad, n: 20 };
}

// Key format is "telescope|camera|filter"; the frames above use filter "L".
// One frame in the detail so defaultConstraintFor has a train to resolve.
function sessionDetail(over: Partial<SessionDetail> = {}): SessionDetail {
  return {
    equipment: { telescope: "TS", camera: "Cam" },
    rigs: [],
    frames: [frame("seed.fits")],
    session_baselines: {
      "TS|Cam|L": {
        median_hfr: baseline(2.1, 0.37),
        eccentricity: baseline(0.5, 0.05),
        fwhm: baseline(3.0, 0.4),
        detected_stars: baseline(100, 10),
      },
    },
    rig_baselines: {},
    ...over,
  } as SessionDetail;
}

const DETAILS: Record<string, SessionDetail> = { [DATE]: sessionDetail() };

function setup(over: Partial<Parameters<typeof WbppQualityPanel>[0]> = {}) {
  const calls: { enabled: boolean[]; config: QualityConfig[] } = { enabled: [], config: [] };
  const result = render(() => (
    <WbppQualityPanel
      enabled={over.enabled ?? true}
      onEnabledChange={(on) => calls.enabled.push(on)}
      config={over.config ?? DEFAULT_CONFIG}
      onConfigChange={(next) => calls.config.push(next)}
      verdicts={over.verdicts ?? VERDICTS}
      loading={over.loading ?? false}
      sessionDetails={over.sessionDetails ?? DETAILS}
    />
  ));
  return { ...result, calls };
}

function headers(container: HTMLElement): string[] {
  // Strip the sort arrow glyphs so the labels compare clean.
  return Array.from(container.querySelectorAll("thead th")).map((th) =>
    th.textContent!.replace(/[▲▼]/g, "").trim(),
  );
}

function headerFor(container: HTMLElement, label: string): HTMLElement {
  return Array.from(container.querySelectorAll("thead th")).find((th) =>
    th.textContent!.startsWith(label),
  ) as HTMLElement;
}

function fileColumn(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("tbody tr td:first-child")).map(
    (td) => td.textContent!,
  );
}

// The dashed "+ <label>" chip for a metric with no (enabled) constraint.
function ghostChip(container: HTMLElement, label: string): HTMLButtonElement {
  return Array.from(container.querySelectorAll("button")).find(
    (b) => b.textContent!.includes("+") && b.textContent!.includes(label),
  ) as HTMLButtonElement;
}

describe("WbppQualityPanel enable checkbox", () => {
  it("reflects the enabled prop and emits changes both ways", () => {
    const off = setup({ enabled: false });
    const box = off.getByLabelText("Enable filters") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect(off.calls.enabled).toEqual([true]);

    const on = setup({ enabled: true });
    const onBox = on.getByLabelText("Enable filters") as HTMLInputElement;
    expect(onBox.checked).toBe(true);
    fireEvent.click(onBox);
    expect(on.calls.enabled).toEqual([false]);
  });

  it("keeps the checkbox live while the rest of the toolbar is inert", () => {
    const { container, getByLabelText } = setup({ enabled: false });
    const inert = container.querySelector(".pointer-events-none") as HTMLElement;
    expect(inert).not.toBe(null);
    expect(inert.className).toContain("opacity-50");
    // The checkbox sits outside the inert wrapper; the chips sit inside it.
    expect(inert.contains(getByLabelText("Enable filters"))).toBe(false);
    expect(inert.contains(ghostChip(container, "HFR"))).toBe(true);
  });
});

describe("WbppQualityPanel chips toolbar", () => {
  it("renders five ghost chips and none of the old controls", () => {
    const { container, queryByText, queryByLabelText } = setup();
    for (const label of ["HFR", "Ecc", "FWHM", "Stars", "RMS"]) {
      expect(ghostChip(container, label)).toBeTruthy();
    }
    // No Mode dropdown, no score threshold, no "+ Add constraint" link.
    expect(queryByLabelText("Mode")).toBe(null);
    expect(queryByLabelText("Score threshold")).toBe(null);
    expect(queryByText("+ Add constraint")).toBe(null);
  });

  it("appends defaultConstraintFor's constraint when a ghost chip is clicked", () => {
    const { container, calls } = setup();
    fireEvent.click(ghostChip(container, "HFR"));
    expect(calls.config.length).toBe(1);
    // The chip must emit exactly what the lib derives from the same details,
    // dates and config the panel was given -- not a hand-rolled default.
    const expected = defaultConstraintFor("hfr", DETAILS, [DATE], DEFAULT_CONFIG);
    expect(calls.config[0]).toEqual({ ...DEFAULT_CONFIG, constraints: [expected] });
    expect(calls.config[0].constraints[0].enabled).toBe(true);
    expect(calls.config[0].constraints[0].op).toBe("lte");
  });

  it("appends to the existing constraints rather than replacing them", () => {
    const held: RawConstraint = { metric: "ecc", op: "lte", value: 0.55, enabled: true };
    const { container, calls } = setup({ config: config([held]) });
    fireEvent.click(ghostChip(container, "Stars"));
    const expected = defaultConstraintFor("stars", DETAILS, [DATE], config([held]));
    expect(calls.config[0].constraints).toEqual([held, expected]);
  });

  it("renders an enabled constraint as an inline pill editor", () => {
    const { container, getByLabelText, queryByText } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: true }]),
    });
    expect((getByLabelText("HFR threshold") as HTMLInputElement).value).toBe("1.65");
    expect((getByLabelText("HFR comparison") as HTMLSelectElement).value).toBe("lte");
    // The active metric no longer offers a ghost chip.
    expect(ghostChip(container, "HFR")).toBe(undefined);
    // The other metrics still do.
    expect(ghostChip(container, "Ecc")).toBeTruthy();
    expect(queryByText("Remove")).toBe(null);
  });

  it("emits the edited value as a number, other fields untouched", () => {
    const { getByLabelText, calls } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: true }]),
    });
    fireEvent.input(getByLabelText("HFR threshold"), { target: { value: "2.5" } });
    expect(calls.config[0].constraints).toEqual([
      { metric: "hfr", op: "lte", value: 2.5, enabled: true },
    ]);
  });

  it("emits the flipped op when the comparison select changes", () => {
    const { getByLabelText, calls } = setup({
      config: config([{ metric: "stars", op: "gte", value: 100, enabled: true }]),
    });
    fireEvent.change(getByLabelText("Stars comparison"), { target: { value: "lte" } });
    expect(calls.config[0].constraints).toEqual([
      { metric: "stars", op: "lte", value: 100, enabled: true },
    ]);
  });

  it("disables (never deletes) on x, keeping the value", () => {
    const { getByLabelText, calls } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: true }]),
    });
    fireEvent.click(getByLabelText("Disable HFR constraint"));
    expect(calls.config[0].constraints).toEqual([
      { metric: "hfr", op: "lte", value: 1.65, enabled: false },
    ]);
  });

  it("shows the held value on a disabled constraint's ghost chip", () => {
    const { container } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: false }]),
    });
    const chip = ghostChip(container, "HFR");
    expect(chip.textContent!.replace(/\s+/g, " ")).toContain("≤ 1.65");
  });

  it("re-enables a disabled constraint without resetting its value", () => {
    const { container, calls } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: false }]),
    });
    fireEvent.click(ghostChip(container, "HFR"));
    expect(calls.config[0].constraints).toEqual([
      { metric: "hfr", op: "lte", value: 1.65, enabled: true },
    ]);
  });
});

describe("WbppQualityPanel stat pill", () => {
  const pill = (container: HTMLElement) => container.querySelector("span.ml-auto") as HTMLElement;

  it("counts kept and skipped from the verdicts", () => {
    const { container } = setup();
    const p = pill(container);
    expect(p.querySelector(".text-theme-success")!.textContent).toBe("1");
    expect(p.querySelector(".text-theme-error")!.textContent).toBe("2");
    expect(p.textContent!.replace(/\s+/g, " ")).toContain("of 3");
  });

  it("reads everything kept while the master toggle is off", () => {
    const { container } = setup({ enabled: false });
    const p = pill(container);
    expect(p.querySelector(".text-theme-success")!.textContent).toBe("3");
    expect(p.querySelector(".text-theme-error")!.textContent).toBe("0");
  });
});

describe("WbppQualityPanel baseline control", () => {
  it("accents the active baseline and emits the other on click", () => {
    const { getByText, calls } = setup();
    expect(getByText("This session").className).toContain("bg-theme-accent/20");
    expect(getByText("Rig (catalog)").className).not.toContain("bg-theme-accent/20");
    fireEvent.click(getByText("Rig (catalog)"));
    expect(calls.config).toEqual([{ ...DEFAULT_CONFIG, baseline: "rig" }]);
  });
});

describe("WbppQualityPanel table columns", () => {
  it("renders the fixed column set with no Score column", () => {
    const { container } = setup();
    expect(headers(container)).toEqual([
      "File", "Session", "Filter", "HFR", "Ecc", "FWHM", "Stars", "RMS", "Verdict",
    ]);
  });

  it("pins the header with a solid background so rows cannot bleed through", () => {
    const { container } = setup();
    const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
    expect(scroller.className).toContain("max-h-[22rem]");
    for (const th of Array.from(container.querySelectorAll("thead th"))) {
      expect(th.className).toContain("sticky");
      expect(th.className).toContain("top-0");
      expect(th.className).toContain("bg-theme-elevated");
      // z-20: above in-modal z-10 siblings, below the dialog chrome.
      expect(th.className).toContain("z-20");
    }
  });

  it("formats metric values per column and em-dashes the missing ones", () => {
    const { container } = setup({
      verdicts: [verdict("m.fits", true, "pass", { median_hfr: 2.1, detected_stars: 100 })],
    });
    const cells = Array.from(container.querySelectorAll("tbody tr td")).map((c) => c.textContent);
    // File, Session, Filter, then HFR / Ecc / FWHM / Stars / RMS.
    expect(cells.slice(3, 8)).toEqual(["2.10", "—", "—", "100", "—"]);
  });

  it("shows an em dash for a null filter", () => {
    const { container } = setup({
      verdicts: [verdict("d.fits", false, "unmeasured", { filter_used: null })],
    });
    expect(container.querySelectorAll("tbody tr td")[2].textContent).toBe("—");
  });
});

describe("WbppQualityPanel sorting", () => {
  const SORTABLE: FrameVerdict[] = [
    verdict("late-small-hfr.fits", true, "pass", {
      timestamp: "2026-07-01T03:00:00",
      median_hfr: 1.5,
    }),
    verdict("early-big-hfr.fits", false, "fail", {
      timestamp: "2026-07-01T01:00:00",
      median_hfr: 2.8,
    }),
    verdict("mid-no-hfr.fits", true, "pass", { timestamp: "2026-07-01T02:00:00" }),
  ];

  it("defaults to chronological order by frame timestamp", () => {
    const { container } = setup({ verdicts: SORTABLE });
    expect(fileColumn(container)).toEqual([
      "early-big-hfr.fits",
      "mid-no-hfr.fits",
      "late-small-hfr.fits",
    ]);
  });

  it("toggles a metric column asc then desc, sinking missing values", () => {
    const { container } = setup({ verdicts: SORTABLE });
    fireEvent.click(headerFor(container, "HFR"));
    expect(fileColumn(container)).toEqual([
      "late-small-hfr.fits", // 1.5
      "early-big-hfr.fits", // 2.8
      "mid-no-hfr.fits", // null sinks
    ]);
    expect(headerFor(container, "HFR").textContent).toContain("▲");

    fireEvent.click(headerFor(container, "HFR"));
    expect(fileColumn(container)).toEqual([
      "early-big-hfr.fits", // 2.8
      "late-small-hfr.fits", // 1.5
      "mid-no-hfr.fits", // null still sinks
    ]);
    expect(headerFor(container, "HFR").textContent).toContain("▼");
  });

  it("sorts by file name when the File header is clicked", () => {
    const { container } = setup({ verdicts: SORTABLE });
    fireEvent.click(headerFor(container, "File"));
    expect(fileColumn(container)).toEqual([
      "early-big-hfr.fits",
      "late-small-hfr.fits",
      "mid-no-hfr.fits",
    ]);
  });

  it("groups Exclude first on Verdict sort, chronological within each group", () => {
    const verdicts: FrameVerdict[] = [
      verdict("keep-early.fits", true, "pass", { timestamp: "2026-07-01T01:00:00" }),
      verdict("drop-late.fits", false, "fail", { timestamp: "2026-07-01T04:00:00" }),
      verdict("keep-late.fits", true, "pass", { timestamp: "2026-07-01T03:00:00" }),
      verdict("drop-early.fits", false, "fail", { timestamp: "2026-07-01T02:00:00" }),
    ];
    const { container } = setup({ verdicts });
    fireEvent.click(headerFor(container, "Verdict"));
    expect(fileColumn(container)).toEqual([
      "drop-early.fits",
      "drop-late.fits",
      "keep-early.fits",
      "keep-late.fits",
    ]);
  });
});

describe("WbppQualityPanel cell banding", () => {
  it("bands metric cells against the session baseline", () => {
    // HFR 2.8 vs median 2.1 / mad 0.37 -> z = 1.89 -> "watch" -> warning.
    // Stars 60 vs median 100 / mad 10 -> flipped z = +4 -> "reject" -> error.
    // HFR 1.5 vs median 2.1 / mad 0.37 -> z = -1.62 -> "better" -> success.
    const { container } = setup({
      verdicts: [
        verdict("watch.fits", false, "fail", {
          timestamp: "2026-07-01T01:00:00",
          median_hfr: 2.8,
        }),
        verdict("reject.fits", false, "fail", {
          timestamp: "2026-07-01T02:00:00",
          detected_stars: 60,
        }),
        verdict("better.fits", true, "pass", {
          timestamp: "2026-07-01T03:00:00",
          median_hfr: 1.5,
        }),
      ],
    });
    const rows = container.querySelectorAll("tbody tr");
    const cell = (row: number, col: number) => rows[row].querySelectorAll("td")[col];
    expect(cell(0, 3).className).toContain("text-theme-warning"); // HFR watch
    expect(cell(1, 6).className).toContain("text-theme-error"); // Stars reject (sign flipped)
    expect(cell(2, 3).className).toContain("text-theme-success"); // HFR better
  });

  it("grades against the rig baseline when config.baseline is rig", () => {
    // HFR 2.8 equals the rig median -> z = 0 -> neutral, where the session
    // baseline (median 2.1) would have banded the same value "watch".
    const detail = sessionDetail({
      rig_baselines: { "TS|Cam|L": { median_hfr: baseline(2.8, 0.37) } },
    } as Partial<SessionDetail>);
    const { container } = setup({
      config: config([], { baseline: "rig" }),
      verdicts: [verdict("r.fits", true, "pass", { median_hfr: 2.8 })],
      sessionDetails: { [DATE]: detail },
    });
    expect(container.querySelectorAll("tbody tr td")[3].className).toContain(
      "text-theme-text-primary",
    );
  });

  it("renders a verdict whose session detail is missing, unbanded", () => {
    const v: FrameVerdict = {
      ...verdict("orphan.fits", true, "pass", { median_hfr: 2.8 }),
      sessionDate: "2099-01-01",
    };
    const { container } = setup({ verdicts: [v], sessionDetails: {} });
    const cells = container.querySelectorAll("tbody tr td");
    expect(cells[3].className).toContain("text-theme-text-primary");
    expect(cells[3].className).not.toContain("text-theme-warning");
    expect(cells[3].textContent).toBe("2.80");
  });
});

describe("WbppQualityPanel threshold-relative coloring", () => {
  // With an active HFR gate at 2.0, cells color against THAT gate, not the
  // baseline MAD bands: above it -> error, at/near it -> warning, clear -> plain.
  const gated = config([{ metric: "hfr", op: "lte", value: 2.0, enabled: true }]);

  it("colors constrained cells relative to the active threshold", () => {
    const { container } = setup({
      config: gated,
      verdicts: [
        verdict("over.fits", false, "fail", { timestamp: "2026-07-01T01:00:00", median_hfr: 2.5 }),
        verdict("at.fits", true, "pass", { timestamp: "2026-07-01T02:00:00", median_hfr: 2.0 }),
        verdict("clear.fits", true, "pass", { timestamp: "2026-07-01T03:00:00", median_hfr: 1.5 }),
      ],
    });
    const rows = container.querySelectorAll("tbody tr");
    const hfrCell = (row: number) => rows[row].querySelectorAll("td")[3];
    expect(hfrCell(0).className).toContain("text-theme-error");
    // Exactly at the threshold the frame PASSES, so it must read watch, not red.
    expect(hfrCell(1).className).toContain("text-theme-warning");
    expect(hfrCell(2).className).toContain("text-theme-text-primary");
  });

  it("keeps baseline banding for metrics without an active constraint", () => {
    // Same rows, no constraints: HFR 2.5 vs baseline 2.1/0.37 -> z 1.08 -> neutral.
    const { container } = setup({
      verdicts: [verdict("over.fits", true, "pass", { median_hfr: 2.5 })],
    });
    expect(container.querySelectorAll("tbody tr td")[3].className).toContain(
      "text-theme-text-primary",
    );
  });
});

describe("WbppQualityPanel scope control", () => {
  const seeded: RawConstraint = {
    metric: "hfr",
    op: "lte",
    value: 2.67,
    enabled: true,
    groupValues: { "TS|Cam|L": 2.67 },
    seed: { groupKey: "TS|Cam|L", filter: "L", date: DATE, n: 20, pooledFilters: [] },
  };

  it("defaults the scope select to Global", () => {
    const { getByLabelText } = setup({ config: config([seeded]) });
    expect((getByLabelText("HFR threshold scope") as HTMLSelectElement).value).toBe("global");
  });

  it("switching to Per-session emits scope, default k, and the polarity op", () => {
    const { getByLabelText, calls } = setup({ config: config([seeded]) });
    fireEvent.change(getByLabelText("HFR threshold scope"), { target: { value: "session" } });
    expect(calls.config[0].constraints[0]).toMatchObject({
      metric: "hfr",
      scope: "session",
      k: 1.5,
      op: "lte",
    });
  });

  it("shows the k input instead of op/value in per-session mode", () => {
    const perSession: RawConstraint = { ...seeded, scope: "session", k: 1.5 };
    const { getByLabelText, queryByLabelText } = setup({ config: config([perSession]) });
    expect((getByLabelText("HFR sigma multiplier") as HTMLInputElement).value).toBe("1.5");
    expect(queryByLabelText("HFR threshold")).toBe(null);
    expect(queryByLabelText("HFR comparison")).toBe(null);
  });

  it("editing a Global value clears the per-filter seeds (manual override)", () => {
    const { getByLabelText, calls } = setup({ config: config([seeded]) });
    fireEvent.input(getByLabelText("HFR threshold"), { target: { value: "2.2" } });
    const emitted = calls.config[0].constraints[0];
    expect(emitted.value).toBe(2.2);
    expect(emitted.groupValues).toBeUndefined();
    expect(emitted.seed).toBeUndefined();
  });

  it("shows the seed provenance badge for an auto-seeded Global chip", () => {
    const { container } = setup({ config: config([seeded]) });
    const text = container.textContent!.replace(/\s+/g, " ");
    expect(text).toContain("HFR seeded from L");
    expect(text).toContain(DATE);
    expect(text).toContain("n=20");
  });

  it("lists pooled-fallback filters on the badge", () => {
    const pooled: RawConstraint = {
      ...seeded,
      seed: { ...seeded.seed!, pooledFilters: ["OIII", "SII"] },
    };
    const { container } = setup({ config: config([pooled]) });
    expect(container.textContent!.replace(/\s+/g, " ")).toContain("pooled: OIII, SII");
  });

  it("renders per-session rows with derived threshold and keep/cut counts", () => {
    const perSession: RawConstraint = { ...seeded, scope: "session", k: 1.5 };
    // Baseline hfr 2.1/0.37 -> 2.1 + 1.5*1.4826*0.37 = 2.92; frames 2.5 keep, 3.5 cut.
    const details = {
      [DATE]: sessionDetail({
        frames: [
          frame("k.fits", { median_hfr: 2.5 }),
          frame("c.fits", { median_hfr: 3.5 }),
        ],
      } as Partial<SessionDetail>),
    };
    const { container } = setup({
      config: config([perSession]),
      sessionDetails: details,
      verdicts: [verdict("k.fits", true, "pass", { median_hfr: 2.5 })],
    });
    const text = container.textContent!.replace(/\s+/g, " ");
    expect(text).toContain("HFR per session");
    expect(text).toContain("07-01 L ≤2.92");
    expect(text).toContain("n=2");
    expect(text).toContain("keep 1 / cut 1");
  });
});

describe("WbppQualityPanel verdict column", () => {
  it("renders a pill per verdict kind with the failure reason beside Exclude", () => {
    const { container } = setup();
    const cells = Array.from(container.querySelectorAll("tbody tr td:last-child"));
    expect(cells[0].textContent!.trim()).toBe("Copy");
    expect(cells[1].textContent).toContain("HFR 2.80 > 2.00");
    expect(cells[1].textContent).toContain("Exclude");
    expect(cells[2].textContent!.trim()).toBe("Unmeasured");
    const pillOf = (cell: Element) => cell.querySelector("span:last-child")!;
    expect(pillOf(cells[0]).className).toContain("text-theme-success");
    expect(pillOf(cells[1]).className).toContain("text-theme-error");
    expect(pillOf(cells[2]).className).toContain("text-theme-warning");
  });

  it("shows every row as Copy with no reasons while the master toggle is off", () => {
    const { container } = setup({ enabled: false });
    const cells = Array.from(container.querySelectorAll("tbody tr td:last-child"));
    expect(cells.map((c) => c.textContent!.trim())).toEqual(["Copy", "Copy", "Copy"]);
    expect(container.textContent).not.toContain("HFR 2.80 > 2.00");
  });
});

describe("WbppQualityPanel help accordion", () => {
  const glyph = (r: ReturnType<typeof setup>) =>
    r.getByLabelText("About the quality filter") as HTMLButtonElement;

  it("renders the help glyph, collapsed by default", () => {
    const r = setup();
    expect(glyph(r)).toBeTruthy();
    expect(glyph(r).getAttribute("aria-expanded")).toBe("false");
    // No overlay, and the inline region is not in the document until expanded.
    expect(r.queryByRole("region")).toBe(null);
  });

  it("stays reachable while the master toggle is off", () => {
    // The glyph must sit outside the inert (pointer-events-none) wrapper.
    const { container, getByLabelText } = setup({ enabled: false });
    const inert = container.querySelector(".pointer-events-none") as HTMLElement;
    expect(inert.contains(getByLabelText("About the quality filter"))).toBe(false);
  });

  it("expands inline on click and shows the guide with its key phrases", () => {
    const r = setup();
    fireEvent.click(glyph(r));
    expect(glyph(r).getAttribute("aria-expanded")).toBe("true");
    const region = r.getByRole("region", { name: "Quality filter guide" });
    // The panel renders in normal flow, not as a floating dialog.
    expect(r.queryByRole("dialog")).toBe(null);
    const text = region.textContent!.replace(/\s+/g, " ");
    expect(text).toContain("Global:");
    expect(text).toContain("Per-session:");
    expect(text).toContain("Choosing k");
    expect(text).toContain("works in reverse");
    expect(text).toContain("pooled");
  });

  it("collapses again on a second glyph click", () => {
    const r = setup();
    fireEvent.click(glyph(r));
    expect(r.queryByRole("region")).not.toBe(null);
    fireEvent.click(glyph(r));
    expect(r.queryByRole("region")).toBe(null);
    expect(glyph(r).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("WbppQualityPanel empty and loading states", () => {
  it("shows the loading line in place of the table while loading", () => {
    const { container } = setup({ loading: true, verdicts: [] });
    expect(container.textContent).toContain("Loading session frames…");
    expect(container.querySelector("table")).toBe(null);
  });

  it("says there are no lights when loaded and empty", () => {
    const { container } = setup({ loading: false, verdicts: [] });
    expect(container.textContent).toContain("No light frames in the selected sessions.");
    expect(container.querySelector("table")).toBe(null);
  });

  it("states the scope: lights only, everything else copied unchanged", () => {
    const { container } = setup();
    expect(container.textContent).toContain(
      "Filters apply to light frames only. All other files are copied unchanged.",
    );
    // The old claim was wrong and must not come back.
    expect(container.textContent).not.toContain("Calibration frames are always copied");
  });
});
