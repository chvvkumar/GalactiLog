import { describe, it, expect } from "vitest";
import { render } from "@solidjs/testing-library";
import GuidingScorecard, { guidingEmptyMessage } from "./GuidingScorecard";
import type { GuidingRig } from "../api/types";

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
  it("renders one row per rig with the session and gated counts", () => {
    const rigs = [rig(), rig({ telescope: "RedCat 51", session_count: 5, gated_session_count: 0 })];
    const { getByText, getAllByText } = render(() => <GuidingScorecard rigs={rigs} />);
    expect(getByText("Esprit 100")).toBeDefined();
    expect(getByText("RedCat 51")).toBeDefined();
    expect(getByText("12")).toBeDefined();
    expect(getByText("2 gated")).toBeDefined();
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

describe("guidingEmptyMessage", () => {
  it("returns null when rigs exist", () => {
    expect(guidingEmptyMessage(1, 3)).toBeNull();
  });

  it("names the Scan Manager when nothing is catalogued", () => {
    expect(guidingEmptyMessage(0, 0)).toBe(
      "No PHD2 guide logs catalogued. Enable guide log scanning in Scan Manager.",
    );
  });

  it("counts unmapped sessions when only unmapped profiles exist", () => {
    expect(guidingEmptyMessage(0, 7)).toBe(
      "7 guiding sessions found but no PHD2 profile is mapped to a telescope. Map profiles in Settings.",
    );
  });
});
