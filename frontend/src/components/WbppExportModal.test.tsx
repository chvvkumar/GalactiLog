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

vi.mock("../api/generated/client", () => ({
  apiClient: {
    POST: (path: string, opts: any) => postMock(path, opts),
    GET: () => Promise.resolve({ data: null, response: { ok: true } }),
  },
}));

let general: Record<string, unknown> = {};

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    settings: () => ({ general }),
    displaySettings: () => undefined,
    saveGeneral: vi.fn(() => Promise.resolve({})),
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

/** Populates the Folders-to-copy zone by running the preview. */
async function preview() {
  fireEvent.click(buttonsLabelled("Preview folder levels")[0]);
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

beforeEach(() => {
  document.body.innerHTML = "";
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

    fireEvent.click(document.body.querySelector('input[type="checkbox"]') as HTMLElement);
    await flush();
    expect(bodyText()).toContain("8 frames · 1 folder · —");
  });
});

/**
 * A session split across two filter folders, as the reviewer traced it: 60 lights,
 * 30 under .../Ha and 30 under .../OIII.
 *
 * Pass/fail is deterministic via median_hfr alone: with a session baseline of
 * median 2.0 / mad 0.5, hfr 1.0 gives z=-2 -> score 83.4 (pass) and hfr 3.0 gives
 * z=+2 -> score 16.6 (fail, under the default threshold of 60). detected_stars and
 * eccentricity stay null so those axes drop out of combinedScore.
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

    fireEvent.click(document.body.querySelector('input[type="checkbox"]') as HTMLElement);
    await flush();

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

    fireEvent.click(document.body.querySelector('input[type="checkbox"]') as HTMLElement);
    await flush();

    expect(primaryButton().textContent?.trim()).toBe("Copy 25 frames");
    expect(bodyText()).not.toContain("-5 frames");
  });

  it("drives the footer count and the primary label", async () => {
    renderModal();
    await preview();
    await pickBothFolders();
    expect(primaryButton().textContent?.trim()).toBe("Copy 10 frames");
    expect(bodyText()).toContain("10 frames · 1 folder · 1 KB");

    const checkbox = document.body.querySelector('input[type="checkbox"]') as HTMLInputElement;
    fireEvent.click(checkbox);
    await flush();

    // Both cached lights are unmeasured, so both are excluded: 10 - 2 = 8, and
    // their 100 B each comes off the 1000 B level total.
    expect(primaryButton().textContent?.trim()).toBe("Copy 8 frames");
    expect(bodyText()).toContain("8 frames · 1 folder · 800 B");
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

describe("WbppExportModal folder rows", () => {
  it("keeps the preview empty state until a preview runs", () => {
    renderModal();
    expect(bodyText()).toContain('Click "Preview folder levels" to choose which folder to copy');
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

  it("mounts the level editor in place when Edit is toggled", async () => {
    renderModal();
    await preview();
    expect(document.body.querySelector('[role="radiogroup"]')).toBe(null);
    fireEvent.click(buttonsLabelled("Edit")[0]);
    expect(document.body.querySelector('[role="radiogroup"]')).not.toBe(null);
    fireEvent.click(buttonsLabelled("Done")[0]);
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
