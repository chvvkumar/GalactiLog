import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { Suspense } from "solid-js";
import { QueryClient, QueryClientProvider } from "@tanstack/solid-query";

// Reproduces the "opening the guide graph refreshes the whole page" bug from
// the Phase 1 soak.
//
// Root cause: @tanstack/solid-query's useQuery is backed by createResource, so
// reading `data` for a key with nothing cached re-enters a pending resource and
// suspends the NEAREST Suspense boundary. The app has exactly one, wrapping the
// whole router (index.tsx:32), and its fallback is a full-screen "Loading...".
// The guide graph's two queries only start when the section is expanded, long
// after that boundary resolved, so the first expand blanked the entire page and
// then rebuilt it, resetting the scroll position and every open panel.
//
// The fix puts the queries and their effects in a child component under a
// Suspense boundary local to the panel. This test asserts both halves: the
// local fallback appears (so the reads really do suspend) and the app-level
// fallback never does (so the blast radius is the panel).

const sessionsResponse = {
  sessions: [
    {
      id: "s-1",
      started_at: "2026-07-14T21:42:27Z",
      ended_at: "2026-07-14T22:04:27Z",
      duration_s: 1320,
      frame_count: 3,
      equipment_profile: "140APO_AM5N_ASI174MM",
      telescope: "140APO",
      pixel_scale_arcsec: 1.54,
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
    },
  ],
};

const framesResponse = {
  pixel_scale_arcsec: 1.54,
  started_at: "2026-07-14T21:42:27Z",
  frames: [
    { t: 0, ra: 0.1, dec: -0.2, ra_pulse_ms: 0, ra_dir: "", dec_pulse_ms: 0, dec_dir: "", snr: 20, mass: 1, dropped: false },
    { t: 3, ra: 0.4, dec: 0.3, ra_pulse_ms: 0, ra_dir: "", dec_pulse_ms: 0, dec_dir: "", snr: 20, mass: 1, dropped: false },
    { t: 6, ra: -0.5, dec: 0.1, ra_pulse_ms: 0, ra_dir: "", dec_pulse_ms: 0, dec_dir: "", snr: 20, mass: 1, dropped: false },
  ],
  events: [],
};

// A holder rather than a bare `let`: the sessions request stays pending until
// the test releases it, which is the whole point of the first assertion block.
const pending: { releaseSessions: (() => void) | null } = { releaseSessions: null };

vi.mock("../api/generated/client", () => ({
  apiClient: {
    GET: vi.fn((path: string) => {
      if (path === "/api/phd2/sessions") {
        return new Promise((resolve) => {
          pending.releaseSessions = () => resolve({ data: sessionsResponse, response: { ok: true } });
        });
      }
      return Promise.resolve({ data: framesResponse, response: { ok: true } });
    }),
  },
}));

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    timezone: () => "UTC",
    use24hTime: () => false,
  }),
}));

// jsdom has no 2d canvas context, so chart.js cannot construct. The panel's
// DOM, not its pixels, is what this test is about.
vi.mock("chart.js", () => {
  class FakeChart {
    data: unknown;
    options: unknown;
    scales: Record<string, unknown> = {};
    constructor(_canvas: unknown, config: { data: unknown; options: unknown }) {
      this.data = config.data;
      this.options = config.options;
    }
    update() {}
    destroy() {}
  }
  return { Chart: FakeChart };
});
vi.mock("../utils/chartRegistry", () => ({}));

import Phd2GuideGraph from "./Phd2GuideGraph";

function Harness() {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Suspense fallback={<div data-testid="app-fallback">Loading...</div>}>
        <div data-testid="page">The rest of the target page</div>
        <Phd2GuideGraph sessionDate="2026-07-14" telescope={null} />
      </Suspense>
    </QueryClientProvider>
  );
}

const settle = async (ticks = 8) => {
  for (let i = 0; i < ticks; i++) {
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
  }
};

describe("Phd2GuideGraph expand", () => {
  it("suspends inside the panel, not at the app boundary", async () => {
    const { getByRole, queryByTestId, getByText, queryByText } = render(() => <Harness />);

    const page = queryByTestId("page") as HTMLElement;
    expect(page).not.toBeNull();
    expect(queryByTestId("app-fallback")).toBeNull();

    fireEvent.click(getByRole("button", { name: "Guide Graph (PHD2)" }));
    await settle(3);

    // The sessions request is still in flight: the panel shows its own
    // fallback, the app-level one is untouched, and the surrounding page has
    // not been detached and rebuilt.
    expect(queryByText("Loading guiding data...")).not.toBeNull();
    expect(queryByTestId("app-fallback")).toBeNull();
    expect(page.isConnected).toBe(true);
    expect(queryByTestId("page")).toBe(page);

    pending.releaseSessions?.();
    await settle();

    expect(queryByTestId("app-fallback")).toBeNull();
    expect(queryByText("Loading guiding data...")).toBeNull();
    expect(
      getByText("Scroll to zoom, Shift+scroll for vertical, drag to pan, double-click to reset")
    ).toBeTruthy();
    // Same DOM node throughout: the page was never swapped for a fallback.
    expect(page.isConnected).toBe(true);
  });

  it("gives the toggle an explicit button type so it can never submit a form", () => {
    const { getByRole } = render(() => <Harness />);
    const toggle = getByRole("button", { name: "Guide Graph (PHD2)" }) as HTMLButtonElement;
    expect(toggle.getAttribute("type")).toBe("button");
  });
});
