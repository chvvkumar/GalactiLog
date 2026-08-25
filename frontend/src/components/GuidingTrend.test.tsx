import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import GuidingTrend from "./GuidingTrend";
import type { GuidingMonthlyRow } from "../api/types";

function month(telescope: string, m: string, rms: number | null, lost = 1.5): GuidingMonthlyRow {
  return {
    telescope,
    month: m,
    session_count: 3,
    guided_hours: 6,
    rms_total_arcsec: rms,
    rms_ra_arcsec: rms,
    rms_dec_arcsec: rms,
    star_lost_pct: lost,
  };
}

const monthly: GuidingMonthlyRow[] = [
  month("Esprit 100", "2026-05", 0.55),
  month("Esprit 100", "2026-06", null),
  month("Esprit 100", "2026-07", 0.72),
  month("RedCat 51", "2026-07", 1.1),
];

describe("GuidingTrend", () => {
  it("selects the first rig by default and switches bars when another rig is clicked", () => {
    const { getByText, queryByText, getByRole } = render(() => <GuidingTrend monthly={monthly} />);
    expect(getByText("2026-05")).toBeDefined();
    expect(getByText("0.55")).toBeDefined();
    expect(queryByText("1.10")).toBeNull();

    fireEvent.click(getByRole("button", { name: "RedCat 51" }));
    expect(getByText("1.10")).toBeDefined();
    expect(queryByText("2026-05")).toBeNull();
  });

  it("renders an empty slot with the month label when rms is null", () => {
    const { getByText, queryByText } = render(() => <GuidingTrend monthly={monthly} />);
    expect(getByText("2026-06")).toBeDefined();
    expect(queryByText("—")).toBeNull();
  });

  it("hides the rig selector when only one rig is present", () => {
    const { queryByRole } = render(() => (
      <GuidingTrend monthly={monthly.filter((m) => m.telescope === "Esprit 100")} />
    ));
    expect(queryByRole("button", { name: "Esprit 100" })).toBeNull();
  });
});
