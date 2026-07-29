import { describe, it, expect } from "vitest";
import {
  guideRangeCaption,
  guideTimeTick,
  guideTooltipLabel,
  guideTooltipTitle,
  isScaleMissing,
  sessionOptionLabel,
} from "./Phd2GuideGraph";
import { ARCSEC, formatArcsec } from "../utils/format";
import { clockRange, clockTime, clockTimeWithSeconds } from "../utils/phd2Format";
import type { Phd2Frame, Phd2FramesResponse, Phd2SessionSummary } from "../api/types";

const session: Phd2SessionSummary = {
  id: "s-1",
  started_at: "2026-07-14T21:42:27Z",
  ended_at: "2026-07-14T22:04:27Z",
  duration_s: 1320,
  frame_count: 2640,
  equipment_profile: "140APO_AM5N_ASI174MM",
  telescope: "140APO",
  pixel_scale_arcsec: 1.54,
  rms_ra_arcsec: 0.41,
  rms_dec_arcsec: 0.58,
  rms_total_arcsec: 0.71,
  peak_ra_arcsec: 2.2,
  peak_dec_arcsec: 3.1,
  drop_count: 2,
  max_drop_run: 1,
  unguided_seconds: 3,
  dither_count: 5,
  settle_count: 5,
  settle_failed_count: 0,
  settle_median_s: 6.2,
  snr_mean: 28.4,
  star_mass_mean: 1702,
  last_cal_issue: null,
  pier_side: "West",
  gated: false,
};

describe("sessionOptionLabel", () => {
  it("labels a session by start time and duration", () => {
    expect(sessionOptionLabel(session, "9:42 PM", false)).toBe("9:42 PM · 22m");
  });

  it("appends the profile when the night mixes profiles", () => {
    expect(sessionOptionLabel(session, "9:42 PM", true)).toBe(
      "9:42 PM · 22m · 140APO_AM5N_ASI174MM"
    );
  });

  it("marks a session that was too short to grade", () => {
    expect(sessionOptionLabel({ ...session, gated: true, duration_s: 90 }, "9:42 PM", false)).toBe(
      "9:42 PM · 1m 30s · short"
    );
  });
});

describe("guideTooltipLabel", () => {
  it("formats arcseconds through the shared helper", () => {
    expect(guideTooltipLabel("RA", 0.4137)).toBe(`RA: ${formatArcsec(0.4137)}`);
    expect(guideTooltipLabel("RA", 0.4137)).toBe(`RA: 0.41${ARCSEC}`);
  });

  it("uses the true double-prime, not a straight quote", () => {
    expect(guideTooltipLabel("Dec", -1.2)).toContain("″");
    expect(guideTooltipLabel("Dec", -1.2)).not.toContain('"');
  });

  it("leaves the star-loss marker unitless", () => {
    expect(guideTooltipLabel("Star lost", 0)).toBe("Star lost");
  });
});

const frame = (t: number, ra: number | null): Phd2Frame => ({
  t,
  ra,
  dec: ra,
  ra_pulse_ms: 0,
  ra_dir: "",
  dec_pulse_ms: 0,
  dec_dir: "",
  snr: 28.4,
  mass: 1702,
  dropped: false,
});

const framesResponse = (
  pixel_scale_arcsec: number | null,
  frames: Phd2Frame[],
): Phd2FramesResponse => ({
  pixel_scale_arcsec,
  started_at: "2026-07-14T21:42:27Z",
  frames,
  events: [],
});

describe("isScaleMissing", () => {
  it("reports frames that arrived without a pixel scale to convert them", () => {
    expect(isScaleMissing(framesResponse(null, [frame(1, null), frame(2, null)]))).toBe(true);
  });

  it("is false when the session has a pixel scale", () => {
    expect(isScaleMissing(framesResponse(1.54, [frame(1, 0.5)]))).toBe(false);
  });

  it("leaves the empty-series case to the no-frames message", () => {
    expect(isScaleMissing(framesResponse(null, []))).toBe(false);
  });

  it("is false while the response is still loading", () => {
    expect(isScaleMissing(undefined)).toBe(false);
  });
});

// The suite runs in whatever timezone the machine is set to, so the expected
// clock strings are taken from the shared helper rather than hard-coded. What
// is asserted here is that the component routes through that helper at all,
// and the shape of what it produces.
const STARTED_AT = "2026-07-14T21:42:27Z";

// Fixing the timezone in the options makes the expected strings exact: the
// session starts at 21:42:27 UTC, so five minutes in reads 21:47 there.
const UTC_24H = { hour12: false, timeZone: "UTC" };
const UTC_12H = { hour12: true, timeZone: "UTC" };

describe("guideTimeTick", () => {
  it("labels the axis with the clock time of night, not elapsed seconds", () => {
    expect(guideTimeTick(STARTED_AT, 300)).toBe(clockTime(STARTED_AT, 300));
    expect(guideTimeTick(STARTED_AT, 300)).toMatch(/^\d{2}:\d{2}$/);
  });

  it("renders in the display timezone it is given", () => {
    expect(guideTimeTick(STARTED_AT, 300, UTC_24H)).toBe("21:47");
  });

  it("renders a 12-hour clock when the display setting asks for one", () => {
    expect(guideTimeTick(STARTED_AT, 300, UTC_12H)).toBe(clockTime(STARTED_AT, 300, UTC_12H));
    expect(guideTimeTick(STARTED_AT, 300, UTC_12H)).toContain("09:47");
    expect(guideTimeTick(STARTED_AT, 300, UTC_12H)).not.toBe("21:47");
  });

  it("falls back to elapsed duration with no session start to measure from", () => {
    expect(guideTimeTick(null, 300)).toBe("5m");
    expect(guideTimeTick(undefined, 90, UTC_12H)).toBe("1m 30s");
  });
});

describe("guideTooltipTitle", () => {
  it("names the frame's clock time to the second", () => {
    expect(guideTooltipTitle(STARTED_AT, 305)).toBe(clockTimeWithSeconds(STARTED_AT, 305));
    expect(guideTooltipTitle(STARTED_AT, 305)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it("agrees with the axis label on the minute", () => {
    expect(guideTooltipTitle(STARTED_AT, 305).slice(0, 5)).toBe(guideTimeTick(STARTED_AT, 305));
  });

  it("carries the same display settings as the axis", () => {
    expect(guideTooltipTitle(STARTED_AT, 305, UTC_24H)).toBe("21:47:32");
    expect(guideTooltipTitle(STARTED_AT, 305, UTC_12H)).toContain("09:47:32");
  });

  it("falls back to elapsed duration with no session start", () => {
    expect(guideTooltipTitle(null, 300)).toBe("5m");
  });
});

describe("guideRangeCaption", () => {
  it("describes the whole session when nothing is zoomed", () => {
    expect(guideRangeCaption(null, { min: 0, max: 1320 }, STARTED_AT)).toBe(
      "Error in arcseconds against the clock time of night."
    );
  });

  it("names the visible window in clock time and the session length when zoomed", () => {
    expect(guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, STARTED_AT)).toBe(
      `Error in arcseconds, ${clockRange(STARTED_AT, 300, 420)} of 22m.`
    );
    expect(guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, STARTED_AT)).toMatch(
      /^Error in arcseconds, \d{2}:\d{2} to \d{2}:\d{2} of 22m\.$/
    );
  });

  it("reads the window under the display settings it is given", () => {
    expect(guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, STARTED_AT, UTC_24H)).toBe(
      "Error in arcseconds, 21:47 to 21:49 of 22m."
    );
    expect(
      guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, STARTED_AT, UTC_12H)
    ).toContain("09:47");
  });

  it("keeps elapsed wording when the session start is unknown", () => {
    expect(guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, null)).toBe(
      "Error in arcseconds, 5m to 7m of 22m."
    );
  });

  it("never mentions the downsampling note", () => {
    expect(guideRangeCaption({ min: 300, max: 420 }, { min: 0, max: 1320 }, STARTED_AT)).not.toContain(
      "peaks preserved"
    );
  });
});
