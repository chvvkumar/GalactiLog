import { describe, it, expect, vi } from "vitest";
import { render } from "@solidjs/testing-library";
import type { FrameRecord, SessionDetail, SessionOverview } from "../api/types";

// Locked user ruling 6: the PHD2 provenance hint on the guiding median cell
// belongs to EXPANDED cards only. The parent (TargetDetailPage) passes its
// session cache as `detail` unconditionally and never clears it on collapse,
// and it also fills that cache from the chart checkbox and the Astrobin CSV
// paths with no expand at all. So `props.detail` cannot stand in for "the card
// is open": only `props.isExpanded` can. Without that gate the dagger appears
// on collapsed rows, and its absence stops meaning "this value came from the
// CSV" and starts meaning "nobody has loaded this night yet".
//
// These tests render the real component so the ruling is pinned to the JSX,
// not to a helper the JSX could quietly stop calling.

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    displaySettings: () => undefined,
    customColumns: () => [],
    settings: () => undefined,
    filterAliasMap: () => ({}),
    filterColorMap: () => ({}),
    filterBadgeStyle: () => "solid",
    timezone: () => "UTC",
    use24hTime: () => true,
  }),
}));

// The expanded body mounts two chart.js panels that need a real canvas and the
// graph-settings store. Neither says anything about the header row under test,
// so both are stubbed out rather than propped up.
vi.mock("./SessionMetricsChart", () => ({ default: () => null }));
vi.mock("./Phd2GuideGraph", () => ({ default: () => null }));

import SessionAccordionCard, { RMS_PHD2_GLYPH } from "./SessionAccordionCard";

const frame = (source: FrameRecord["guiding_rms_source"]): FrameRecord => ({
  timestamp: "2026-07-14T22:03:11Z",
  filter_used: "Ha",
  exposure_time: 300,
  median_hfr: 2.4,
  eccentricity: 0.42,
  sensor_temp: -10,
  gain: 100,
  file_name: "Ha_300s_0001.fits",
  image_id: "img-1",
  file_path: "/data/Ha_300s_0001.fits",
  file_size: 41943040,
  source_relative: "Ha_300s_0001.fits",
  hfr_stdev: 0.11,
  fwhm: 3.1,
  detected_stars: 812,
  guiding_rms_arcsec: 0.71,
  guiding_rms_ra_arcsec: 0.41,
  guiding_rms_dec_arcsec: 0.58,
  guiding_rms_source: source,
  adu_stdev: 120,
  adu_mean: 1450,
  adu_median: 1400,
  adu_min: 900,
  adu_max: 65535,
  focuser_position: 18400,
  focuser_temp: 11.2,
  rotator_position: 90,
  pier_side: "West",
  airmass: 1.14,
  ambient_temp: 12.4,
  dew_point: 6.1,
  humidity: 64,
  pressure: 1013.2,
  wind_speed: 3.1,
  wind_direction: 210,
  wind_gust: 5.4,
  cloud_cover: 2,
  sky_quality: 20.8,
  rig: "140APO",
});

const session: SessionOverview = {
  session_date: "2026-07-14",
  integration_seconds: 7200,
  frame_count: 24,
  median_hfr: 2.4,
  median_eccentricity: 0.42,
  filters_used: ["Ha"],
  camera: "ASI2600MM",
  telescope: "140APO",
  median_fwhm: 3.1,
  median_detected_stars: 812,
  median_guiding_rms_arcsec: 0.71,
  filter_medians: [],
  has_notes: false,
  rig_count: 1,
  ra: 202.4696,
  dec: 47.1953,
  position_angle: null,
};

const detail: SessionDetail = {
  target_name: "M51",
  session_date: "2026-07-14",
  thumbnail_url: null,
  frame_count: 24,
  integration_seconds: 7200,
  median_hfr: 2.4,
  median_eccentricity: 0.42,
  filters_used: { Ha: 24 },
  equipment: { camera: "ASI2600MM", telescope: "140APO" },
  raw_reference_header: null,
  min_hfr: 2.1,
  max_hfr: 2.9,
  min_eccentricity: 0.31,
  max_eccentricity: 0.55,
  sensor_temp: -10,
  sensor_temp_min: -10,
  sensor_temp_max: -9,
  gain: 100,
  offset: 50,
  exposure_times: [300],
  first_frame_time: "2026-07-14T21:42:27Z",
  last_frame_time: "2026-07-14T23:51:12Z",
  filter_details: [],
  insights: [],
  frames: [frame("phd2"), frame("phd2")],
  median_fwhm: 3.1,
  min_fwhm: 2.8,
  max_fwhm: 3.6,
  median_guiding_rms: 0.71,
  min_guiding_rms: 0.62,
  max_guiding_rms: 0.9,
  median_detected_stars: 812,
  median_airmass: 1.14,
  median_ambient_temp: 12.4,
  median_humidity: 64,
  median_cloud_cover: 2,
  notes: null,
  rigs: [],
  session_baselines: {},
  rig_baselines: {},
};

const columns = {
  hfr: true,
  eccentricity: true,
  fwhm: false,
  detected_stars: false,
  guiding_rms: true,
};

/** The collapsed header row's guiding cell, which is the only cell carrying
 *  `text-metric-guiding` on that row. */
function guidingCell(container: HTMLElement): HTMLElement {
  const cell = container.querySelector<HTMLElement>("td.text-metric-guiding");
  if (!cell) throw new Error("guiding median cell not rendered");
  return cell;
}

function renderCard(isExpanded: boolean, sessionDetail: SessionDetail | null) {
  return render(() => (
    <table>
      <SessionAccordionCard
        session={session}
        isExpanded={isExpanded}
        onToggle={() => {}}
        detail={sessionDetail}
        visibleColumns={columns}
      />
    </table>
  ));
}

describe("collapsed-row guiding provenance", () => {
  it("shows no dagger on a collapsed row whose detail is already cached", () => {
    const { container } = renderCard(false, detail);
    const cell = guidingCell(container);
    expect(cell.textContent).not.toContain(RMS_PHD2_GLYPH);
  });

  it("shows no provenance tooltip on a collapsed row whose detail is already cached", () => {
    const { container } = renderCard(false, detail);
    expect(guidingCell(container).getAttribute("title")).toBeNull();
  });

  it("still renders the median value itself on a collapsed row", () => {
    const { container } = renderCard(false, detail);
    expect(guidingCell(container).textContent).toContain("0.71");
  });

  it("renders identically whether or not the parent cache happens to hold the night", () => {
    // The whole point of ruling 6: two collapsed rows with the same provenance
    // must not differ because the user expanded or charted one of them.
    const cached = guidingCell(renderCard(false, detail).container);
    const uncached = guidingCell(renderCard(false, null).container);
    expect(cached.textContent).toBe(uncached.textContent);
    expect(cached.getAttribute("title")).toBe(uncached.getAttribute("title"));
  });
});

describe("expanded-row guiding provenance", () => {
  it("marks the median value with the dagger once the card is open", () => {
    const { container } = renderCard(true, detail);
    expect(guidingCell(container).textContent).toContain(RMS_PHD2_GLYPH);
  });

  it("names the guide log in the tooltip once the card is open", () => {
    const { container } = renderCard(true, detail);
    expect(guidingCell(container).getAttribute("title")).toBe(
      "Median RMS from PHD2 guide logs"
    );
  });

  it("says nothing about a source the frames do not carry", () => {
    const csvNight: SessionDetail = { ...detail, frames: [frame("csv")] };
    const { container } = renderCard(true, csvNight);
    const cell = guidingCell(container);
    expect(cell.textContent).not.toContain(RMS_PHD2_GLYPH);
    expect(cell.getAttribute("title")).toBe("Median RMS from NINA CSV sidecars");
  });
});
