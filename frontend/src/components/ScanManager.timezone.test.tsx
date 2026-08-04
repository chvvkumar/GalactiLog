import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";
import { ApiError } from "../api/unwrap";

// Observer timezone control in Settings > Library > Observer Location.
//
// The control is a dropdown of IANA zone names sourced from
// Intl.supportedValuesOf. An unset value must stay empty: the backend guard
// observer_timezone_is_set treats an empty string as "not configured" and
// refuses to interpret PHD2 guide logs with a clock nobody chose.

interface GeneralStub {
  // Indexed so the stub drops straight into the Record<string, unknown> the
  // mocked settings context passes around.
  [key: string]: unknown;
  include_calibration: boolean;
  auto_scan_enabled: boolean;
  auto_scan_interval: number;
  observer_name: string | null;
  observer_latitude: number | null;
  observer_longitude: number | null;
  observer_timezone: string;
  phd2_scan_enabled: boolean;
  timezone: string;
}

const harness = vi.hoisted(() => {
  const state: {
    general: Record<string, unknown>;
    saveGeneral: (g: Record<string, unknown>) => Promise<unknown>;
    toasts: { message: string; severity?: string }[];
  } = {
    general: {},
    saveGeneral: async () => ({}),
    toasts: [],
  };
  return state;
});

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => {
    const [settings, setSettings] = createSignal<{ general: Record<string, unknown> }>({
      general: harness.general,
    });
    return {
      settings,
      saveGeneral: async (g: Record<string, unknown>) => {
        const result = await harness.saveGeneral(g);
        harness.general = g;
        setSettings({ general: g });
        return result;
      },
    };
  },
}));

vi.mock("./AuthProvider", () => ({
  useAuth: () => ({ isAdmin: () => true }),
}));

vi.mock("../store/scan", () => ({
  useScan: () => ({
    scanStatus: () => ({ state: "idle" }),
    isActive: () => false,
    stopping: () => false,
    startScan: vi.fn(),
    startRegeneration: vi.fn(),
    stopScan: vi.fn(),
    stopPolling: vi.fn(),
  }),
}));

vi.mock("../store/stats", () => ({
  useStats: () => ({ stats: () => null }),
}));

vi.mock("../store/rebuild", () => ({
  rebuildStatus: () => ({ state: "idle" }),
  fetchRebuildStatus: vi.fn(),
}));

vi.mock("../api/generated/client", () => ({
  apiClient: {
    GET: vi.fn(() => Promise.resolve({ data: {}, response: { ok: true } })),
  },
}));

vi.mock("../api/scanFilters", () => ({
  scanFilters: { get: vi.fn(() => Promise.resolve({ configured: true })) },
}));

vi.mock("./Toast", () => ({
  showToast: (message: string, severity?: string) => {
    harness.toasts.push({ message, severity });
  },
}));

vi.mock("./DatabaseOverview", () => ({ default: () => null }));
vi.mock("./CaptureActivity", () => ({ default: () => null }));
vi.mock("./ScanControls", () => ({ default: () => null }));
vi.mock("./ConfirmDialog", () => ({ default: () => null }));
vi.mock("./ActivityFeed", () => ({ default: () => null }));
vi.mock("./MaintenanceActions", () => ({ default: () => null }));
vi.mock("./ScanFiltersPanel", () => ({ default: () => null }));
vi.mock("./ScanFiltersOnboarding", () => ({ default: () => null }));

import ScanManager from "./ScanManager";

const baseGeneral = (overrides: Partial<GeneralStub> = {}): GeneralStub => ({
  include_calibration: true,
  auto_scan_enabled: false,
  auto_scan_interval: 240,
  observer_name: null,
  observer_latitude: null,
  observer_longitude: null,
  observer_timezone: "",
  phd2_scan_enabled: true,
  timezone: "America/Chicago",
  ...overrides,
});

const flush = async () => {
  for (let i = 0; i < 4; i++) {
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
  }
};

const openObserverHelp = (container: HTMLElement) => {
  const heading = Array.from(container.querySelectorAll("h4")).find(
    (h) => h.textContent === "Observer Location"
  );
  const glyph = heading?.parentElement?.querySelector("button");
  if (!glyph) throw new Error("Observer Location help glyph not found");
  fireEvent.click(glyph);
};

describe("observer timezone control", () => {
  beforeEach(() => {
    harness.general = baseGeneral();
    harness.saveGeneral = async () => ({});
    harness.toasts = [];
  });

  it("shows a placeholder and selects no zone when nothing is stored", async () => {
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("");
    expect(select.options[select.selectedIndex].textContent).toBe("Select a timezone");
  });

  it("saves the exact IANA name picked from the list", async () => {
    const saved: Record<string, unknown>[] = [];
    harness.saveGeneral = async (g) => {
      saved.push(g);
      return {};
    };
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Europe/Helsinki" } });
    await flush();
    expect(saved.length).toBe(1);
    expect(saved[0].observer_timezone).toBe("Europe/Helsinki");
  });

  it("offers a display-timezone entry that stores the real IANA zone", async () => {
    const saved: Record<string, unknown>[] = [];
    harness.saveGeneral = async (g) => {
      saved.push(g);
      return {};
    };
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    const entry = Array.from(select.options).find((o) => o.textContent?.startsWith("Same as display"));
    expect(entry).toBeTruthy();
    expect(entry!.textContent).toContain("Central Time");
    expect(entry!.textContent).toContain("America/Chicago");
    expect(entry!.value).toBe("America/Chicago");
    fireEvent.change(select, { target: { value: entry!.value } });
    await flush();
    expect(saved.length).toBe(1);
    expect(saved[0].observer_timezone).toBe("America/Chicago");
  });

  it("labels the display entry with the zone alone when there is no name for it", async () => {
    harness.general = baseGeneral({ timezone: "Etc/GMT+3" });
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    const entry = Array.from(select.options).find((o) => o.textContent?.startsWith("Same as display"));
    expect(entry!.textContent).toBe("Same as display (Etc/GMT+3)");
  });

  it("preselects a stored zone", async () => {
    harness.general = baseGeneral({ observer_timezone: "Europe/Helsinki" });
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    expect(select.value).toBe("Europe/Helsinki");
    expect(select.options[select.selectedIndex].textContent).toBe("Europe/Helsinki");
  });

  it("keeps a stored zone visible even when the runtime does not list it", async () => {
    harness.general = baseGeneral({ observer_timezone: "US/Central" });
    const { getByLabelText } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    expect(select.value).toBe("US/Central");
    expect(select.options[select.selectedIndex].textContent).toBe("US/Central");
  });

  it("drops the helper line and explains the container clock in the help glyph", async () => {
    const { container } = render(() => <ScanManager />);
    await flush();
    expect(container.textContent).not.toContain("Leave empty to use the server timezone.");
    openObserverHelp(container as HTMLElement);
    const dialog = container.ownerDocument.querySelector('[role="dialog"]');
    expect(dialog).toBeTruthy();
    const text = dialog!.textContent ?? "";
    expect(text).toContain("UTC");
    expect(text).toContain("PHD2");
    expect(text.toLowerCase()).toContain("container");
  });

  it("degrades to a text input when the runtime cannot list zones", async () => {
    const original = Object.getOwnPropertyDescriptor(Intl, "supportedValuesOf");
    Object.defineProperty(Intl, "supportedValuesOf", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    try {
      const { getByLabelText } = render(() => <ScanManager />);
      await flush();
      const field = getByLabelText("Timezone") as HTMLInputElement;
      expect(field.tagName).toBe("INPUT");
      expect(field.type).toBe("text");
    } finally {
      if (original) Object.defineProperty(Intl, "supportedValuesOf", original);
    }
  });

  it("surfaces a save the backend rejected", async () => {
    harness.saveGeneral = async () => {
      throw new ApiError(422, "Unknown time zone: Europe/Helsinki");
    };
    const { getByLabelText, container } = render(() => <ScanManager />);
    await flush();
    const select = getByLabelText("Timezone") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Europe/Helsinki" } });
    await flush();
    expect(container.textContent).toContain("Unknown time zone: Europe/Helsinki");
    expect(harness.toasts.some((t) => t.message.includes("Unknown time zone"))).toBe(true);
  });
});

describe("timezone list helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when Intl cannot enumerate zones", async () => {
    const { supportedTimeZones } = await import("../utils/dateTime");
    const original = Object.getOwnPropertyDescriptor(Intl, "supportedValuesOf");
    Object.defineProperty(Intl, "supportedValuesOf", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    try {
      expect(supportedTimeZones()).toBeNull();
    } finally {
      if (original) Object.defineProperty(Intl, "supportedValuesOf", original);
    }
  });

  it("lists real IANA zones when Intl can enumerate them", async () => {
    const { supportedTimeZones } = await import("../utils/dateTime");
    const zones = supportedTimeZones();
    expect(zones).not.toBeNull();
    expect(zones!.length).toBeGreaterThan(100);
    expect(zones).toContain("America/Chicago");
  });

  it("gives a descriptive name for a zone", async () => {
    const { timezoneFriendlyName } = await import("../utils/dateTime");
    expect(timezoneFriendlyName("America/Chicago")).toBe("Central Time");
    expect(timezoneFriendlyName("Not/AZone")).toBe("Not/AZone");
  });

  it("prefers a name over a bare offset", async () => {
    const { timezoneFriendlyName } = await import("../utils/dateTime");
    expect(timezoneFriendlyName("UTC")).toBe("Coordinated Universal Time");
    expect(timezoneFriendlyName("Etc/GMT+3")).toBe("Etc/GMT+3");
  });
});
