import { describe, it, expect, vi } from "vitest";
import { render } from "@solidjs/testing-library";
import { Router, Route } from "@solidjs/router";
import GuidingScorecard, { GuidingEmptyNotice } from "./GuidingScorecard";
import type { GuidingRig } from "../api/types";

let admin = true;
vi.mock("./AuthProvider", () => ({ useAuth: () => ({ isAdmin: () => admin }) }));

function renderNotice(unmapped: number) {
  return render(() => (
    <Router>
      <Route path="/" component={() => <GuidingEmptyNotice unmapped={unmapped} />} />
    </Router>
  ));
}

function rig(overrides: Partial<GuidingRig> = {}): GuidingRig {
  return {
    telescope: "Esprit 100",
    session_count: 12,
    gated_session_count: 2,
    guided_hours: 34.5,
    rms_total_arcsec: 0.61,
    rms_ra_arcsec: 0.42,
    rms_dec_arcsec: 0.44,
    rms_total_filtered_arcsec: 0.55,
    ra_dec_ratio: 1.05,
    peak_ra_arcsec: 2.1,
    peak_dec_arcsec: 1.9,
    star_lost_pct: 0.8,
    unguided_minutes: 12.5,
    dither_count: 80,
    settle_median_s: 3.2,
    settle_fail_pct: 4.0,
    exposure_ms_values: [1000, 2000],
    first_night: "2026-01-02",
    last_night: "2026-08-20",
    ...overrides,
  };
}

describe("GuidingScorecard", () => {
  it("renders one row per rig with the session and short-session counts", () => {
    const rigs = [rig(), rig({ telescope: "RedCat 51", session_count: 5, gated_session_count: 0 })];
    const { getByText, getAllByText } = render(() => <GuidingScorecard rigs={rigs} />);
    expect(getByText("Esprit 100")).toBeDefined();
    expect(getByText("RedCat 51")).toBeDefined();
    expect(getByText("12")).toBeDefined();
    expect(getByText("2 too short to score")).toBeDefined();
    expect(getAllByText(/Guide exposure: 1000, 2000 ms/).length).toBe(2);
  });

  it("renders the em dash glyph for null metrics", () => {
    const rigs = [rig({ rms_total_arcsec: null, ra_dec_ratio: null, settle_median_s: null })];
    const { getAllByText } = render(() => <GuidingScorecard rigs={rigs} />);
    expect(getAllByText("—").length).toBe(3);
  });

  it("shows the empty state when there are no rigs", () => {
    const { getByText } = render(() => <GuidingScorecard rigs={[]} />);
    expect(getByText("No guiding data available")).toBeDefined();
  });
});

describe("GuidingEmptyNotice", () => {
  it("links an admin to the PHD2 profile mapping when profiles are unmapped", async () => {
    admin = true;
    const { findByText } = renderNotice(7);
    const link = await findByText("Map profiles in Settings");
    expect(link.getAttribute("href")).toBe("/settings?tab=equipment#phd2-profiles");
    expect(link.parentElement?.textContent).toContain(
      "7 guiding sessions found but no PHD2 profile is mapped to a telescope.",
    );
  });

  it("links an admin to the guide log setting when nothing is catalogued", async () => {
    admin = true;
    const { findByText } = renderNotice(0);
    const link = await findByText("Enable guide log scanning");
    expect(link.getAttribute("href")).toBe("/settings?tab=scan#guide-logs");
  });

  it("renders no link for a viewer and says an admin must do it", async () => {
    admin = false;
    const { container, findByText } = renderNotice(7);
    await findByText(/An admin can map profiles in Settings/);
    expect(container.querySelector("a")).toBeNull();
  });
});
