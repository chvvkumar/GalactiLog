import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";

// The vi.mock factories must be hoisted above the component import, so the
// component's module-level imports resolve to these stubs.
const getMock = vi.fn((_path: string, _opts?: any) =>
  Promise.resolve({ data: null, response: { ok: true } }),
);

vi.mock("../api/generated/client", () => ({
  apiClient: {
    GET: (path: string, opts: any) => getMock(path, opts),
    POST: vi.fn(),
  },
}));

let general: Record<string, unknown> = {};
const saveGeneralMock = vi.fn((_g: Record<string, unknown>) => Promise.resolve({}));

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    settings: () => ({ general }),
    displaySettings: () => undefined,
    contentWidth: () => "full",
    saveGeneral: (g: Record<string, unknown>) => saveGeneralMock(g),
  }),
}));

vi.mock("./Toast", () => ({ showToast: vi.fn() }));

// Browser-native move support: the modal reads isFsAccessSupported at render
// time, calls pickDirectory on click, then scanForNames/moveMatches. All four
// are stubbed so the tests drive the flow without real handles.
let fsSupported = true;
const pickDirectoryMock = vi.fn((_mode: string, _id: string) => Promise.resolve({} as any));

vi.mock("../lib/wbppBrowserCopy", () => {
  class CopyCancelledError extends Error {
    constructor() {
      super("cancelled");
      this.name = "CopyCancelledError";
    }
  }
  return {
    isFsAccessSupported: () => fsSupported,
    pickDirectory: (mode: string, id: string) => pickDirectoryMock(mode, id),
    CopyCancelledError,
  };
});

const scanForNamesMock = vi.fn(
  (_root: any, _names: string[]): Promise<any> =>
    Promise.resolve({ root: {}, matches: [], missing: [], collisions: [] }),
);
const moveMatchesMock = vi.fn(
  (
    _scan: any,
    _onProgress: (done: number, total: number) => void,
    _signal: AbortSignal,
  ): Promise<any> => Promise.resolve({ moved: 0, failed: [] }),
);

vi.mock("../lib/frameListBrowserMove", () => ({
  scanForNames: (root: any, names: string[]) => scanForNamesMock(root, names),
  moveMatches: (scan: any, onProgress: any, signal: AbortSignal) =>
    moveMatchesMock(scan, onProgress, signal),
}));

import FrameListModal from "./FrameListModal";
import { CopyCancelledError } from "../lib/wbppBrowserCopy";
import { showToast } from "./Toast";
import type { SessionDetail } from "../api/types";

// Dialog renders through a Portal, so every query runs against document.body.
const bodyText = (): string => document.body.textContent ?? "";

const buttons = (): HTMLButtonElement[] =>
  Array.from(document.body.querySelectorAll("button"));

const DATE = "2026-07-01";
const QUALITY_KEY = "galactilog.wbppQuality.v1.default";

/**
 * Five lights judged by a persisted HFR <= 2 gate: two pass (1.0, 1.2), two
 * fail (3.0, 3.5), one carries no metrics at all and lands in "unmeasured".
 */
function cacheDetail(): SessionDetail {
  const frame = (name: string, hfr: number | null) => ({
    file_name: name,
    file_path: `Z:\\Astro\\M31\\${DATE}\\Ha\\${name}`,
    filter_used: "Ha",
    source_relative: `M31/${DATE}/Ha/${name}`,
    file_size: 100,
    median_hfr: hfr,
    eccentricity: null,
    fwhm: null,
    detected_stars: null,
    guiding_rms_arcsec: null,
    adu_median: null,
    rig: null,
  });
  return {
    equipment: { telescope: "TS", camera: "Cam" },
    rigs: [],
    frames: [
      frame("a_pass.fits", 1.0),
      frame("b_fail.fits", 3.0),
      frame("c_unmeasured.fits", null),
      frame("d_fail.fits", 3.5),
      frame("e_pass.fits", 1.2),
    ],
    session_baselines: { "TS|Cam|Ha": { median_hfr: { median: 2.0, mad: 0.5, n: 20 } } },
    rig_baselines: {},
  } as unknown as SessionDetail;
}

function renderModal(cache: Record<string, SessionDetail> = { [DATE]: cacheDetail() }) {
  return render(() => (
    <FrameListModal
      targetId="t-1"
      targetName="M31"
      selectedDates={[DATE]}
      sessionCache={cache}
      onClose={() => {}}
    />
  ));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

const modeButton = (label: "Good" | "Bad"): HTMLButtonElement => {
  const b = buttons().find((el) => el.textContent?.trim() === label);
  if (!b) throw new Error(`No ${label} mode button found. Body: ${bodyText()}`);
  return b;
};

const rowCheckbox = (fileName: string): HTMLInputElement => {
  const el = document.body.querySelector(
    `input[type="checkbox"][aria-label="${fileName}"]`,
  ) as HTMLInputElement | null;
  if (!el) throw new Error(`No row checkbox for ${fileName}. Body: ${bodyText()}`);
  return el;
};

const formatSelect = (): HTMLSelectElement =>
  document.body.querySelector('select[aria-label="Format"]') as HTMLSelectElement;

const copyButton = (): HTMLButtonElement => {
  const b = buttons().find((el) =>
    /^Copy (\d[\d,]* names?|script \(\d[\d,]* names?\))$/.test(el.textContent?.trim() ?? ""),
  );
  if (!b) throw new Error(`No copy button found. Body: ${bodyText()}`);
  return b;
};

let writeTextMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  document.body.innerHTML = "";
  localStorage.clear();
  // The shared per-rig quality store: an armed HFR <= 2 gate, filter on. The
  // modal must hydrate from the SAME key the WBPP export modal writes.
  localStorage.setItem(
    QUALITY_KEY,
    JSON.stringify({
      enabled: true,
      config: {
        baseline: "session",
        constraints: [{ metric: "hfr", op: "lte", value: 2, enabled: true }],
      },
    }),
  );
  general = {
    frame_list_base_folder: null,
    wbpp_default_os: null,
    wbpp_library_root: "Z:\\Astro",
  };
  writeTextMock = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: writeTextMock },
    configurable: true,
  });
  getMock.mockClear();
  saveGeneralMock.mockClear();
  fsSupported = true;
  pickDirectoryMock.mockClear();
  pickDirectoryMock.mockImplementation((_mode: string, _id: string) => Promise.resolve({} as any));
  scanForNamesMock.mockClear();
  scanForNamesMock.mockImplementation(() =>
    Promise.resolve({ root: {}, matches: [], missing: [], collisions: [] }),
  );
  moveMatchesMock.mockClear();
  moveMatchesMock.mockImplementation(() => Promise.resolve({ moved: 0, failed: [] }));
  (showToast as ReturnType<typeof vi.fn>).mockClear();
});

describe("FrameListModal selection", () => {
  it("defaults to bad mode: count equals the fail count and unmeasured stays out", () => {
    renderModal();
    // 2 fails of 5 frames; the unmeasured frame was never rejected by a gate,
    // so it must not appear in the bad list.
    expect(bodyText()).toContain("2 of 5 frames selected");
    expect(rowCheckbox("b_fail.fits").checked).toBe(true);
    expect(rowCheckbox("d_fail.fits").checked).toBe(true);
    expect(rowCheckbox("c_unmeasured.fits").checked).toBe(false);
    expect(rowCheckbox("a_pass.fits").checked).toBe(false);
  });

  it("good mode includes unmeasured until the include-unmeasured box is unchecked", async () => {
    renderModal();
    fireEvent.click(modeButton("Good"));
    await flush();
    // 2 passes + 1 unmeasured (include unmeasured defaults ON).
    expect(bodyText()).toContain("3 of 5 frames selected");
    expect(rowCheckbox("c_unmeasured.fits").checked).toBe(true);

    const include = document.body.querySelector(
      'input[aria-label="Include unmeasured"]',
    ) as HTMLInputElement;
    expect(include).not.toBe(null);
    fireEvent.click(include);
    await flush();

    expect(bodyText()).toContain("2 of 5 frames selected");
    expect(rowCheckbox("c_unmeasured.fits").checked).toBe(false);
  });

  it("a row checkbox flips a fail frame out of the bad list and the count decrements", async () => {
    renderModal();
    expect(bodyText()).toContain("2 of 5 frames selected");
    fireEvent.click(rowCheckbox("b_fail.fits"));
    await flush();
    expect(bodyText()).toContain("1 of 5 frames selected");
    expect(rowCheckbox("b_fail.fits").checked).toBe(false);
  });

  it("changing a chip value resets overrides so the count returns to the computed set", async () => {
    renderModal();
    fireEvent.click(rowCheckbox("b_fail.fits"));
    await flush();
    expect(bodyText()).toContain("1 of 5 frames selected");

    // Loosen the gate to 2.5: b_fail (3.0) and d_fail (3.5) still fail, so the
    // computed set is unchanged -- only the override must be discarded.
    const input = document.body.querySelector(
      'input[aria-label="HFR threshold"]',
    ) as HTMLInputElement;
    fireEvent.input(input, { target: { value: "2.5" } });
    await flush();

    expect(bodyText()).toContain("2 of 5 frames selected");
    expect(rowCheckbox("b_fail.fits").checked).toBe(true);
  });
});

describe("FrameListModal copy", () => {
  it("writes the newline name list to the clipboard in names format", async () => {
    renderModal();
    fireEvent.change(formatSelect(), { target: { value: "names" } });
    await flush();
    fireEvent.click(copyButton());
    await flush();

    expect(writeTextMock).toHaveBeenCalledTimes(1);
    expect(writeTextMock).toHaveBeenCalledWith("b_fail.fits\nd_fail.fits");
  });

  it("disables Copy in script format while the base folder is blank", async () => {
    // No stored base folder AND no library root, so the input seeds blank.
    general = { frame_list_base_folder: null, wbpp_default_os: null, wbpp_library_root: null };
    renderModal();
    fireEvent.change(formatSelect(), { target: { value: "script" } });
    await flush();

    const btn = copyButton();
    expect(btn.textContent?.trim()).toBe("Copy script (2 names)");
    expect(btn.disabled).toBe(true);

    const base = document.body.querySelector(
      'input[aria-label="Base folder"]',
    ) as HTMLInputElement;
    expect(base).not.toBe(null);
    fireEvent.input(base, { target: { value: "D:\\Staging\\M31" } });
    await flush();
    expect(copyButton().disabled).toBe(false);
  });
});

describe("FrameListModal base folder row", () => {
  const baseInput = (): HTMLInputElement =>
    document.body.querySelector('input[aria-label="Base folder"]') as HTMLInputElement;

  it("shows a disabled, explained base folder input in explorer format", () => {
    renderModal();
    const base = baseInput();
    expect(base).not.toBe(null);
    expect(base.disabled).toBe(true);
    expect(base.parentElement?.getAttribute("title")).toBe(
      "Base folder is used only by the move script format",
    );
  });

  it("enables the base folder input in script format", async () => {
    renderModal();
    fireEvent.change(formatSelect(), { target: { value: "script" } });
    await flush();
    const base = baseInput();
    expect(base.disabled).toBe(false);
    expect(base.parentElement?.getAttribute("title")).toBe(null);
  });

  it("seeds a never-set base folder from the WBPP library root", () => {
    general = { frame_list_base_folder: null, wbpp_default_os: null, wbpp_library_root: "Z:\\Astro" };
    renderModal();
    expect(baseInput().value).toBe("Z:\\Astro");
  });
});

describe("FrameListModal browser move", () => {
  const moveButton = (): HTMLButtonElement | undefined =>
    buttons().find((el) => /^Move \d+ to _rejected$/.test(el.textContent?.trim() ?? ""));

  const fakeRoot = { name: "picked" } as any;

  // Two hits for b_fail.fits (a collision), one for d_fail.fits, plus one
  // missing name -- exercises every row style of the confirm panel.
  const fakeScan = () => ({
    root: fakeRoot,
    matches: [
      { name: "b_fail.fits", relPath: "Ha/b_fail.fits", parent: {} as any },
      { name: "b_fail.fits", relPath: "Ha2/b_fail.fits", parent: {} as any },
      { name: "d_fail.fits", relPath: "Ha/d_fail.fits", parent: {} as any },
    ],
    missing: ["ghost.fits"],
    collisions: ["b_fail.fits"],
  });

  it("hides the move button entirely when the File System Access API is unsupported", () => {
    fsSupported = false;
    renderModal();
    expect(moveButton()).toBeUndefined();
    // The clipboard path is unaffected.
    expect(copyButton()).toBeDefined();
  });

  it("shows the confirm panel with counts, relPaths, collision notes and missing names after pick + scan", async () => {
    pickDirectoryMock.mockImplementation(() => Promise.resolve(fakeRoot));
    scanForNamesMock.mockImplementation(() => Promise.resolve(fakeScan()));
    renderModal();

    const btn = moveButton();
    expect(btn).toBeDefined();
    expect(btn!.textContent?.trim()).toBe("Move 2 to _rejected");
    fireEvent.click(btn!);
    await flush();

    expect(pickDirectoryMock).toHaveBeenCalledWith("readwrite", "frame-list-base");
    // The scan searches the SELECTED set (bad mode: the two fail frames).
    expect(scanForNamesMock).toHaveBeenCalledTimes(1);
    expect(scanForNamesMock.mock.calls[0][0]).toBe(fakeRoot);
    expect(scanForNamesMock.mock.calls[0][1]).toEqual(["b_fail.fits", "d_fail.fits"]);

    expect(bodyText()).toContain("3 files matched, 1 missing");
    expect(bodyText()).toContain("Files move to _rejected inside the picked folder.");
    expect(bodyText()).toContain("Ha/b_fail.fits");
    expect(bodyText()).toContain("Ha2/b_fail.fits");
    expect(bodyText()).toContain("Ha/d_fail.fits");
    expect(bodyText()).toContain("matches 2 files");
    expect(bodyText()).toContain("ghost.fits");
    // Confirm buttons replace the footer actions.
    expect(buttons().some((el) => el.textContent?.trim() === "Move 3")).toBe(true);
    expect(buttons().some((el) => el.textContent?.trim() === "Back")).toBe(true);
  });

  it("Back returns to the normal footer without moving anything", async () => {
    pickDirectoryMock.mockImplementation(() => Promise.resolve(fakeRoot));
    scanForNamesMock.mockImplementation(() => Promise.resolve(fakeScan()));
    renderModal();
    fireEvent.click(moveButton()!);
    await flush();

    const back = buttons().find((el) => el.textContent?.trim() === "Back")!;
    fireEvent.click(back);
    await flush();

    expect(moveMatchesMock).not.toHaveBeenCalled();
    expect(moveButton()).toBeDefined();
    expect(copyButton()).toBeDefined();
  });

  it("Move runs moveMatches on the scan, toasts the moved count and restores the footer", async () => {
    const scan = fakeScan();
    pickDirectoryMock.mockImplementation(() => Promise.resolve(fakeRoot));
    scanForNamesMock.mockImplementation(() => Promise.resolve(scan));
    moveMatchesMock.mockImplementation(() => Promise.resolve({ moved: 3, failed: [] }));
    renderModal();
    fireEvent.click(moveButton()!);
    await flush();

    const confirm = buttons().find((el) => el.textContent?.trim() === "Move 3")!;
    fireEvent.click(confirm);
    await flush();

    expect(moveMatchesMock).toHaveBeenCalledTimes(1);
    expect(moveMatchesMock.mock.calls[0][0]).toBe(scan);
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining("3"));
    // Back to the normal footer.
    expect(moveButton()).toBeDefined();
    expect(copyButton()).toBeDefined();
  });

  it("shows progress while moving and Stop aborts the run's signal", async () => {
    pickDirectoryMock.mockImplementation(() => Promise.resolve(fakeRoot));
    scanForNamesMock.mockImplementation(() => Promise.resolve(fakeScan()));
    let capturedProgress!: (done: number, total: number) => void;
    let capturedSignal!: AbortSignal;
    let finish!: () => void;
    moveMatchesMock.mockImplementation((_scan: any, onProgress: any, signal: AbortSignal) => {
      capturedProgress = onProgress;
      capturedSignal = signal;
      return new Promise((res) => {
        finish = () => res({ moved: 1, failed: [] });
      });
    });
    renderModal();
    fireEvent.click(moveButton()!);
    await flush();
    fireEvent.click(buttons().find((el) => el.textContent?.trim() === "Move 3")!);
    await flush();

    capturedProgress(1, 3);
    await flush();
    expect(bodyText()).toContain("1 of 3");

    const stop = buttons().find((el) => el.textContent?.trim() === "Stop")!;
    expect(stop).toBeDefined();
    expect(capturedSignal.aborted).toBe(false);
    fireEvent.click(stop);
    expect(capturedSignal.aborted).toBe(true);

    finish();
    await flush();
    expect(moveButton()).toBeDefined();
  });

  it("lists per-file failures inline after the run", async () => {
    pickDirectoryMock.mockImplementation(() => Promise.resolve(fakeRoot));
    scanForNamesMock.mockImplementation(() => Promise.resolve(fakeScan()));
    moveMatchesMock.mockImplementation(() =>
      Promise.resolve({ moved: 2, failed: [{ relPath: "Ha/b_fail.fits", message: "locked" }] }),
    );
    renderModal();
    fireEvent.click(moveButton()!);
    await flush();
    fireEvent.click(buttons().find((el) => el.textContent?.trim() === "Move 3")!);
    await flush();

    expect(bodyText()).toContain("Ha/b_fail.fits");
    expect(bodyText()).toContain("locked");
  });

  it("a cancelled picker is a silent no-op", async () => {
    pickDirectoryMock.mockImplementation(() => Promise.reject(new CopyCancelledError()));
    renderModal();
    fireEvent.click(moveButton()!);
    await flush();

    expect(scanForNamesMock).not.toHaveBeenCalled();
    expect(bodyText()).not.toContain("cancelled");
    // Normal footer untouched.
    expect(copyButton()).toBeDefined();
  });

  it("disables the move button when nothing is selected", async () => {
    renderModal();
    // Good mode with include-unmeasured off leaves 2 passes; flip every row
    // off via mode: switch to good then uncheck all three included rows.
    fireEvent.click(modeButton("Good"));
    await flush();
    fireEvent.click(rowCheckbox("a_pass.fits"));
    fireEvent.click(rowCheckbox("e_pass.fits"));
    fireEvent.click(rowCheckbox("c_unmeasured.fits"));
    await flush();
    expect(bodyText()).toContain("0 of 5 frames selected");
    expect(moveButton()!.disabled).toBe(true);
  });
});
