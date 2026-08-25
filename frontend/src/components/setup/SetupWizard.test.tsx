import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";
import { shouldShowWizard } from "../ProtectedRoute";
import type { SetupState } from "../../api/setup";

const harness = vi.hoisted(() => {
  const state: {
    setup: Record<string, unknown> | undefined;
    general: Record<string, unknown>;
    saved: Record<string, unknown>[];
    filters: unknown[];
    markComplete: () => Promise<void>;
    completeCalls: number;
    setupCompleteSet: boolean[];
    closed: number;
  } = {
    setup: undefined,
    general: {},
    saved: [],
    filters: [],
    markComplete: async () => {},
    completeCalls: 0,
    setupCompleteSet: [],
    closed: 0,
  };
  return state;
});

vi.mock("../SettingsProvider", () => ({
  useSettingsContext: () => {
    const [settings] = createSignal<{ general: Record<string, unknown> }>({
      general: harness.general,
    });
    return {
      settings,
      saveGeneral: async (g: Record<string, unknown>) => {
        harness.saved.push(g);
        return {};
      },
      setupState: () => harness.setup,
      setSetupComplete: (v: boolean) => harness.setupCompleteSet.push(v),
      closeSetupWizard: () => {
        harness.closed++;
      },
    };
  },
}));

vi.mock("../../store/scan", () => ({
  useScan: () => ({
    scanStatus: () => ({ state: "idle", total: 0, completed: 0, failed: 0 }),
    isActive: () => false,
    startScan: vi.fn(),
  }),
}));

vi.mock("../../api/setup", () => ({
  setupApi: {
    markComplete: async () => {
      harness.completeCalls++;
      await harness.markComplete();
    },
  },
}));

vi.mock("../../api/scanFilters", () => ({
  scanFilters: {
    put: async (f: unknown) => {
      harness.filters.push(f);
      return {};
    },
    browse: async () => [],
  },
}));

vi.mock("../Toast", () => ({ showToast: vi.fn() }));

import SetupWizard from "./SetupWizard";

const GENERAL = {
  include_calibration: true,
  auto_scan_enabled: false,
  auto_scan_interval: 240,
  observer_latitude: 42.5,
  observer_longitude: -71.1,
  observer_timezone: "America/New_York",
  phd2_scan_enabled: true,
  use_imaging_night: true,
};

const setupState = (over: Partial<SetupState> = {}): Record<string, unknown> => ({
  complete: false,
  fits_root: "/data/fits",
  fits_root_exists: true,
  fits_root_has_entries: true,
  https_enabled: false,
  version: "2.4.0",
  ...over,
});

beforeEach(() => {
  harness.setup = setupState();
  harness.general = { ...GENERAL };
  harness.saved = [];
  harness.filters = [];
  harness.completeCalls = 0;
  harness.setupCompleteSet = [];
  harness.closed = 0;
  harness.markComplete = async () => {};
  document.body.innerHTML = "";
});

describe("shouldShowWizard", () => {
  it("shows for an admin whose setup is incomplete", () => {
    expect(shouldShowWizard(true, false, false)).toBe(true);
  });

  it("never shows for a viewer", () => {
    expect(shouldShowWizard(false, false, false)).toBe(false);
    expect(shouldShowWizard(false, false, true)).toBe(false);
  });

  it("stays hidden for an admin whose setup is complete", () => {
    expect(shouldShowWizard(true, true, false)).toBe(false);
  });

  it("reopens on an explicit rerun request", () => {
    expect(shouldShowWizard(true, true, true)).toBe(true);
  });
});

// Dialog renders through a Portal, so every query runs against document.body
// rather than the render container.
const bodyText = (): string => document.body.textContent ?? "";

const buttons = (): HTMLButtonElement[] =>
  Array.from(document.body.querySelectorAll("button"));

const btn = (label: string): HTMLButtonElement => {
  const found = buttons().find((b) => (b.textContent ?? "").trim() === label);
  if (!found) throw new Error(`no button labelled ${label}`);
  return found;
};

// One microtask drain is enough: every wizard action awaits at most a couple
// of already-resolved promises before it settles.
const settle = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

describe("SetupWizard", () => {
  it("opens on the environment step and lists the env checks", () => {
    render(() => <SetupWizard />);
    expect(bodyText()).toContain("Step 1 of 5: Environment");
    expect(bodyText()).toContain("/data/fits");
    expect(bodyText()).toContain("2.4.0");
  });

  it("disables Next and names the env var when the FITS root does not exist", () => {
    harness.setup = setupState({ fits_root_exists: false });
    render(() => <SetupWizard />);
    expect(btn("Next").disabled).toBe(true);
    expect(bodyText()).toContain("GALACTILOG_FITS_HOST_PATH");
  });

  it("moves forward and back between steps", async () => {
    render(() => <SetupWizard />);
    expect(btn("Next").disabled).toBe(false);
    fireEvent.click(btn("Next"));
    await settle();
    expect(bodyText()).toContain("Step 2 of 5: Location");
    fireEvent.click(btn("Back"));
    await settle();
    expect(bodyText()).toContain("Step 1 of 5: Environment");
  });

  it("persists the observer fields when leaving the location step", async () => {
    render(() => <SetupWizard />);
    fireEvent.click(btn("Next"));
    await settle();
    fireEvent.click(btn("Next"));
    await settle();
    expect(bodyText()).toContain("Step 3 of 5: Scan filters");
    expect(harness.saved.length).toBe(1);
    expect(harness.saved[0].observer_latitude).toBe(42.5);
    expect(harness.saved[0].observer_longitude).toBe(-71.1);
    expect(harness.saved[0].observer_timezone).toBe("America/New_York");
  });

  it("warns about UTC fallback when longitude is blank, then advances on a second Next", async () => {
    harness.general = { ...GENERAL, observer_longitude: null };
    render(() => <SetupWizard />);
    fireEvent.click(btn("Next"));
    await settle();
    fireEvent.click(btn("Next"));
    await settle();
    expect(bodyText()).toContain("Imaging-night grouping falls back to UTC");
    expect(bodyText()).toContain("Step 2 of 5: Location");
    fireEvent.click(btn("Next"));
    await settle();
    expect(bodyText()).toContain("Step 3 of 5: Scan filters");
  });

  it("writes preset excludes as folder name rules, not paths", async () => {
    render(() => <SetupWizard />);
    fireEvent.click(btn("Next"));
    await settle();
    fireEvent.click(btn("Next"));
    await settle();
    const boxes = Array.from(
      document.body.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
    );
    const wbpp = boxes.find(
      (b) => (b.parentElement?.textContent ?? "").trim() === "WBPP",
    );
    if (!wbpp) throw new Error("no WBPP preset checkbox");
    fireEvent.click(wbpp);
    fireEvent.click(btn("Next"));
    await settle();
    expect(harness.filters).toEqual([
      {
        include_paths: [],
        exclude_paths: [],
        name_rules: [
          {
            id: "setup-exclude-WBPP",
            action: "exclude",
            type: "substring",
            pattern: "WBPP",
            target: "folder",
            enabled: true,
          },
        ],
      },
    ]);
  });

  it("writes empty filter lists when Scan everything is used", async () => {
    render(() => <SetupWizard />);
    fireEvent.click(btn("Next"));
    await settle();
    fireEvent.click(btn("Next"));
    await settle();
    fireEvent.click(btn("Scan everything"));
    await settle();
    expect(bodyText()).toContain("Step 4 of 5: Ingest options");
    expect(harness.filters).toEqual([
      { include_paths: [], exclude_paths: [], name_rules: [] },
    ]);
  });

  it("marks setup complete and closes when Skip setup is used", async () => {
    render(() => <SetupWizard />);
    fireEvent.click(btn("Skip setup"));
    await settle();
    expect(harness.completeCalls).toBe(1);
    expect(harness.setupCompleteSet).toEqual([true]);
    expect(harness.closed).toBe(1);
  });

  it("still closes when the completion call fails", async () => {
    harness.markComplete = async () => {
      throw new Error("boom");
    };
    render(() => <SetupWizard />);
    fireEvent.click(btn("Skip setup"));
    await settle();
    expect(harness.setupCompleteSet).toEqual([true]);
    expect(harness.closed).toBe(1);
  });
});
