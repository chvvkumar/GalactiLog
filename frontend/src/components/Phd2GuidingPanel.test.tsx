import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import Phd2GuidingPanel from "./Phd2GuidingPanel";
import type { Phd2NightSummary } from "../api/types";

const summary: Phd2NightSummary = {
  session_count: 6,
  gated_session_count: 2,
  frame_count: 4210,
  rms_ra_arcsec: 0.412,
  rms_dec_arcsec: 0.587,
  rms_total_arcsec: 0.717,
  drop_count: 9,
  max_drop_run: 4,
  unguided_seconds: 95,
  dither_count: 12,
  settle_failed_count: 1,
  settle_median_s: 6.4,
  cal_issues: ["Orthogonality", "Rates"],
  profiles: ["140APO_AM5N_ASI174MM"],
};

describe("Phd2GuidingPanel", () => {
  it("shows total, RA and Dec RMS to two decimals", () => {
    const { getByText, container } = render(() => <Phd2GuidingPanel summary={summary} />);
    expect(getByText("0.72″")).toBeTruthy();
    expect(container.textContent).toContain("0.41″");
    expect(container.textContent).toContain("0.59″");
  });

  it("notes how many sessions were too short to grade", () => {
    const { container } = render(() => <Phd2GuidingPanel summary={summary} />);
    expect(container.textContent).toContain("6");
    expect(container.textContent).toContain("2 too short to grade");
  });

  it("humanizes unguided time and shows the longest drop run", () => {
    const { container } = render(() => <Phd2GuidingPanel summary={summary} />);
    expect(container.textContent).toContain("9");
    expect(container.textContent).toContain("1m 35s");
    expect(container.textContent).toContain("longest run 4");
  });

  it("renders one badge per calibration issue", () => {
    const { getByText } = render(() => <Phd2GuidingPanel summary={summary} />);
    expect(getByText("Orthogonality").className).toContain("text-theme-warning");
    expect(getByText("Rates").className).toContain("text-theme-warning");
  });

  it("omits the gated note and the badges when there is nothing to report", () => {
    const clean: Phd2NightSummary = { ...summary, gated_session_count: 0, cal_issues: [] };
    const { container, queryByText } = render(() => <Phd2GuidingPanel summary={clean} />);
    expect(container.textContent).not.toContain("too short to grade");
    expect(queryByText("Orthogonality")).toBeNull();
  });

  it("collapses and expands the strip", () => {
    const { container, getByRole } = render(() => <Phd2GuidingPanel summary={summary} />);
    expect(container.textContent).toContain("Dithers");
    // The collapse is a grid-template-rows animation, so the body stays in the
    // DOM at zero height rather than unmounting; assert the collapsed wrapper.
    expect(container.querySelector(".grid-rows-\\[0fr\\]")).toBeNull();
    fireEvent.click(getByRole("button"));
    expect(container.querySelector(".grid-rows-\\[0fr\\]")).toBeTruthy();
  });

  it("renders a dash for a night with no gradeable RMS", () => {
    const ungraded: Phd2NightSummary = {
      ...summary,
      rms_total_arcsec: null,
      rms_ra_arcsec: null,
      rms_dec_arcsec: null,
      settle_median_s: null,
    };
    const { container } = render(() => <Phd2GuidingPanel summary={ungraded} />);
    expect(container.textContent).toContain("—");
  });
});
