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

import FrameListModal from "./FrameListModal";
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
