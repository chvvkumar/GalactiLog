import { describe, it, expect } from "vitest";
import { render } from "@solidjs/testing-library";
import GuidingSettingsTable from "./GuidingSettingsTable";
import type { GuidingSettingsRow } from "../api/types";

function row(overrides: Partial<GuidingSettingsRow>): GuidingSettingsRow {
  return {
    telescope: "Esprit 100",
    algo_ra: "Hysteresis",
    algo_dec: "ResistSwitch",
    exposure_ms: 2000,
    dec_guide_mode: "Auto",
    session_count: 10,
    guided_hours: 20,
    rms_total_arcsec: 0.6,
    rms_ra_arcsec: 0.4,
    rms_dec_arcsec: 0.4,
    star_lost_pct: 1.0,
    ...overrides,
  };
}

const rows: GuidingSettingsRow[] = [
  row({ algo_ra: "PPEC", rms_total_arcsec: 0.5, session_count: 6 }),
  row({ algo_ra: "Hysteresis", rms_total_arcsec: 0.7, session_count: 10 }),
  row({ algo_ra: "Lowpass2", rms_total_arcsec: 0.9, session_count: 2 }),
  row({ telescope: "RedCat 51", algo_ra: "ZFilter", rms_total_arcsec: null, session_count: 4 }),
];

describe("GuidingSettingsTable", () => {
  it("highlights the lowest non-null rms_total row within each rig", () => {
    const { getByText } = render(() => <GuidingSettingsTable settings={rows} />);
    const best = getByText("PPEC").closest("tr")!;
    const other = getByText("Hysteresis").closest("tr")!;
    expect(best.classList.contains("text-theme-success")).toBe(true);
    expect(other.classList.contains("text-theme-success")).toBe(false);
  });

  it("renders rows with fewer than 3 sessions in the tertiary text class", () => {
    const { getByText } = render(() => <GuidingSettingsTable settings={rows} />);
    const weak = getByText("Lowpass2").closest("tr")!;
    const strong = getByText("PPEC").closest("tr")!;
    expect(weak.classList.contains("text-theme-text-tertiary")).toBe(true);
    expect(strong.classList.contains("text-theme-text-tertiary")).toBe(false);
  });

  it("groups rows under one heading row per rig", () => {
    const { getByText } = render(() => <GuidingSettingsTable settings={rows} />);
    expect(getByText("Esprit 100")).toBeDefined();
    expect(getByText("RedCat 51")).toBeDefined();
  });
});
