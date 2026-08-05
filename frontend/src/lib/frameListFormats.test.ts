import { describe, it, expect } from "vitest";
import {
  isIncluded,
  selectedFrames,
  overrideKey,
  explorerSearchString,
  plainNameList,
  moveScript,
  type FrameSelectionOptions,
} from "./frameListFormats";
import type { FrameVerdict, Verdict } from "./wbppQualityFilter";
import type { FrameRecord } from "../api/types";

// Minimal FrameRecord factory: all metrics null unless overridden.
function frame(overrides: Partial<FrameRecord>): FrameRecord {
  return {
    timestamp: "2026-03-15T22:00:00Z",
    filter_used: "Ha",
    exposure_time: 300,
    median_hfr: null,
    eccentricity: null,
    sensor_temp: null,
    gain: null,
    file_name: "light_001.fits",
    image_id: "img-1",
    file_path: "/data/2026/03/15/Target/Ha/light_001.fits",
    file_size: null,
    source_relative: "2026/03/15/Target/Ha/light_001.fits",
    thumbnail_url: null,
    hfr_stdev: null,
    fwhm: null,
    detected_stars: null,
    guiding_rms_arcsec: null,
    guiding_rms_ra_arcsec: null,
    guiding_rms_dec_arcsec: null,
    adu_stdev: null,
    adu_mean: null,
    adu_median: null,
    adu_min: null,
    adu_max: null,
    focuser_position: null,
    focuser_temp: null,
    rotator_position: null,
    pier_side: null,
    airmass: null,
    ambient_temp: null,
    dew_point: null,
    humidity: null,
    pressure: null,
    wind_speed: null,
    wind_direction: null,
    wind_gust: null,
    cloud_cover: null,
    sky_quality: null,
    rig: null,
    ...overrides,
  };
}

// Verdict factory: keep/failures/failedBy derived from the reason, since the
// selection logic keys off `reason` and `frame.source_relative` only.
function verdict(
  reason: Verdict,
  sourceRelative: string,
  fileName?: string,
  sessionDate = "2026-03-15",
): FrameVerdict {
  return {
    frame: frame({
      source_relative: sourceRelative,
      file_name: fileName ?? sourceRelative.split("/").pop()!,
    }),
    sessionDate,
    keep: reason !== "fail",
    reason,
    failures: [],
    failedBy: reason === "fail" ? "hfr 4.00 > 3.00" : null,
  };
}

function opts(overrides: Partial<FrameSelectionOptions> = {}): FrameSelectionOptions {
  return { mode: "bad", includeUnmeasured: true, overrides: {}, ...overrides };
}

const pass = verdict("pass", "a/pass_1.fits");
const fail = verdict("fail", "a/fail_1.fits");
const unmeasured = verdict("unmeasured", "a/unm_1.fits");

describe("isIncluded", () => {
  it("bad mode includes only strict failures, never unmeasured", () => {
    const o = opts({ mode: "bad" });
    expect(isIncluded(fail, o)).toBe(true);
    expect(isIncluded(pass, o)).toBe(false);
    expect(isIncluded(unmeasured, o)).toBe(false);
  });

  it("bad mode ignores includeUnmeasured entirely", () => {
    const o = opts({ mode: "bad", includeUnmeasured: true });
    expect(isIncluded(unmeasured, o)).toBe(false);
  });

  it("good mode includes pass, and unmeasured only while the toggle is on", () => {
    const on = opts({ mode: "good", includeUnmeasured: true });
    expect(isIncluded(pass, on)).toBe(true);
    expect(isIncluded(unmeasured, on)).toBe(true);
    expect(isIncluded(fail, on)).toBe(false);

    const off = opts({ mode: "good", includeUnmeasured: false });
    expect(isIncluded(pass, off)).toBe(true);
    expect(isIncluded(unmeasured, off)).toBe(false);
  });

  it("override wins over the computed verdict in both directions", () => {
    const forceOut = opts({
      mode: "bad",
      overrides: { [overrideKey(fail)]: false },
    });
    expect(isIncluded(fail, forceOut)).toBe(false);

    const forceIn = opts({
      mode: "bad",
      overrides: { [overrideKey(pass)]: true },
    });
    expect(isIncluded(pass, forceIn)).toBe(true);
  });

  it("overrides for other frames do not leak", () => {
    const o = opts({ mode: "bad", overrides: { "2026-03-15|some/other.fits": false } });
    expect(isIncluded(fail, o)).toBe(true);
  });

  it("an override is scoped to its session: same source_relative on another date is untouched", () => {
    const night1 = verdict("fail", "a/twin.fits", undefined, "2026-03-15");
    const night2 = verdict("fail", "a/twin.fits", undefined, "2026-03-16");
    const o = opts({ mode: "bad", overrides: { [overrideKey(night1)]: false } });
    expect(isIncluded(night1, o)).toBe(false);
    expect(isIncluded(night2, o)).toBe(true);
    expect(selectedFrames([night1, night2], o)).toEqual([night2]);
  });
});

describe("selectedFrames", () => {
  it("filters verdicts through isIncluded preserving order", () => {
    const all = [pass, fail, unmeasured];
    expect(selectedFrames(all, opts({ mode: "bad" }))).toEqual([fail]);
    expect(selectedFrames(all, opts({ mode: "good", includeUnmeasured: true }))).toEqual([
      pass,
      unmeasured,
    ]);
    expect(selectedFrames(all, opts({ mode: "good", includeUnmeasured: false }))).toEqual([pass]);
  });

  it("returns empty for empty input", () => {
    expect(selectedFrames([], opts())).toEqual([]);
  });
});

describe("explorerSearchString", () => {
  it("double-quotes each name and joins with OR", () => {
    expect(explorerSearchString(["a.fits", "b.fits"])).toBe('"a.fits" OR "b.fits"');
  });

  it("a single name has no OR", () => {
    expect(explorerSearchString(["a.fits"])).toBe('"a.fits"');
  });

  it("empty list yields an empty string", () => {
    expect(explorerSearchString([])).toBe("");
  });
});

describe("plainNameList", () => {
  it("joins names with newlines", () => {
    expect(plainNameList(["a.fits", "b.fits", "c.fits"])).toBe("a.fits\nb.fits\nc.fits");
  });

  it("empty list yields an empty string", () => {
    expect(plainNameList([])).toBe("");
  });
});

describe("moveScript (PowerShell)", () => {
  const script = moveScript(["a.fits", "b.fits"], "D:\\Staging\\M31", "windows");

  it("declares the -Delete switch", () => {
    expect(script).toContain("param([switch]$Delete)");
  });

  it("single-quotes the base folder", () => {
    expect(script).toContain("$base = 'D:\\Staging\\M31'");
  });

  it("lists every name single-quoted, one per line, indented", () => {
    expect(script).toContain("$names = @(\n  'a.fits',\n  'b.fits'\n)");
  });

  it("targets the _rejected subfolder and confirms before acting", () => {
    expect(script).toContain("Join-Path $base '_rejected'");
    expect(script).toContain("Read-Host");
  });

  it("doubles embedded single quotes in names and base", () => {
    const s = moveScript(["it's.fits"], "D:\\O'Neill", "windows");
    expect(s).toContain("'it''s.fits'");
    expect(s).toContain("$base = 'D:\\O''Neill'");
  });

  it("skips files already under _rejected on re-runs", () => {
    expect(script).toContain("$_.DirectoryName -ne $dest");
  });

  it("an empty name list still yields a runnable script", () => {
    const s = moveScript([], "D:\\Staging", "windows");
    expect(s).toContain("param([switch]$Delete)");
    expect(s).toContain("$names = @(\n)");
    expect(s).toContain("if ($plan.Count -eq 0) { exit 0 }");
  });
});

describe("moveScript (bash)", () => {
  const script = moveScript(["a.fits", "b.fits"], "/mnt/staging", "posix");

  it("supports the --delete flag", () => {
    expect(script).toContain('[ "${1:-}" = "--delete" ] && delete=1');
  });

  it("single-quotes the base folder", () => {
    expect(script).toContain("base='/mnt/staging'");
  });

  it("lists every name single-quoted with no leading indentation", () => {
    expect(script).toContain("names=(\n'a.fits'\n'b.fits'\n)");
  });

  it("escapes single quotes in the base folder", () => {
    const s = moveScript(["a.fits"], "/mnt/o'neill", "posix");
    expect(s).toContain("base='/mnt/o'\\''neill'");
  });

  it("backslash-escapes find glob metacharacters inside quoted names", () => {
    const s = moveScript(["weird[1].fits", "star*?.fits"], "/mnt/staging", "posix");
    expect(s).toContain("'weird\\[1\\].fits'");
    expect(s).toContain("'star\\*\\?.fits'");
  });

  it("escapes backslashes in names before glob escaping", () => {
    const s = moveScript(["back\\slash.fits"], "/mnt/staging", "posix");
    expect(s).toContain("'back\\\\slash.fits'");
  });

  it("prunes the _rejected subtree from find", () => {
    expect(script).toContain('-path "$dest" -prune');
  });

  it("an empty name list still yields a runnable script", () => {
    const s = moveScript([], "/mnt/staging", "posix");
    expect(s).toContain("#!/usr/bin/env bash");
    expect(s).toContain("names=(\n)");
    expect(s).toContain('[ "${#plan[@]}" -eq 0 ] && exit 0');
  });
});
