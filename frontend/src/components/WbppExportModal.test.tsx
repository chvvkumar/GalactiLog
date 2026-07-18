import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";

// The vi.mock factories must be hoisted above the component import, so the
// component's module-level imports resolve to these stubs.
let previewSessions: any[] = [];

const postMock = vi.fn((path: string, _opts?: any) => {
  if (path === "/api/wbpp/preview") {
    return Promise.resolve({
      data: { sessions: previewSessions, target_os: "windows" },
      response: { ok: true },
    });
  }
  return Promise.resolve({
    data: {
      filename: "wbpp_copy.ps1",
      target_os: "windows",
      staging_root: "Z:\\Astro\\_WBPP_staging\\M31",
      script: "# script",
      operations: [],
      exclusions: [],
      light_total: 0,
      light_excluded: 0,
      light_copied: 0,
    },
    response: { ok: true },
  });
});

// Session detail for a date the PAGE has not cached, so the modal must fetch it.
// Two lights, one clearly good and one clearly bad against the baseline, so the
// verdicts the panel renders are real rather than "unmeasured".
const fetchedDetail = () => ({
  equipment: { telescope: "TS", camera: "Cam" },
  rigs: [],
  frames: [
    {
      file_name: "fetched_good.fits", filter_used: "Ha",
      source_relative: "M31/2026-07-05/Ha/fetched_good.fits", file_size: 100,
      median_hfr: 1.0, eccentricity: null, fwhm: null, detected_stars: null,
      guiding_rms_arcsec: null, adu_median: null, rig: null,
    },
    {
      file_name: "fetched_bad.fits", filter_used: "Ha",
      source_relative: "M31/2026-07-05/Ha/fetched_bad.fits", file_size: 100,
      median_hfr: 3.0, eccentricity: null, fwhm: null, detected_stars: null,
      guiding_rms_arcsec: null, adu_median: null, rig: null,
    },
  ],
  session_baselines: { "TS|Cam|Ha": { median_hfr: { median: 2.0, mad: 0.5, n: 20 } } },
  rig_baselines: {},
});

const getMock = vi.fn((_path: string, _opts?: any) =>
  Promise.resolve({ data: fetchedDetail(), response: { ok: true } }),
);

vi.mock("../api/generated/client", () => ({
  apiClient: {
    POST: (path: string, opts: any) => postMock(path, opts),
    GET: (path: string, opts: any) => getMock(path, opts),
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

import WbppExportModal from "./WbppExportModal";
import type { SessionDetail } from "../api/types";

// Dialog renders through a Portal, so every query runs against document.body
// (same helper pattern as Dialog.test.tsx).
const bodyText = (): string => document.body.textContent ?? "";

const buttons = (): HTMLButtonElement[] =>
  Array.from(document.body.querySelectorAll("button"));

const buttonsLabelled = (label: string): HTMLButtonElement[] =>
  buttons().filter((b) => b.textContent?.trim() === label);

const primaryButton = (): HTMLButtonElement => {
  // The footer's primary is the only button whose label is one of these.
  const b = buttons().find((el) =>
    /^(Choose a destination|Choose a source folder|Access denied\. Choose the folder again\.|Grant access and copy|Copy [\d,]+ frames)$/.test(
      el.textContent?.trim() ?? "",
    ),
  );
  if (!b) throw new Error(`No primary button found. Body: ${bodyText()}`);
  return b;
};

const flush = () => new Promise((r) => setTimeout(r, 0));

const DATE = "2026-07-01";

function level(over: Record<string, unknown> = {}) {
  return {
    path: "Z:\\Astro\\M31\\2026-07-01\\Ha",
    container_path: "/data/M31/2026-07-01/Ha",
    depth_from_root: 3,
    frame_count: 10,
    frame_bytes: 1000,
    other_targets: [],
    other_dates: [],
    is_contaminated: false,
    relative_path: "M31/2026-07-01/Ha",
    ...over,
  };
}

function session(over: Record<string, unknown> = {}) {
  return {
    session_date: DATE,
    levels: [level()],
    default_level_index: 0,
    total_frame_count: 10,
    excluded_frame_count: 0,
    ...over,
  };
}

// Two lights with no measured metrics: scoreFrame returns null for both, so the
// score filter calls them "unmeasured" and excludes them. That exercises the
// filter's effect on the footer without needing baseline groups.
function cacheDetail(): SessionDetail {
  const frame = (name: string, fileSize: number | null) => ({
    file_name: name,
    filter_used: "Ha",
    source_relative: `M31/2026-07-01/Ha/${name}`,
    file_size: fileSize,
    median_hfr: null,
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
    frames: [frame("a.fits", 100), frame("b.fits", 100)],
    session_baselines: {},
    rig_baselines: {},
  } as unknown as SessionDetail;
}

function renderModal(cache: Record<string, SessionDetail> = { [DATE]: cacheDetail() }) {
  return render(() => (
    <WbppExportModal
      targetId="t-1"
      targetName="M31"
      selectedDates={[DATE]}
      sessionCache={cache}
      onClose={() => {}}
    />
  ));
}

/**
 * Settles the Folders-to-copy zone. The modal previews automatically on mount
 * whenever a library root is set, so most tests only need to let that resolve;
 * the manual button exists only when the auto-preview was skipped.
 */
async function preview() {
  const btn = buttonsLabelled("Preview folder levels")[0];
  if (btn) fireEvent.click(btn);
  await flush();
}

/**
 * Grants both handles via the pickers so the footer's primary reaches its
 * "Copy N frames" state. Unpicked folders read "Choose..."; in DOM order the
 * Destination zone's rows are "Copy to" then "Copy from".
 */
async function pickBothFolders() {
  fireEvent.click(buttonsLabelled("Choose...")[0]);
  await flush();
  fireEvent.click(buttonsLabelled("Choose...")[0]);
  await flush();
}

// The quality panel's master toggle is the modal's only checkbox.
const filterCheckbox = (): HTMLInputElement =>
  document.body.querySelector('input[type="checkbox"]') as HTMLInputElement;

/**
 * Turns the filter on AND arms one gate. An empty constraint set is no filter
 * (every frame passes), so the enable checkbox alone excludes nothing; the
 * ghost "+ HFR" chip adds a constraint, which starts VALUELESS and gates
 * nothing until a number is typed. This helper types 0 (frames without HFR
 * land in "unmeasured" and are excluded); tests with measured frames tighten
 * the threshold explicitly via setHfrThreshold.
 */
async function enableFilterWithHfrGate() {
  fireEvent.click(filterCheckbox());
  await flush();
  const chip = buttons().find((b) => b.textContent?.replace(/\s+/g, "") === "+HFR");
  if (!chip) throw new Error(`No ghost HFR chip found. Body: ${bodyText()}`);
  fireEvent.click(chip);
  await flush();
  await setHfrThreshold(0);
}

async function setHfrThreshold(value: number) {
  const input = document.body.querySelector(
    'input[aria-label="HFR threshold"]',
  ) as HTMLInputElement;
  fireEvent.input(input, { target: { value: String(value) } });
  await flush();
}

beforeEach(() => {
  document.body.innerHTML = "";
  // The quality filter persists per rig in localStorage; leaking one test's
  // enablement into the next modal's hydration would couple the suite.
  localStorage.clear();
  previewSessions = [session()];
  general = {
    wbpp_library_root: "Z:\\Astro",
    wbpp_default_os: null,
    wbpp_staging_path: null,
    wbpp_exclusions: ["WBPP"],
  };
  // isFsAccessSupported() gates on a secure context plus showDirectoryPicker;
  // jsdom reports isSecureContext false and has no picker, so stub both to
  // exercise the browser-copy path.
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  (window as any).showDirectoryPicker = vi.fn(async ({ mode }: { mode: string }) => ({
    name: mode === "read" ? "AstroLib" : "Staging",
    queryPermission: async () => "granted",
    requestPermission: async () => "granted",
  }));
  postMock.mockClear();
  getMock.mockClear();
  saveGeneralMock.mockClear();
});

describe("WbppExportModal layout", () => {
  it("renders header, body and footer with the body as the only scroll container", () => {
    renderModal();
    const body = document.body.querySelector('[data-testid="wbpp-modal-body"]') as HTMLElement;
    expect(body).not.toBe(null);
    expect(body.className).toContain("overflow-y-auto");

    // The panel must NOT scroll, or the footer scrolls away with the content.
    const panel = body.parentElement as HTMLElement;
    expect(panel.className).toContain("flex-col");
    expect(panel.className).toContain("max-h-[85vh]");
    expect(panel.className.includes("overflow-y-auto")).toBe(false);

    // Header: the title states the action; the target name moved to the subline.
    const h2 = document.body.querySelector("#wbpp-modal-title") as HTMLElement;
    expect(h2.textContent?.trim()).toBe("Export to WBPP");
    expect(
      document.body.querySelector('[role="dialog"]')?.getAttribute("aria-labelledby"),
    ).toBe("wbpp-modal-title");
    // Frame count before a preview comes from the page's session cache.
    expect(bodyText()).toContain("M31 · 1 session · 2 frames");

    // Footer is sticky and repeats modal-surface so content cannot bleed through.
    const footer = panel.lastElementChild as HTMLElement;
    expect(footer.className).toContain("sticky");
    expect(footer.className).toContain("modal-surface");
  });

  it("uses the token shadow rather than a hardcoded one", () => {
    renderModal();
    const body = document.body.querySelector('[data-testid="wbpp-modal-body"]') as HTMLElement;
    const panel = body.parentElement as HTMLElement;
    expect(panel.className).toContain("shadow-[var(--shadow-lg)]");
    expect(panel.className).not.toContain("rgba(0,0,0,0.7)");
    expect(panel.className).not.toContain("ring-white/10");
  });
});

describe("WbppExportModal footer", () => {
  it("disables the primary with 'Choose a destination' when no destination is set", () => {
    renderModal();
    const primary = primaryButton();
    expect(primary.textContent?.trim()).toBe("Choose a destination");
    expect(primary.disabled).toBe(true);
    expect(bodyText()).toContain("Not set");
  });

  it("asks for the source folder, disabled, when only the destination is set", async () => {
    // The rewrite gated the primary on the destination alone, so this user got an
    // enabled "Grant access and copy" whose only possible outcome was the error
    // banner "Choose a library folder and a destination folder first." Disabling it
    // is half the fix; the other half is not naming a step that is not the blocker.
    renderModal();
    await preview();
    fireEvent.click(buttonsLabelled("Choose...")[0]);
    await flush();

    expect(bodyText()).toContain("Staging");
    const primary = primaryButton();
    expect(primary.textContent?.trim()).toBe("Choose a source folder");
    expect(primary.disabled).toBe(true);
  });

  it("points a denied user back at the picker rather than at a dead end", async () => {
    (window as any).showDirectoryPicker = vi.fn(async ({ mode }: { mode: string }) => ({
      name: mode === "read" ? "AstroLib" : "Staging",
      queryPermission: async () => "denied",
      requestPermission: async () => "denied",
    }));
    renderModal();
    await preview();
    await pickBothFolders();

    expect(bodyText()).toContain("access denied");
    const primary = primaryButton();
    // Re-picking is the only recovery: once refused, the browser will not re-prompt
    // for that handle, so "Grant access and copy" was an offer it could not keep.
    expect(primary.textContent?.trim()).toBe("Access denied. Choose the folder again.");
    expect(primary.disabled).toBe(true);
  });

  it("reaches 'access denied' when the copy's permission request is refused", async () => {
    // Only the success path used to set permission state, so a refusal left the row
    // reading "needs permission" and the primary offering to grant access forever.
    (window as any).showDirectoryPicker = vi.fn(async ({ mode }: { mode: string }) => ({
      name: mode === "read" ? "AstroLib" : "Staging",
      queryPermission: async () => "prompt",
      requestPermission: async () => "denied",
      values: async function* () {},
    }));
    renderModal();
    await preview();
    await pickBothFolders();
    expect(bodyText()).toContain("needs permission");

    const primary = primaryButton();
    expect(primary.disabled).toBe(false);
    fireEvent.click(primary);
    await flush();

    expect(bodyText()).toContain("Read permission for the library folder was denied.");
    expect(bodyText()).toContain("access denied");
    expect(primaryButton().disabled).toBe(true);
  });

  it("renders the size total once a destination and preview exist", async () => {
    renderModal();
    await preview();
    await pickBothFolders();
    expect(primaryButton().textContent?.trim()).toBe("Copy 10 frames");
    expect(bodyText()).toContain("1 KB");
  });

  it("renders '—' for the size when a selected level's frame_bytes is null", async () => {
    previewSessions = [session({ levels: [level({ frame_bytes: null })] })];
    renderModal();
    await preview();
    // Never a 0 B and never a partial sum: the backend sends null rather than
    // an undercount, and the footer must say so.
    expect(bodyText()).toContain("10 frames · 1 folder · —");
    expect(bodyText()).not.toContain("0 B");
  });

  it("keeps the size null when an excluded frame has no recorded file_size", async () => {
    const cache = cacheDetail();
    (cache.frames[0] as any).file_size = null;
    renderModal({ [DATE]: cache });
    await preview();
    expect(bodyText()).toContain("1 KB");

    // The HFR gate excludes both unmeasured cached lights; one of them has no
    // recorded size, so the remaining byte total is unknowable.
    await enableFilterWithHfrGate();
    expect(bodyText()).toContain("8 frames · 1 folder · —");
  });
});

/**
 * A session split across two filter folders, as the reviewer traced it: 60 lights,
 * 30 under .../Ha and 30 under .../OIII.
 *
 * Pass/fail is deterministic via median_hfr alone: every frame carries an hfr of
 * either 1.0 or 3.0, so an HFR ≤ 2 constraint passes the former and fails the
 * latter, with nothing landing in "unmeasured".
 */
function splitSessionDetail(haFails: number, oiiiFails: number): SessionDetail {
  const frame = (folder: string, i: number, fails: boolean) => ({
    file_name: `${folder}_${i}.fits`,
    filter_used: folder,
    source_relative: `M31/2026-07-01/${folder}/${folder}_${i}.fits`,
    file_size: 20_000_000,
    median_hfr: fails ? 3.0 : 1.0,
    eccentricity: null,
    fwhm: null,
    detected_stars: null,
    guiding_rms_arcsec: null,
    adu_median: null,
    rig: null,
  });
  const hfrBaseline = { median_hfr: { median: 2.0, mad: 0.5, n: 20 } };
  return {
    equipment: { telescope: "TS", camera: "Cam" },
    rigs: [],
    frames: [
      ...Array.from({ length: 30 }, (_, i) => frame("Ha", i, i < haFails)),
      ...Array.from({ length: 30 }, (_, i) => frame("OIII", i, i < oiiiFails)),
    ],
    session_baselines: { "TS|Cam|Ha": hfrBaseline, "TS|Cam|OIII": hfrBaseline },
    rig_baselines: {},
  } as unknown as SessionDetail;
}

/** The Ha level only: 30 of the session's 60 frames, 600 MB of its bytes. */
const HA_LEVEL = level({
  path: "Z:\\Astro\\M31\\2026-07-01\\Ha",
  relative_path: "M31/2026-07-01/Ha",
  frame_count: 30,
  frame_bytes: 600_000_000,
});

describe("WbppExportModal quality frame fetch", () => {
  // Every other test in this file passes a populated sessionCache, which is exactly
  // why the loop below shipped: `props.sessionCache[date] ?? qualitySessions()[date]`
  // short-circuits, so a cached date never reads (never tracks) the signal the
  // effect writes. Only an UNCACHED date reaches that read. These tests use an
  // empty cache on purpose.
  const UNCACHED = "2026-07-05";

  const renderUncached = (dates: string[] = [UNCACHED]) =>
    render(() => (
      <WbppExportModal
        targetId="t-1"
        targetName="M31"
        selectedDates={dates}
        sessionCache={{}}
        onClose={() => {}}
      />
    ));

  const enableFilter = async () => {
    fireEvent.click(document.body.querySelector('input[type="checkbox"]') as HTMLInputElement);
    await flush();
  };

  it("fetches an uncached session exactly once instead of looping forever", async () => {
    renderUncached();
    await enableFilter();
    // The effect used to subscribe to the signal it writes, so each write retriggered
    // it and fired another GET: thousands of identical requests per second at the
    // backend, for as long as the modal stayed open.
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock.mock.calls[0][0]).toBe("/api/targets/{target_id}/sessions/{date}");
    expect(getMock.mock.calls[0][1].params.path.date).toBe(UNCACHED);

    // Still settled after further ticks: a loop would keep climbing.
    await flush();
    await flush();
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it("fetches each uncached date once and no more", async () => {
    renderUncached([UNCACHED, "2026-07-06", "2026-07-07"]);
    await enableFilter();
    expect(getMock).toHaveBeenCalledTimes(3);
    expect(getMock.mock.calls.map((c) => c[1].params.path.date).sort()).toEqual([
      "2026-07-05",
      "2026-07-06",
      "2026-07-07",
    ]);
  });

  it("lands the fetched frames in state rather than overwriting them each pass", async () => {
    // The other half of the same bug: every rerun reset state to a snapshot taken
    // before the in-flight fetch resolved, so the arriving frames were discarded and
    // the panel graded an empty table on a session that had plenty.
    renderUncached();
    await enableFilterWithHfrGate();
    // The chip's default derives from the session baseline (median 2.0, mad 0.5:
    // 2.0 + 1.5 * 1.4826 * 0.5 = 3.11), which both frames clear. Tighten it so
    // the verdicts split: hfr 1.0 passes, hfr 3.0 fails.
    await setHfrThreshold(2);
    expect(bodyText()).not.toContain("No light frames");
    expect(bodyText()).toContain("fetched_good.fits");
    expect(bodyText()).toContain("fetched_bad.fits");
    // Real verdicts from the fetched frames: the failing HFR cell carries the
    // gate sentence as its tooltip (the table no longer prints reason text).
    const tdTitles = Array.from(document.body.querySelectorAll("td[title]")).map((t) =>
      t.getAttribute("title"),
    );
    expect(tdTitles).toContain("HFR 3.00 > 2.00");
  });
});

describe("WbppExportModal quality filter", () => {
  it("counts only the excluded frames inside the selected level", async () => {
    // The selected Ha level holds 30 frames; 5 of them fail. The other 20 failures
    // are OIII frames, physically outside the level, which the copy never touches
    // (wbppBrowserCopy only skips files under the subtree it walks).
    previewSessions = [session({ levels: [HA_LEVEL], total_frame_count: 60 })];
    renderModal({ [DATE]: splitSessionDetail(5, 20) });
    await preview();
    await pickBothFolders();
    expect(primaryButton().textContent?.trim()).toBe("Copy 30 frames");

    await enableFilterWithHfrGate();
    await setHfrThreshold(2);

    // 30 - 5, NOT 30 - 25: subtracting all 25 failures across the session from a
    // level that only contains 5 of them mixed two different frame domains.
    expect(primaryButton().textContent?.trim()).toBe("Copy 25 frames");
    // 600 MB - (5 x 20 MB). The 20 OIII frames never contributed to the level's
    // 600 MB, so deducting their bytes understated the total roughly four-fold.
    expect(bodyText()).toContain("25 frames · 1 folder · 500 MB");
  });

  it("cannot drive the count negative when the failures sit outside the level", async () => {
    // 35 of the session's 60 frames fail, but the selected level only holds 30.
    // Subtracting across domains rendered "Copy -5 frames".
    previewSessions = [session({ levels: [HA_LEVEL], total_frame_count: 60 })];
    renderModal({ [DATE]: splitSessionDetail(5, 30) });
    await preview();
    await pickBothFolders();

    await enableFilterWithHfrGate();
    await setHfrThreshold(2);

    expect(primaryButton().textContent?.trim()).toBe("Copy 25 frames");
    expect(bodyText()).not.toContain("-5 frames");
  });

  it("drives the footer count and the primary label", async () => {
    renderModal();
    await preview();
    await pickBothFolders();
    expect(primaryButton().textContent?.trim()).toBe("Copy 10 frames");
    expect(bodyText()).toContain("10 frames · 1 folder · 1 KB");

    await enableFilterWithHfrGate();

    // Both cached lights carry no HFR, so the gate lands them in "unmeasured"
    // and excludes them: 10 - 2 = 8, and their 100 B each comes off the 1000 B
    // level total.
    expect(primaryButton().textContent?.trim()).toBe("Copy 8 frames");
    expect(bodyText()).toContain("8 frames · 1 folder · 800 B");
  });
});

describe("WbppExportModal quality config persistence", () => {
  const KEY = "galactilog.wbppQuality.v1.default";

  const stored = (over: Record<string, unknown> = {}) =>
    JSON.stringify({
      enabled: true,
      config: {
        baseline: "rig",
        constraints: [{ metric: "ecc", op: "lte", value: 0.55, enabled: true }],
      },
      ...over,
    });

  it("hydrates the filter from the per-rig store instead of resetting it", async () => {
    localStorage.setItem(KEY, stored());
    renderModal();
    await flush();

    // Opening the modal used to reset every one of these, so the same tuning was
    // redone by hand on every export.
    expect(filterCheckbox().checked).toBe(true);
    const value = document.body.querySelector(
      'input[aria-label="Ecc threshold"]',
    ) as HTMLInputElement;
    expect(value.value).toBe("0.55");
    // The stored "rig" baseline is the active segment.
    const rigSegment = buttonsLabelled("Rig (catalog)")[0];
    expect(rigSegment.className).toContain("text-theme-accent");
  });

  it("falls back to filter-off with no constraints when nothing is stored", () => {
    renderModal();
    expect(filterCheckbox().checked).toBe(false);
    // The panel toolbar is always present; no chip is active.
    expect(bodyText()).toContain("Enable filters");
    expect(document.body.querySelector('input[aria-label="HFR threshold"]')).toBe(null);
    expect(document.body.querySelector('input[aria-label="Ecc threshold"]')).toBe(null);
  });

  // Stored config can predate this build. A metric it no longer evaluates must
  // be dropped, not carried into the filter as a gate that matches nothing.
  it("drops a stored constraint naming an unknown metric", async () => {
    localStorage.setItem(
      KEY,
      stored({
        config: {
          baseline: "session",
          constraints: [
            { metric: "snr", op: "lte", value: 5, enabled: true },
            { metric: "ecc", op: "lte", value: 0.55, enabled: true },
          ],
        },
      }),
    );
    renderModal();
    await flush();
    expect(document.body.querySelector('input[aria-label="Ecc threshold"]')).not.toBe(null);
    expect(bodyText()).not.toContain("snr");
  });

  it("writes changes to localStorage and never to server settings", async () => {
    renderModal();
    fireEvent.click(filterCheckbox());
    await flush();

    const raw = localStorage.getItem(KEY);
    expect(raw).not.toBe(null);
    expect(JSON.parse(raw!)).toMatchObject({ enabled: true });

    // The old debounced PUT /settings/general is gone: the filter is a rig-shaped
    // browser preference now, and a non-admin must not lose it to a 403.
    await new Promise((r) => setTimeout(r, 900));
    expect(saveGeneralMock).not.toHaveBeenCalled();
  });

  it("keys the store by the sessions' rig when the frames carry one", async () => {
    const cache = cacheDetail();
    for (const f of cache.frames) (f as any).rig = "RigA";
    localStorage.setItem(
      "galactilog.wbppQuality.v1.RigA",
      stored({ config: { baseline: "session", constraints: [] } }),
    );
    renderModal({ [DATE]: cache });
    await flush();

    // Hydrated from RigA's slot, not from "default".
    expect(filterCheckbox().checked).toBe(true);

    fireEvent.click(filterCheckbox());
    await flush();
    expect(JSON.parse(localStorage.getItem("galactilog.wbppQuality.v1.RigA")!)).toMatchObject({
      enabled: false,
    });
  });

  it("keeps in-session edits when the rig resolves after a fetch", async () => {
    // Uncached sessions: the rig starts null and only resolves once the fetched
    // frames arrive -- after the user may already have tuned the filter. The
    // resolved rig's stored state (filter off) must NOT clobber those edits;
    // instead the edits move to the resolved rig's slot.
    const detail = fetchedDetail();
    for (const f of detail.frames) (f as any).rig = "RigX";
    getMock.mockImplementation(() =>
      Promise.resolve({ data: detail, response: { ok: true } }),
    );
    localStorage.setItem(
      "galactilog.wbppQuality.v1.RigX",
      JSON.stringify({ enabled: false, config: { baseline: "session", constraints: [] } }),
    );
    render(() => (
      <WbppExportModal
        targetId="t-1"
        targetName="M31"
        selectedDates={["2026-07-05"]}
        sessionCache={{}}
        onClose={() => {}}
      />
    ));

    // The user's edit: enable the filter while the rig is still unresolved.
    fireEvent.click(filterCheckbox());
    await flush();

    // The fetch has resolved and the frames carry RigX, yet the edit survives...
    expect(filterCheckbox().checked).toBe(true);
    // ...and has been written under the resolved rig's own key.
    expect(JSON.parse(localStorage.getItem("galactilog.wbppQuality.v1.RigX")!)).toMatchObject({
      enabled: true,
    });
  });
});

describe("WbppExportModal empty-export guard", () => {
  const emptied = () => document.body.querySelector('[data-testid="wbpp-empty-export"]');

  it("says so when the filter excludes every frame in the selected folders", async () => {
    // The level holds exactly the two cached lights, both unmeasured under the
    // HFR gate, so the filter takes all of them: the copy would write an empty
    // folder.
    previewSessions = [
      session({ levels: [level({ frame_count: 2, frame_bytes: 200 })], total_frame_count: 2 }),
    ];
    renderModal();
    await preview();
    expect(emptied()).toBe(null);

    await enableFilterWithHfrGate();

    expect(emptied()).not.toBe(null);
    expect(bodyText()).toContain("would copy nothing");
    await pickBothFolders();
    expect(primaryButton().textContent?.trim()).toBe("Copy 0 frames");
  });

  it("stays quiet while the filter still keeps frames", async () => {
    renderModal();
    await preview();
    await enableFilterWithHfrGate();
    // 10 frames in the level, 2 excluded: 8 still copy.
    expect(emptied()).toBe(null);
  });

  it("does not blame the filter for a genuinely empty folder", async () => {
    previewSessions = [
      session({ levels: [level({ frame_count: 0, frame_bytes: 0 })], total_frame_count: 0 }),
    ];
    renderModal({});
    await preview();
    await enableFilterWithHfrGate();
    // Nothing was there to exclude, so the filter is not the reason.
    expect(emptied()).toBe(null);
  });

  it("stays quiet when the filter is off", async () => {
    previewSessions = [
      session({ levels: [level({ frame_count: 2, frame_bytes: 200 })], total_frame_count: 2 }),
    ];
    renderModal();
    await preview();
    expect(emptied()).toBe(null);
  });
});

describe("WbppExportModal script menu", () => {
  const openMenu = () => {
    fireEvent.click(buttons().find((b) => b.textContent?.includes("Generate script"))!);
  };

  it("marks the detected OS when no preference is pinned", () => {
    general.wbpp_default_os = null;
    renderModal();
    openMenu();
    const menu = document.body.querySelector('[role="menu"]') as HTMLElement;
    const powershell = Array.from(menu.querySelectorAll('[role="menuitem"]')).find((i) =>
      i.textContent?.includes("PowerShell"),
    ) as HTMLElement;
    // Z:\Astro is a Windows root, so PowerShell is the detected default.
    expect(powershell.textContent).toContain("Detected");
    expect(menu.textContent).not.toContain("Your default");
  });

  it("marks the pinned preference as 'Your default'", () => {
    general.wbpp_default_os = "posix";
    renderModal();
    openMenu();
    const menu = document.body.querySelector('[role="menu"]') as HTMLElement;
    const shell = Array.from(menu.querySelectorAll('[role="menuitem"]')).find((i) =>
      i.textContent?.includes("Shell (.sh)"),
    ) as HTMLElement;
    // The pinned preference wins over the Windows library root's detection.
    expect(shell.textContent).toContain("Your default");
    expect(menu.textContent).not.toContain("Detected");
  });

  it("sends the chosen OS to generate rather than the resolved default", async () => {
    general.wbpp_default_os = null;
    renderModal();
    openMenu();
    const shell = Array.from(
      document.body.querySelectorAll('[role="menuitem"]'),
    ).find((i) => i.textContent?.includes("Shell (.sh)")) as HTMLElement;
    fireEvent.click(shell);
    await flush();
    // The default resolved to "windows"; the click must override it, or the menu
    // is decoration.
    const call = postMock.mock.calls.find((c) => c[0] === "/api/wbpp/generate");
    expect(call).not.toBe(undefined);
    expect(call![1].body.target_os).toBe("posix");
  });

  it("keeps the script output reachable after generation", async () => {
    renderModal();
    openMenu();
    fireEvent.click(document.body.querySelectorAll('[role="menuitem"]')[0] as HTMLElement);
    await flush();
    expect(bodyText()).toContain("Download wbpp_copy.ps1");
    expect(bodyText()).toContain("Copy script");
    expect(bodyText()).toContain("Hide script");
    expect(bodyText()).toContain("Unblock-File");
  });
});

describe("WbppExportModal destinations", () => {
  it("shows the script's staging path on Chromium, distinctly from the copy target", async () => {
    // The handle name used to displace the staging root entirely, so a Chromium
    // user could not see where a generated script would write -- and the footer's
    // "→ Staging" pointed at a different place than the script's output.
    renderModal();
    await pickBothFolders();
    expect(bodyText()).toContain("Copy → Staging");
    expect(bodyText()).toContain("Script → Z:\\Astro\\_WBPP_staging\\M31");
    expect(bodyText()).toContain("Script to");
  });

  it("honours a staging override in the script destination", async () => {
    general.wbpp_staging_path = "D:\\stage";
    renderModal();
    expect(bodyText()).toContain("Script → D:\\stage");
  });

  it("still shows the staging path when the browser cannot copy", () => {
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    renderModal();
    expect(bodyText()).toContain("Script → Z:\\Astro\\_WBPP_staging\\M31");
    // The fallback used to point at "the staging path above" when no such line existed.
    expect(bodyText()).toContain('it copies into the "Script to" path above');
  });

  it("invites a choice before a folder exists and a change after", async () => {
    renderModal();
    // "Change" on an empty row invited changing something that was not set.
    expect(buttonsLabelled("Choose...").length).toBe(2);
    expect(buttonsLabelled("Change...").length).toBe(0);
    await pickBothFolders();
    expect(buttonsLabelled("Choose...").length).toBe(0);
    expect(buttonsLabelled("Change...").length).toBe(2);
  });
});

describe("WbppExportModal settings", () => {
  it("no longer offers a script-type select", () => {
    renderModal();
    // Reveal the app-config fields behind Options > Change.
    const change = buttonsLabelled("Change");
    fireEvent.click(change[change.length - 1]);
    expect(bodyText()).toContain("Library root (on your machine)");
    expect(bodyText()).toContain("Excluded folder patterns (one per line)");
    // The choice moved to the footer menu; no select offers it any more.
    const options = Array.from(document.body.querySelectorAll("option"));
    expect(options.some((o) => o.getAttribute("value") === "auto")).toBe(false);
    expect(bodyText()).not.toContain("Auto-detect");
    expect(bodyText()).not.toContain("Detected:");
  });

  it("shows the resolved library line in Options", () => {
    renderModal();
    expect(bodyText()).toContain("Library: Z:\\Astro (Windows)");
  });
});

describe("WbppExportModal reattach to a live copy", () => {
  // The copy lives in the module-level wbppCopyJob store precisely so it
  // survives the modal closing; a later remount (e.g. reopening the export
  // dialog) must render the store's live state rather than starting fresh.
  it("renders progress from the store immediately on mount, without the modal itself starting the copy", async () => {
    let resolveCopy!: (r: { copied: number; destinationName: string }) => void;
    postMock.mockClear();
    const wbppBrowserCopy = await import("../lib/wbppBrowserCopy");
    vi.spyOn(wbppBrowserCopy, "runBrowserCopy").mockImplementation(
      ((_root: any, _dest: any, opts: any) => {
        opts.onProgress(4, 8, "reattach.fits");
        return new Promise((res) => {
          resolveCopy = res;
        });
      }) as any,
    );
    const { startWbppCopy, stopWbppCopy } = await import("../store/wbppCopyJob");

    // Drive the store to "running" the same way a previous, now-unmounted
    // instance of this modal would have, via startWbppCopy directly rather
    // than through any component.
    const copyPromise = startWbppCopy({
      rootHandle: {},
      destHandle: {},
      operations: [],
      exclusions: [],
      excludedSourceRelatives: [],
      targetName: "M31",
    });

    // A fresh mount of the modal -- simulating "reopen" -- must reflect the
    // in-flight copy immediately, with no click of its own required.
    renderModal();
    expect(bodyText()).toMatch(/4|8/);
    const bar = document.body.querySelector(".bg-theme-accent.transition-all") as HTMLElement;
    expect(bar).not.toBe(null);
    expect(bar.style.width).toBe("50%");

    // Cleanup: stop the copy so it does not leak into later tests.
    stopWbppCopy();
    resolveCopy({ copied: 4, destinationName: "d" });
    await copyPromise;
  });
});

describe("WbppExportModal folder rows", () => {
  it("offers a manual preview only while no library root allows the auto-preview", () => {
    // With a root set the modal previews on mount; without one it must not fire
    // a doomed request, and the manual entry waits (disabled) for the root.
    general.wbpp_library_root = "";
    renderModal();
    expect(postMock).not.toHaveBeenCalled();
    const btn = buttonsLabelled("Preview folder levels")[0];
    expect(btn).not.toBe(undefined);
    expect(btn.disabled).toBe(true);
    expect(bodyText()).toContain(
      "Preview the folder levels to choose which folder to copy for each session",
    );
  });

  it("shows one row per session and hides the full path behind the title attribute", async () => {
    renderModal();
    await preview();
    expect(postMock.mock.calls[0][0]).toBe("/api/wbpp/preview");
    const row = Array.from(document.body.querySelectorAll("[title]")).find(
      (el) => el.getAttribute("title") === "Z:\\Astro\\M31\\2026-07-01\\Ha",
    );
    expect(row).not.toBe(undefined);
    expect(row!.textContent).toContain(DATE);
    expect(row!.textContent).toContain("10 frames");
  });

  it("mounts the level editor in place when a row is expanded", async () => {
    renderModal();
    await preview();
    expect(document.body.querySelector('[role="radiogroup"]')).toBe(null);
    const row = buttons().find((b) => b.getAttribute("aria-expanded") === "false");
    expect(row).not.toBe(undefined);
    fireEvent.click(row!);
    expect(document.body.querySelector('[role="radiogroup"]')).not.toBe(null);
    fireEvent.click(row!);
    expect(document.body.querySelector('[role="radiogroup"]')).toBe(null);
  });

  it("offers a rescan icon button instead of a refresh text button", async () => {
    renderModal();
    await preview();
    expect(buttonsLabelled("Refresh folder levels").length).toBe(0);
    const rescan = buttons().find((b) => b.getAttribute("aria-label") === "Rescan folders");
    expect(rescan).not.toBe(undefined);
    fireEvent.click(rescan!);
    await flush();
    expect(postMock.mock.calls.filter((c) => c[0] === "/api/wbpp/preview").length).toBe(2);
  });

  it("shows a visible in-progress state while rescanning", async () => {
    renderModal();
    await preview();
    // Hold the preview open so the in-flight state can be observed: a dimmed icon
    // on its own left a slow rescan looking like nothing had happened.
    let release = () => {};
    postMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () =>
            resolve({
              data: { sessions: previewSessions, target_os: "windows" },
              response: { ok: true },
            });
        }) as any,
    );
    fireEvent.click(buttons().find((b) => b.getAttribute("aria-label") === "Rescan folders")!);
    await flush();

    expect(bodyText()).toContain("Rescanning...");
    const spinner = document.body.querySelector("svg.animate-spin");
    expect(spinner).not.toBe(null);
    expect(
      buttons().find((b) => b.getAttribute("aria-label") === "Rescanning folders")?.disabled,
    ).toBe(true);

    release();
    await flush();
    expect(bodyText()).not.toContain("Rescanning...");
  });

  it("names the renamed destination only on the rows a rename happens to", async () => {
    // Two sessions whose chosen folders share the basename LIGHT: plan() renames
    // both to {date}_LIGHT. Nothing used to say so.
    const other = "2026-07-02";
    previewSessions = [
      session({ levels: [level({ path: "Z:\\Astro\\M31\\2026-07-01\\LIGHT" })] }),
      session({
        session_date: other,
        levels: [level({ path: "Z:\\Astro\\M31\\2026-07-02\\LIGHT" })],
      }),
    ];
    render(() => (
      <WbppExportModal
        targetId="t-1"
        targetName="M31"
        selectedDates={[DATE, other]}
        sessionCache={{}}
        onClose={() => {}}
      />
    ));
    await preview();
    expect(bodyText()).toContain(`→ ${DATE}_LIGHT`);
    expect(bodyText()).toContain(`→ ${other}_LIGHT`);
  });

  it("says nothing about renaming when the basenames do not collide", async () => {
    renderModal();
    await preview();
    // A single Ha folder keeps its name, so the row must not imply otherwise.
    expect(bodyText()).not.toContain("→ Ha");
    expect(bodyText()).not.toContain(`${DATE}_Ha`);
  });
});
