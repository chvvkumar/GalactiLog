import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import GuidingAltitude from "./GuidingAltitude";
import type { GuidingAltitudeBandRow } from "../api/types";

function band(overrides: Partial<GuidingAltitudeBandRow> = {}): GuidingAltitudeBandRow {
  return {
    telescope: "Esprit 100",
    band: ">60",
    session_count: 100,
    rms_total_arcsec: 0.8,
    rms_ra_arcsec: 0.5,
    rms_dec_arcsec: 0.6,
    ...overrides,
  };
}

const THREE: GuidingAltitudeBandRow[] = [
  band({ band: "<30", session_count: 310, rms_total_arcsec: 1.42, rms_ra_arcsec: 0.85, rms_dec_arcsec: 1.13 }),
  band({ band: "30-60", session_count: 2100, rms_total_arcsec: 1.05 }),
  band({ band: ">60", session_count: 2159, rms_total_arcsec: 0.88 }),
];

describe("GuidingAltitude", () => {
  it("renders one dome per rig", () => {
    const rows = [...THREE, band({ telescope: "RedCat 51", band: "<30", rms_total_arcsec: 1.9 })];
    const { getByLabelText } = render(() => <GuidingAltitude altitudeBands={rows} />);
    expect(getByLabelText("Esprit 100 sky arc")).toBeDefined();
    expect(getByLabelText("RedCat 51 sky arc")).toBeDefined();
  });

  it("prints the RMS and the ratio to the rig's above-60 band in each wedge", () => {
    const { getByLabelText } = render(() => <GuidingAltitude altitudeBands={THREE} />);
    const dome = getByLabelText("Esprit 100 sky arc").textContent ?? "";
    expect(dome).toContain("1.42");
    expect(dome).toContain("×1.61");
    expect(dome).toContain("×1.00");
    expect(dome).toContain("n 310");
  });

  it("renders a muted wedge marked no data when a band is missing or has no RMS", () => {
    const rows = [THREE[0], band({ band: "30-60", rms_total_arcsec: null })];
    const { container, getAllByText } = render(() => <GuidingAltitude altitudeBands={rows} />);
    expect(getAllByText("no data").length).toBe(2);
    expect(container.querySelectorAll(".skyarc-s0").length).toBe(2);
  });

  it("shows the RA and Dec split in a tooltip when a wedge is hovered", () => {
    const { container } = render(() => <GuidingAltitude altitudeBands={THREE} />);
    const tip = () => container.querySelector('[role="status"]');
    expect(tip()).toBeNull();
    const wedge = container.querySelector("path.skyarc-wedge")!;
    fireEvent.pointerMove(wedge, { clientX: 40, clientY: 60 });
    const text = tip()?.textContent ?? "";
    expect(text).toContain("Esprit 100");
    expect(text).toContain("RMS RA0.85 arcsec");
    expect(text).toContain("RMS Dec1.13 arcsec");
    fireEvent.pointerLeave(wedge);
    expect(tip()).toBeNull();
  });

  it("lists every row in the table view", () => {
    const { container } = render(() => <GuidingAltitude altitudeBands={THREE} />);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    expect(container.querySelector("details summary")?.textContent).toBe("Table view");
  });
});
