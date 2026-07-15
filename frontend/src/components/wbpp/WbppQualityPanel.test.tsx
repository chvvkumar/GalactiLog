import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import WbppQualityPanel, { type QualityConfig } from "./WbppQualityPanel";
import type { DisplaySettings, FrameRecord, SessionDetail } from "../../api/types";
import type { FrameVerdict } from "../../lib/wbppQualityFilter";

const DEFAULT_CONFIG: QualityConfig = {
  mode: "score",
  scoreThreshold: 60,
  rawConstraints: [],
  baseline: "session",
};

const DATE = "2026-07-01";

function frame(name: string, over: Partial<FrameRecord> = {}): FrameRecord {
  return {
    file_name: name,
    filter_used: "L",
    source_relative: `lights/${name}`,
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
  score: number | null,
  over: Partial<FrameRecord> = {},
): FrameVerdict {
  return { frame: frame(name, over), sessionDate: DATE, score, keep, reason };
}

const VERDICTS: FrameVerdict[] = [
  verdict("a.fits", true, "pass", 82),
  verdict("b.fits", false, "fail", 31),
  verdict("c.fits", false, "unmeasured", null),
];

const TOTALS = { total: 3, copy: 1, fail: 1, unmeasured: 1 };

// A baseline group needs n >= MIN_GROUP (8) and a non-zero mad, else madZ
// returns null and every cell bands to neutral.
function baseline(median: number, mad: number) {
  return { median, mad, n: 20 };
}

// Key format is "telescope|camera|filter"; the frames above use filter "L".
function sessionDetail(over: Partial<SessionDetail> = {}): SessionDetail {
  return {
    equipment: { telescope: "TS", camera: "Cam" },
    rigs: [],
    frames: [],
    session_baselines: {
      "TS|Cam|L": {
        median_hfr: baseline(2.1, 0.37),
        eccentricity: baseline(0.5, 0.05),
        fwhm: baseline(3.0, 0.4),
        detected_stars: baseline(100, 10),
        adu_median: baseline(1000, 100),
      },
    },
    rig_baselines: {},
    ...over,
  } as SessionDetail;
}

const DETAILS: Record<string, SessionDetail> = { [DATE]: sessionDetail() };

// All six metric groups must be present; the override flips one group or field.
function displaySettings(over: Record<string, unknown> = {}): DisplaySettings {
  const group = (fields: Record<string, boolean>) => ({ enabled: true, fields });
  return {
    quality: group({ hfr: true, eccentricity: true, fwhm: true, detected_stars: true }),
    guiding: group({ rms_total: true }),
    adu: group({ median: true }),
    focuser: group({}),
    mount: group({}),
    weather: group({}),
    ...over,
  } as DisplaySettings;
}

function setup(over: Partial<Parameters<typeof WbppQualityPanel>[0]> = {}) {
  const calls: { enabled: boolean[]; config: QualityConfig[] } = { enabled: [], config: [] };
  const result = render(() => (
    <WbppQualityPanel
      enabled={over.enabled ?? false}
      onEnabledChange={(on) => calls.enabled.push(on)}
      config={over.config ?? DEFAULT_CONFIG}
      onConfigChange={(next) => calls.config.push(next)}
      verdicts={over.verdicts ?? VERDICTS}
      totals={over.totals ?? TOTALS}
      loading={over.loading ?? false}
      sessionDetails={over.sessionDetails ?? DETAILS}
      displaySettings={"displaySettings" in over ? over.displaySettings : displaySettings()}
    />
  ));
  return { ...result, calls };
}

function headers(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("thead th")).map((th) => th.textContent!);
}

describe("WbppQualityPanel collapsed", () => {
  it("renders only the checkbox row when disabled", () => {
    const { container, getByLabelText } = setup({ enabled: false });
    expect(container.textContent).toContain("Skip low-quality light frames");
    expect(container.querySelector("select")).toBe(null);
    expect(container.querySelector("table")).toBe(null);
    expect(container.textContent).not.toContain("Baseline");
    expect(container.textContent).not.toContain("Keep ≥");
    expect(container.textContent).not.toContain("Calibration frames are always copied");
    const box = getByLabelText("Skip low-quality light frames") as HTMLInputElement;
    expect(box.checked).toBe(false);
  });

  it("calls onEnabledChange when the checkbox is ticked", () => {
    const { getByLabelText, calls } = setup({ enabled: false });
    fireEvent.click(getByLabelText("Skip low-quality light frames"));
    expect(calls.enabled).toEqual([true]);
  });

  it("calls onEnabledChange with false when unticked", () => {
    const { getByLabelText, calls } = setup({ enabled: true });
    const box = getByLabelText("Skip low-quality light frames") as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(calls.enabled).toEqual([false]);
  });
});

describe("WbppQualityPanel expanded", () => {
  it("renders the mode select with both modes", () => {
    const { getByLabelText } = setup({ enabled: true });
    const select = getByLabelText("Mode") as HTMLSelectElement;
    expect(select.value).toBe("score");
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["score", "raw"]);
    expect(select.textContent).toContain("Composite score");
    expect(select.textContent).toContain("Raw metrics (AND)");
  });

  it("renders the threshold controls and the default-60 hint in score mode", () => {
    const { container, getByLabelText } = setup({ enabled: true });
    expect((getByLabelText("Score threshold") as HTMLInputElement).value).toBe("60");
    const range = getByLabelText("Keep score at or above") as HTMLInputElement;
    expect(range.type).toBe("range");
    expect(range.value).toBe("60");
    expect(container.textContent).toContain(
      "Default 60 matches the green row cutoff on the session table.",
    );
  });

  it("renders the baseline toggles with the active one accented", () => {
    const { getAllByRole } = setup({ enabled: true });
    const labels = getAllByRole("button").map((b) => b.textContent);
    expect(labels).toContain("This session");
    expect(labels).toContain("Rig (catalog)");
    const active = getAllByRole("button").find((b) => b.textContent === "This session")!;
    expect(active.className).toContain("bg-theme-accent/20");
  });

  it("renders the constraint builder in raw mode", () => {
    const { container, getByText } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw", rawConstraints: [{ metric: "median_hfr", value: 3 }] },
    });
    expect(getByText("+ Add constraint")).toBeTruthy();
    expect(getByText("Remove")).toBeTruthy();
    expect(container.textContent).toContain("≤");
  });

  // FIX 3: with no constraints there is nothing to read off the rows, so the
  // guidance must be on screen rather than behind the help icon.
  it("explains constraints inline while there are none", () => {
    const { container, queryByLabelText } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw", rawConstraints: [] },
    });
    expect(container.textContent).toContain(
      "Add one or more constraints. A frame is kept only if every metric it has data for passes.",
    );
    expect(container.textContent).toContain(
      "Frames with none of the constrained metrics are unmeasured.",
    );
    // Inline instead of, not as well as: no duplicate copy behind the icon.
    expect(queryByLabelText("About raw constraints")).toBe(null);
  });

  it("moves the constraint help behind the icon once a constraint exists", () => {
    const { container, getByLabelText } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw", rawConstraints: [{ metric: "median_hfr", value: 3 }] },
    });
    expect(container.textContent).not.toContain("Add one or more constraints.");
    fireEvent.click(getByLabelText("About raw constraints"));
    expect(container.textContent).toContain("Add one or more constraints.");
  });

  it("renders the frame table with a row per verdict", () => {
    const { container } = setup({ enabled: true });
    expect(container.querySelector("table")).not.toBe(null);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    expect(container.textContent).toContain("a.fits");
    expect(container.textContent).toContain("c.fits");
  });

  it("puts the table in a bounded scroll container", () => {
    const { container } = setup({ enabled: true });
    const scroller = container.querySelector(".overflow-y-auto");
    expect(scroller).not.toBe(null);
    expect(scroller!.className).toContain("max-h-[200px]");
    expect(scroller!.querySelector("table")).not.toBe(null);
  });

  it("renders a badge per verdict kind", () => {
    const { container } = setup({ enabled: true });
    const badges = Array.from(container.querySelectorAll("tbody tr td:last-child span"));
    expect(badges.map((b) => b.textContent)).toEqual(["Copy", "Exclude", "Unmeasured"]);
    expect(badges[0].className).toContain("text-theme-success");
    expect(badges[1].className).toContain("text-theme-error");
    expect(badges[2].className).toContain("text-theme-warning");
  });

  it("shows an em dash for a null score and a null filter", () => {
    const { container } = setup({
      enabled: true,
      verdicts: [verdict("d.fits", false, "unmeasured", null, { filter_used: null })],
    });
    const cells = container.querySelectorAll("tbody tr td");
    expect(cells[2].textContent).toBe("—");
    // Score sits after the six metric columns, before the verdict badge.
    expect(cells[cells.length - 2].textContent).toBe("—");
  });

  it("shows the loading state only while loading", () => {
    expect(setup({ enabled: true, loading: true }).container.textContent).toContain(
      "Loading session frames…",
    );
    expect(setup({ enabled: true, loading: false }).container.textContent).not.toContain(
      "Loading session frames…",
    );
  });
});

describe("WbppQualityPanel metric columns", () => {
  it("renders every visible metric column header", () => {
    const { container } = setup({ enabled: true });
    expect(headers(container)).toEqual([
      "File", "Session", "Filter", "HFR", "Ecc", "FWHM", "Stars", "RMS", "ADU", "Score", "Verdict",
    ]);
  });

  it("formats metric values per column and em-dashes the missing ones", () => {
    const { container } = setup({
      enabled: true,
      verdicts: [verdict("m.fits", true, "pass", 70, { median_hfr: 2.1, detected_stars: 100 })],
    });
    const cells = Array.from(container.querySelectorAll("tbody tr td")).map((c) => c.textContent);
    // File, Session, Filter, then HFR / Ecc / FWHM / Stars / RMS / ADU.
    expect(cells.slice(3, 9)).toEqual(["2.10", "—", "—", "100", "—", "—"]);
  });

  it("bands a metric cell against the baseline in score mode", () => {
    // HFR 2.8 vs median 2.1 / mad 0.37 -> z = 1.89 -> "watch" -> warning.
    // Stars 60 vs median 100 / mad 10 -> flipped z = +4 -> "reject" -> error.
    // HFR 1.5 vs median 2.1 / mad 0.37 -> z = -1.62 -> "better" -> success.
    const { container } = setup({
      enabled: true,
      verdicts: [
        verdict("watch.fits", false, "fail", 40, { median_hfr: 2.8 }),
        verdict("reject.fits", false, "fail", 10, { detected_stars: 60 }),
        verdict("better.fits", true, "pass", 90, { median_hfr: 1.5 }),
      ],
    });
    const rows = container.querySelectorAll("tbody tr");
    const cell = (row: number, col: number) => rows[row].querySelectorAll("td")[col];
    expect(cell(0, 3).className).toContain("text-theme-warning"); // HFR watch
    expect(cell(1, 6).className).toContain("text-theme-error"); // Stars reject
    expect(cell(2, 3).className).toContain("text-theme-success"); // HFR better
  });

  it("does not band cells in raw mode", () => {
    const { container } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw" },
      verdicts: [verdict("watch.fits", false, "fail", 40, { median_hfr: 2.8 })],
    });
    const hfr = container.querySelectorAll("tbody tr td")[3];
    expect(hfr.className).toContain("text-theme-text-primary");
    expect(hfr.className).not.toContain("text-theme-warning");
    expect(hfr.textContent).toBe("2.80");
  });

  it("hides a column switched off in displaySettings", () => {
    const { container } = setup({
      enabled: true,
      displaySettings: displaySettings({
        quality: {
          enabled: true,
          fields: { hfr: false, eccentricity: true, fwhm: true, detected_stars: true },
        },
      }),
    });
    const h = headers(container);
    expect(h).not.toContain("HFR");
    expect(h).toContain("Ecc");
    expect(h).toContain("ADU");
  });

  it("hides every column in a group switched off in displaySettings", () => {
    const { container } = setup({
      enabled: true,
      displaySettings: displaySettings({ adu: { enabled: false, fields: { median: true } } }),
    });
    const h = headers(container);
    expect(h).not.toContain("ADU");
    expect(h).toContain("HFR");
  });

  it("falls back to quality + guiding columns when displaySettings is undefined", () => {
    // isFieldVisible's undefined branch: quality and guiding on, adu off.
    const { container } = setup({ enabled: true, displaySettings: undefined });
    const h = headers(container);
    expect(h).toContain("HFR");
    expect(h).toContain("RMS");
    expect(h).not.toContain("ADU");
  });
});

describe("WbppQualityPanel sparse session cache", () => {
  it("renders a verdict whose session is missing without throwing", () => {
    const v: FrameVerdict = {
      ...verdict("orphan.fits", true, "pass", 70, { median_hfr: 2.8 }),
      sessionDate: "2099-01-01",
    };
    const { container } = setup({ enabled: true, verdicts: [v], sessionDetails: {} });
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    const cells = container.querySelectorAll("tbody tr td");
    // No baseline to grade against, so the cell is unbanded rather than colored.
    expect(cells[3].className).toContain("text-theme-text-primary");
    expect(cells[3].className).not.toContain("text-theme-warning");
    // Values the frame carries still render; genuinely null metrics em-dash.
    expect(cells[3].textContent).toBe("2.80");
    expect(cells[4].textContent).toBe("—");
    expect(container.textContent).toContain("orphan.fits");
  });

  it("renders an em dash for every metric when the session is missing and the frame is bare", () => {
    const v: FrameVerdict = {
      ...verdict("bare.fits", false, "unmeasured", null),
      sessionDate: "2099-01-01",
    };
    const { container } = setup({ enabled: true, verdicts: [v], sessionDetails: {} });
    const cells = Array.from(container.querySelectorAll("tbody tr td")).map((c) => c.textContent);
    expect(cells.slice(3, 9)).toEqual(["—", "—", "—", "—", "—", "—"]);
  });

  it("leaves a cell unbanded when the baseline group is too sparse", () => {
    // n < MIN_GROUP (8) -> madZ returns null -> neutral.
    const detail = sessionDetail({
      session_baselines: { "TS|Cam|L": { median_hfr: { median: 2.1, mad: 0.37, n: 3 } } },
    } as Partial<SessionDetail>);
    const { container } = setup({
      enabled: true,
      verdicts: [verdict("sparse.fits", false, "fail", 40, { median_hfr: 2.8 })],
      sessionDetails: { [DATE]: detail },
    });
    expect(container.querySelectorAll("tbody tr td")[3].className).toContain(
      "text-theme-text-primary",
    );
  });

  it("grades against the rig baseline when the baseline mode is rig", () => {
    // HFR 2.8 equals the rig median -> z = 0 -> neutral, where the session
    // baseline (median 2.1) would have banded the same value "watch".
    const detail = sessionDetail({
      rig_baselines: { "TS|Cam|L": { median_hfr: baseline(2.8, 0.37) } },
    } as Partial<SessionDetail>);
    const { container } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, baseline: "rig" },
      verdicts: [verdict("r.fits", true, "pass", 60, { median_hfr: 2.8 })],
      sessionDetails: { [DATE]: detail },
    });
    expect(container.querySelectorAll("tbody tr td")[3].className).toContain(
      "text-theme-text-primary",
    );
  });
});

describe("WbppQualityPanel live count line", () => {
  it("reflects props.totals with exclude = fail + unmeasured", () => {
    const { container } = setup({
      enabled: true,
      totals: { total: 40, copy: 31, fail: 7, unmeasured: 2 },
    });
    expect(container.textContent!.replace(/\s+/g, " ")).toContain(
      "Skips 9 of 40 lights in the selected sessions (7 below threshold, 2 unmeasured). " +
        "Calibration frames are always copied.",
    );
  });

  it("reads zero when nothing is excluded", () => {
    const { container } = setup({
      enabled: true,
      totals: { total: 5, copy: 5, fail: 0, unmeasured: 0 },
    });
    expect(container.textContent!.replace(/\s+/g, " ")).toContain(
      "Skips 0 of 5 lights in the selected sessions (0 below threshold, 0 unmeasured).",
    );
  });

  // The panel counts every light in the selected sessions; the footer counts
  // only what lies under the selected folder levels. Both are right for their
  // own scope, so the panel's figures have to name theirs or the two totals
  // read as a contradiction.
  it("names the domain its counts cover, next to the counts", () => {
    const { container } = setup({
      enabled: true,
      totals: { total: 30, copy: 25, fail: 3, unmeasured: 2 },
    });
    const text = container.textContent!.replace(/\s+/g, " ");
    // The scope sits on the counted noun, not in a sentence after it.
    expect(text).toContain("of 30 lights in the selected sessions");
    expect(text).not.toContain("of 30 lights (");
  });
});

describe("WbppQualityPanel is controlled", () => {
  it("emits the full config when the threshold changes", () => {
    const { getByLabelText, calls } = setup({ enabled: true });
    fireEvent.input(getByLabelText("Score threshold"), { target: { value: "75" } });
    expect(calls.config.length).toBe(1);
    expect(calls.config[0]).toEqual({
      mode: "score",
      scoreThreshold: 75,
      rawConstraints: [],
      baseline: "session",
    });
  });

  it("emits the full config when the mode changes", () => {
    const { getByLabelText, calls } = setup({ enabled: true });
    fireEvent.change(getByLabelText("Mode"), { target: { value: "raw" } });
    expect(calls.config[0]).toEqual({ ...DEFAULT_CONFIG, mode: "raw" });
  });

  it("emits the full config when the baseline changes", () => {
    const { getAllByRole, calls } = setup({ enabled: true });
    fireEvent.click(getAllByRole("button").find((b) => b.textContent === "Rig (catalog)")!);
    expect(calls.config[0]).toEqual({ ...DEFAULT_CONFIG, baseline: "rig" });
  });

  it("adds the first unused metric at value 0", () => {
    const { getByText, calls } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw", rawConstraints: [{ metric: "median_hfr", value: 3 }] },
    });
    fireEvent.click(getByText("+ Add constraint"));
    expect(calls.config[0].rawConstraints).toEqual([
      { metric: "median_hfr", value: 3 },
      { metric: "fwhm", value: 0 },
    ]);
  });

  it("removes the clicked constraint", () => {
    const { getAllByText, calls } = setup({
      enabled: true,
      config: {
        ...DEFAULT_CONFIG,
        mode: "raw",
        rawConstraints: [
          { metric: "median_hfr", value: 3 },
          { metric: "fwhm", value: 4 },
        ],
      },
    });
    fireEvent.click(getAllByText("Remove")[0]);
    expect(calls.config[0].rawConstraints).toEqual([{ metric: "fwhm", value: 4 }]);
  });

  it("disables + Add constraint once every metric is used", () => {
    const { getByText } = setup({
      enabled: true,
      config: {
        ...DEFAULT_CONFIG,
        mode: "raw",
        rawConstraints: [
          { metric: "median_hfr", value: 1 },
          { metric: "fwhm", value: 1 },
          { metric: "eccentricity", value: 1 },
          { metric: "detected_stars", value: 1 },
          { metric: "guiding_rms_arcsec", value: 1 },
          { metric: "adu_median", value: 1 },
        ],
      },
    });
    expect((getByText("+ Add constraint") as HTMLButtonElement).disabled).toBe(true);
  });

  it("emits the constraint value as a number", () => {
    const { getByLabelText, calls } = setup({
      enabled: true,
      config: { ...DEFAULT_CONFIG, mode: "raw", rawConstraints: [{ metric: "median_hfr", value: 3 }] },
    });
    fireEvent.input(getByLabelText("HFR value"), { target: { value: "2.5" } });
    expect(calls.config[0].rawConstraints).toEqual([{ metric: "median_hfr", value: 2.5 }]);
  });
});
