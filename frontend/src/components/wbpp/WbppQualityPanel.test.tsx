import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";

// FilePreviewModal (opened from the file column) reads the preview resolution
// from the settings context; stub it so tests need no provider tree.
vi.mock("../SettingsProvider", () => ({
  useSettingsContext: () => ({
    settings: () => ({ general: { preview_resolution: 2400 } }),
  }),
}));

import WbppQualityPanel from "./WbppQualityPanel";
import {
  emptyConstraintFor,
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
    image_id: `id-${name}`,
    file_path: `/data/lights/${name}`,
    thumbnail_url: null,
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
  failures: FrameVerdict["failures"] | null = null,
): FrameVerdict {
  return {
    frame: frame(name, over),
    sessionDate: DATE,
    keep,
    reason,
    failedBy,
    // Unless a test hands explicit failures, mirror the production invariant:
    // failedBy is the first failure's sentence.
    failures: failures ?? (failedBy ? [{ metric: "hfr", text: failedBy }] : []),
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
// One frame in the detail so the cell coloring has a train to resolve.
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
      isIncluded={over.isIncluded}
      onToggleInclude={over.onToggleInclude}
      showFullPath={over.showFullPath}
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
  // File sits last-but-one, just before Session.
  return Array.from(container.querySelectorAll("tbody tr td:nth-last-child(2)")).map(
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

  it("appends an empty (valueless) constraint when a ghost chip is clicked", () => {
    const { container, calls } = setup();
    fireEvent.click(ghostChip(container, "HFR"));
    expect(calls.config.length).toBe(1);
    // A new chip carries no number: it must not exclude anything until the
    // user supplies a value.
    const expected = emptyConstraintFor("hfr");
    expect(calls.config[0]).toEqual({ ...DEFAULT_CONFIG, constraints: [expected] });
    expect(calls.config[0].constraints[0].enabled).toBe(true);
    expect(calls.config[0].constraints[0].value).toBeNull();
    expect(calls.config[0].constraints[0].op).toBe("lte");
  });

  it("appends to the existing constraints rather than replacing them", () => {
    const held: RawConstraint = { metric: "ecc", op: "lte", value: 0.55, enabled: true };
    const { container, calls } = setup({ config: config([held]) });
    fireEvent.click(ghostChip(container, "Stars"));
    expect(calls.config[0].constraints).toEqual([held, emptyConstraintFor("stars")]);
  });

  it("clearing the threshold input reverts the constraint to valueless", () => {
    const { getByLabelText, calls } = setup({
      config: config([{ metric: "hfr", op: "lte", value: 1.65, enabled: true }]),
    });
    fireEvent.input(getByLabelText("HFR threshold"), { target: { value: "" } });
    expect(calls.config[0].constraints).toEqual([
      { metric: "hfr", op: "lte", value: null, enabled: true },
    ]);
  });

  it("offers ecc presets on the active Ecc chip and applies one on click", () => {
    const { getByTitle, calls } = setup({
      config: config([{ metric: "ecc", op: "lte", value: null, enabled: true }]),
    });
    fireEvent.click(getByTitle("Balanced: ecc ≤ 0.65"));
    expect(calls.config[0].constraints).toEqual([
      { metric: "ecc", op: "lte", value: 0.65, enabled: true },
    ]);
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

  it("does not render the tally when the host provides isIncluded (its own counts line owns the numbers)", () => {
    const { container } = setup({
      isIncluded: () => true,
      onToggleInclude: () => {},
    });
    expect(pill(container)).toBe(null);
    expect(container.textContent).not.toContain("kept");
    expect(container.textContent).not.toContain("skipped");
  });

  it("keeps the tally when isIncluded is absent (the WBPP export path)", () => {
    const { container } = setup();
    const p = pill(container);
    expect(p).not.toBe(null);
    expect(p.textContent).toContain("kept");
    expect(p.textContent).toContain("skipped");
  });
});

describe("WbppQualityPanel baseline control", () => {
  it("accents the active baseline and emits the other on click", () => {
    const { getByText, calls } = setup();
    expect(getByText("This session").className).toContain("bg-theme-accent/20");
    expect(getByText("Overall").className).not.toContain("bg-theme-accent/20");
    fireEvent.click(getByText("Overall"));
    expect(calls.config).toEqual([{ ...DEFAULT_CONFIG, baseline: "rig" }]);
  });
});

describe("WbppQualityPanel table columns", () => {
  it("renders the fixed column set with no Score column", () => {
    const { container } = setup();
    expect(headers(container)).toEqual([
      "Verdict", "Filter", "HFR", "Ecc", "FWHM", "Stars", "RMS", "File", "Session",
    ]);
  });

  it("pins the header with a solid background so rows cannot bleed through", () => {
    const { container } = setup();
    const scroller = container.querySelector(".overflow-y-auto") as HTMLElement;
    expect(scroller.className).toContain("max-h-[36rem]");
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
    // Verdict, Filter, then HFR / Ecc / FWHM / Stars / RMS.
    expect(cells.slice(2, 7)).toEqual(["2.10", "—", "—", "100", "—"]);
  });

  it("shows an em dash for a null filter", () => {
    const { container } = setup({
      verdicts: [verdict("d.fits", false, "unmeasured", { filter_used: null })],
    });
    expect(container.querySelectorAll("tbody tr td")[1].textContent).toBe("—");
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
    expect(cell(0, 2).className).toContain("text-theme-warning"); // HFR watch
    expect(cell(1, 5).className).toContain("text-theme-error"); // Stars reject (sign flipped)
    expect(cell(2, 2).className).toContain("text-theme-success"); // HFR better
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
    expect(container.querySelectorAll("tbody tr td")[2].className).toContain(
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
    expect(cells[2].className).toContain("text-theme-text-primary");
    expect(cells[2].className).not.toContain("text-theme-warning");
    expect(cells[2].textContent).toBe("2.80");
  });
});

describe("WbppQualityPanel verdict column", () => {
  it("renders an icon per verdict kind with the failure detail in the tooltip", () => {
    const { container } = setup();
    const icons = Array.from(
      container.querySelectorAll("tbody tr td:first-child span"),
    ) as HTMLElement[];
    expect(icons[0].textContent).toBe("●");
    expect(icons[0].title).toBe("Copy");
    expect(icons[0].className).toContain("text-theme-success");
    expect(icons[1].textContent).toBe("✕");
    expect(icons[1].title).toContain("Exclude");
    expect(icons[1].title).toContain("HFR 2.80 > 2.00");
    expect(icons[1].className).toContain("text-theme-error");
    expect(icons[2].textContent).toBe("◐");
    expect(icons[2].title).toContain("Unmeasured");
    expect(icons[2].className).toContain("text-theme-warning");
  });

  it("marks the failing metric cell with a glyph, keeping the slot on passing cells", () => {
    const { container } = setup({
      verdicts: [
        verdict("pass.fits", true, "pass", {
          timestamp: "2026-07-01T01:00:00",
          median_hfr: 1.5,
        }),
        verdict(
          "fail.fits",
          false,
          "fail",
          { timestamp: "2026-07-01T02:00:00", median_hfr: 2.8 },
          "HFR 2.80 > 2.00",
        ),
      ],
    });
    const rows = container.querySelectorAll("tbody tr");
    const hfrCell = (row: number) => rows[row].querySelectorAll("td")[2];
    expect(hfrCell(1).className).toContain("text-theme-error");
    expect(hfrCell(1).title).toBe("HFR 2.80 > 2.00");
    expect(hfrCell(1).querySelector("span")!.textContent).toBe("✕");
    // Passing cell keeps an EMPTY slot of the same width so digits align.
    expect(hfrCell(0).querySelector("span")!.textContent).toBe("");
    expect(hfrCell(0).querySelector("span")!.className).toContain("w-3");
    expect(hfrCell(1).querySelector("span")!.className).toContain("w-3");
  });

  it("shows every row as Copy with no failure marks while the master toggle is off", () => {
    const { container } = setup({ enabled: false });
    const icons = Array.from(
      container.querySelectorAll("tbody tr td:first-child span"),
    ) as HTMLElement[];
    expect(icons.map((i) => i.textContent)).toEqual(["●", "●", "●"]);
    expect(icons.map((i) => i.title)).toEqual(["Copy", "Copy", "Copy"]);
    expect(container.textContent).not.toContain("HFR 2.80 > 2.00");
    // No metric cell carries the failure mark or tooltip while disabled.
    for (const td of Array.from(container.querySelectorAll("tbody td[title]"))) {
      expect((td as HTMLElement).title).not.toContain("HFR");
    }
  });
});

describe("WbppQualityPanel file preview", () => {
  const dialog = () => document.querySelector('[role="dialog"]') as HTMLElement | null;

  function openRow(container: HTMLElement, name: string) {
    const link = Array.from(container.querySelectorAll("tbody td button")).find(
      (b) => b.textContent === name,
    ) as HTMLButtonElement;
    expect(link).toBeTruthy();
    fireEvent.click(link);
    return dialog()!;
  }

  it("renders the file name as a preview link", () => {
    const { container } = setup();
    const cells = container.querySelectorAll("tbody tr td:nth-last-child(2)");
    for (const td of Array.from(cells)) {
      expect(td.querySelector("button")).toBeTruthy();
    }
    expect(fileColumn(container)).toEqual(["a.fits", "b.fits", "c.fits"]);
  });

  it("opens the preview modal with the row's verdict and metric strip", () => {
    const { container } = setup();
    const d = openRow(container, "b.fits");
    expect(d.textContent).toContain("/data/lights/b.fits");
    // Verdict pill carries the failure detail in its tooltip.
    expect(d.textContent).toContain("Exclude");
    const verdictPill = Array.from(d.querySelectorAll("span[title]")).find((s) =>
      (s as HTMLElement).title.startsWith("Exclude"),
    ) as HTMLElement;
    expect(verdictPill.title).toContain("HFR 2.80 > 2.00");
    // Metric, filter and session pills mirror the table row.
    expect(d.textContent).toContain("Filter");
    expect(d.textContent).toContain("HFR");
    expect(d.textContent).toContain(DATE);
    fireEvent.click(d.querySelector('button[class*="absolute"]')!);
    expect(dialog()).toBe(null);
  });

  it("navigates all rows in the current sort order from the clicked index", () => {
    const { container } = setup();
    const d = openRow(container, "b.fits");
    // Chronological default order: a, b, c -> b.fits is 2 of 3.
    expect(d.textContent).toContain("2 / 3");
  });

  it("shows Copy on every row's preview while the master toggle is off", () => {
    const { container } = setup({ enabled: false });
    const d = openRow(container, "b.fits");
    expect(d.textContent).toContain("Copy");
    expect(d.textContent).not.toContain("Exclude");
  });
});

describe("WbppQualityPanel copy column and full path", () => {
  const rowCheckboxes = (container: HTMLElement): HTMLInputElement[] =>
    Array.from(container.querySelectorAll('tbody input[type="checkbox"]'));

  it("renders a leading Copy checkbox column when both include props are provided", () => {
    const toggled: FrameVerdict[] = [];
    const { container } = setup({
      isIncluded: (v) => v.frame.file_name === "b.fits",
      onToggleInclude: (v) => toggled.push(v),
    });
    expect(headers(container)).toEqual([
      "Copy", "Verdict", "Filter", "HFR", "Ecc", "FWHM", "Stars", "RMS", "File", "Session",
    ]);
    const boxes = rowCheckboxes(container);
    expect(boxes.length).toBe(3);
    // Checked state mirrors isIncluded per verdict (chronological order a, b, c).
    expect(boxes.map((b) => b.checked)).toEqual([false, true, false]);
    // Each checkbox is labelled by its file name.
    expect(boxes.map((b) => b.getAttribute("aria-label"))).toEqual([
      "a.fits", "b.fits", "c.fits",
    ]);
    fireEvent.click(boxes[2]);
    expect(toggled.length).toBe(1);
    expect(toggled[0].frame.file_name).toBe("c.fits");
  });

  it("shows the full path under the file name when showFullPath is set", () => {
    const { container } = setup({ showFullPath: true });
    const fileCells = Array.from(
      container.querySelectorAll("tbody tr td:nth-last-child(2)"),
    ) as HTMLElement[];
    expect(fileCells[0].textContent).toContain("/data/lights/a.fits");
    const pathLine = fileCells[0].querySelector(".text-theme-text-tertiary") as HTMLElement;
    expect(pathLine).toBeTruthy();
    expect(pathLine.className).toContain("truncate");
  });

  it("renders exactly as before when none of the new props are given", () => {
    const { container } = setup();
    expect(rowCheckboxes(container).length).toBe(0);
    expect(headers(container)).toEqual([
      "Verdict", "Filter", "HFR", "Ecc", "FWHM", "Stars", "RMS", "File", "Session",
    ]);
    expect(container.textContent).not.toContain("/data/lights/a.fits");
    // No skipped-row highlight without the include callback.
    for (const tr of Array.from(container.querySelectorAll("tbody tr"))) {
      expect(tr.className).not.toContain("bg-theme-error/10");
      expect(tr.className).not.toContain("opacity-60");
    }
  });

  it("ties the tint to the fail verdict and the dim to non-inclusion, independently", () => {
    const [included, setIncluded] = createSignal(new Set(["a.fits", "c.fits"]));
    const { container } = setup({
      isIncluded: (v) => included().has(v.frame.file_name),
      onToggleInclude: () => {},
    });
    const tinted = () =>
      Array.from(container.querySelectorAll("tbody tr")).map((tr) =>
        tr.className.includes("bg-theme-error/10"),
      );
    const dimmed = () =>
      Array.from(container.querySelectorAll("tbody tr")).map((tr) =>
        tr.className.includes("opacity-60"),
      );
    // Chronological order a (pass), b (fail), c (unmeasured); b excluded.
    // Tint follows the verdict: only the fail row.
    expect(tinted()).toEqual([false, true, false]);
    // Dim follows inclusion: only the excluded row.
    expect(dimmed()).toEqual([false, true, false]);
    setIncluded(new Set(["b.fits"]));
    // b is now fail plus included: still tinted, no longer dimmed.
    // a and c are pass/unmeasured plus non-included: dimmed, never tinted.
    expect(tinted()).toEqual([false, true, false]);
    expect(dimmed()).toEqual([true, false, true]);
  });

  it("no longer hosts the quality help popover (it lives in the export modal)", () => {
    const { container } = setup();
    expect(
      container.querySelector('button[aria-label="About quality filters"]'),
    ).toBe(null);
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
