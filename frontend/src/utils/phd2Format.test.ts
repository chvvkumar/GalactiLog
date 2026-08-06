import { describe, it, expect } from "vitest";
import {
  clockRange,
  clockTime,
  clockTimeWithSeconds,
  formatSecondsShort,
} from "./phd2Format";
import { formatTime } from "./dateTime";

/**
 * Builds the UTC ISO string for a given *local* wall clock instant, so these
 * expectations hold in whatever timezone the test runner sits in. Asserting
 * against a hard-coded "2026-07-28T23:50:00Z" would only pass in UTC.
 */
function isoAtLocal(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  second = 0,
): string {
  return new Date(year, month - 1, day, hour, minute, second).toISOString();
}

/** The runtime's own zone, so `formatTime` can be asked for the same instant. */
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
/** 12-hour literals below ("09:45 PM") are how en locales render; others differ. */
const EN_LOCALE = Intl.DateTimeFormat().resolvedOptions().locale.startsWith("en");

describe("formatSecondsShort", () => {
  it("renders sub-minute durations in whole seconds", () => {
    expect(formatSecondsShort(0)).toBe("0s");
    expect(formatSecondsShort(45.4)).toBe("45s");
    expect(formatSecondsShort(59.6)).toBe("60s");
  });

  it("renders minutes, dropping a zero seconds remainder", () => {
    expect(formatSecondsShort(420)).toBe("7m");
    expect(formatSecondsShort(450)).toBe("7m 30s");
  });

  it("renders hours, dropping a zero minutes remainder", () => {
    expect(formatSecondsShort(7200)).toBe("2h");
    expect(formatSecondsShort(8100)).toBe("2h 15m");
  });

  it("clamps nonsense input to zero", () => {
    expect(formatSecondsShort(-5)).toBe("0s");
    expect(formatSecondsShort(Number.NaN)).toBe("0s");
  });
});

describe("clockTime", () => {
  it("renders the session start itself", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 21, 45), 0)).toBe("21:45");
  });

  it("adds elapsed seconds to the start time", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 21, 45), 25 * 60)).toBe("22:10");
    expect(clockTime(isoAtLocal(2026, 7, 28, 21, 45), 2 * 3600)).toBe("23:45");
  });

  it("crosses midnight into the next day", () => {
    const start = isoAtLocal(2026, 7, 28, 23, 50);
    expect(clockTime(start, 20 * 60)).toBe("00:10");
    expect(clockTime(start, 2 * 3600 + 20 * 60)).toBe("02:10");
  });

  it("truncates to the minute rather than rounding up", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45);
    expect(clockTime(start, 59.9)).toBe("21:45");
    expect(clockTime(start, 60)).toBe("21:46");
  });

  it("pads single digit hours and minutes", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 5, 7), 0)).toBe("05:07");
  });

  it("reads a start without an explicit zone as UTC", () => {
    // Pydantic emits "+00:00"; a naive value must not be taken as local time.
    expect(clockTime("2026-07-28T23:50:00", 20 * 60)).toBe(
      clockTime("2026-07-28T23:50:00Z", 20 * 60),
    );
    expect(clockTime("2026-07-28T23:50:00+00:00", 20 * 60)).toBe(
      clockTime("2026-07-28T23:50:00Z", 20 * 60),
    );
  });

  it("falls back to elapsed time when the start is missing or unparseable", () => {
    expect(clockTime("", 450)).toBe("7m 30s");
    expect(clockTime("   ", 45)).toBe("45s");
    expect(clockTime("not a timestamp", 8100)).toBe("2h 15m");
    expect(clockTime(null as unknown as string, 420)).toBe("7m");
  });

  it("falls back to elapsed time when the offset is not a number", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45);
    expect(clockTime(start, Number.NaN)).toBe("0s");
    expect(clockTime(start, Number.POSITIVE_INFINITY)).toBe("0s");
  });
});

describe("clockTimeWithSeconds", () => {
  it("keeps seconds precision", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45, 0);
    expect(clockTimeWithSeconds(start, 0)).toBe("21:45:00");
    expect(clockTimeWithSeconds(start, 125)).toBe("21:47:05");
  });

  it("carries the start's own seconds through", () => {
    expect(clockTimeWithSeconds(isoAtLocal(2026, 7, 28, 21, 45, 37), 3)).toBe(
      "21:45:40",
    );
  });

  it("truncates fractional seconds, so its minute matches clockTime", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45, 0);
    expect(clockTimeWithSeconds(start, 5.9)).toBe("21:45:05");
    expect(clockTimeWithSeconds(start, 59.9)).toBe("21:45:59");
  });

  it("crosses midnight into the next day", () => {
    expect(clockTimeWithSeconds(isoAtLocal(2026, 7, 28, 23, 59, 50), 15)).toBe(
      "00:00:05",
    );
  });

  it("falls back to elapsed time when the start is unusable", () => {
    expect(clockTimeWithSeconds("", 450)).toBe("7m 30s");
    expect(clockTimeWithSeconds("not a timestamp", 45)).toBe("45s");
  });
});

describe("clockRange", () => {
  it("renders both ends as wall clock times", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45);
    expect(clockRange(start, 0, 30 * 60)).toBe("21:45 to 22:15");
  });

  it("crosses midnight", () => {
    const start = isoAtLocal(2026, 7, 28, 23, 30);
    expect(clockRange(start, 0, 90 * 60)).toBe("23:30 to 01:00");
  });

  it("falls back to elapsed time on both ends when the start is unusable", () => {
    expect(clockRange("", 0, 450)).toBe("0s to 7m 30s");
    expect(clockRange("not a timestamp", 420, 8100)).toBe("7m to 2h 15m");
  });
});

describe("12-hour display", () => {
  it("defaults to 24-hour browser local, so callers that omit the options are unaffected", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45);
    expect(clockTime(start, 0)).toBe(clockTime(start, 0, {}));
    expect(clockTime(start, 0)).toBe(clockTime(start, 0, { hour12: false }));
    expect(clockTimeWithSeconds(start, 0)).toBe(clockTimeWithSeconds(start, 0, {}));
    expect(clockRange(start, 0, 60)).toBe(clockRange(start, 0, 60, {}));
    expect(clockTime(start, 0, { hour12: false })).toBe("21:45");
  });

  it("matches the session dropdown's formatter for the same instant", () => {
    // The dropdown calls formatTime(session.started_at, tz, use24h). Both
    // readings sit in the same panel, so they must agree character for
    // character rather than merely both being twelve-hour.
    const at = new Date(2026, 6, 28, 21, 45, 0);
    const start = at.toISOString();
    expect(clockTime(start, 0, { hour12: true })).toBe(formatTime(at, BROWSER_TZ, false));
    expect(clockTime(start, 0, { hour12: false })).toBe(formatTime(at, BROWSER_TZ, true));
    const later = new Date(2026, 6, 28, 9, 5, 0);
    expect(clockTime(later.toISOString(), 0, { hour12: true })).toBe(formatTime(later, BROWSER_TZ, false));
  });

  it("falls back to elapsed time when the start is unusable", () => {
    expect(clockTime("", 450, { hour12: true })).toBe("7m 30s");
    expect(clockTimeWithSeconds("not a timestamp", 45, { hour12: true })).toBe("45s");
    expect(clockRange("", 0, 450, { hour12: true })).toBe("0s to 7m 30s");
  });
});

describe.skipIf(!EN_LOCALE)("12-hour display, en locale rendering", () => {
  it("renders an evening time with a padded hour and a meridiem", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 21, 45), 0, { hour12: true })).toBe("09:45 PM");
    expect(clockTime(isoAtLocal(2026, 7, 28, 5, 7), 0, { hour12: true })).toBe("05:07 AM");
  });

  it("renders midnight as 12 AM, crossing over from the evening before", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 23, 50), 20 * 60, { hour12: true })).toBe("12:10 AM");
    expect(clockTime(isoAtLocal(2026, 7, 28, 23, 50), 10 * 60, { hour12: true })).toBe("12:00 AM");
  });

  it("renders noon as 12 PM, not 00 PM", () => {
    expect(clockTime(isoAtLocal(2026, 7, 28, 11, 55), 5 * 60, { hour12: true })).toBe("12:00 PM");
    expect(clockTime(isoAtLocal(2026, 7, 28, 11, 55), 10 * 60, { hour12: true })).toBe("12:05 PM");
  });

  it("keeps seconds precision in tooltips", () => {
    const start = isoAtLocal(2026, 7, 28, 21, 45, 0);
    expect(clockTimeWithSeconds(start, 125, { hour12: true })).toBe("09:47:05 PM");
    expect(clockTimeWithSeconds(isoAtLocal(2026, 7, 28, 23, 59, 50), 15, { hour12: true })).toBe(
      "12:00:05 AM",
    );
  });

  it("renders both ends of a range", () => {
    expect(clockRange(isoAtLocal(2026, 7, 28, 21, 45), 0, 30 * 60, { hour12: true })).toBe(
      "09:45 PM to 10:15 PM",
    );
    expect(clockRange(isoAtLocal(2026, 7, 28, 23, 30), 0, 90 * 60, { hour12: true })).toBe(
      "11:30 PM to 01:00 AM",
    );
  });
});

describe("display timezone", () => {
  // The panel's dropdown renders in the user's configured zone, so the axis
  // has to be able to as well. These instants are anchored in UTC, so the
  // expectations hold whatever zone the runner sits in.
  const AT_2145_KOLKATA = "2026-07-28T16:15:00Z";

  it("matches the session dropdown's formatter in a non-browser zone", () => {
    const at = new Date(AT_2145_KOLKATA);
    for (const tz of ["Asia/Kolkata", "America/Denver", "Pacific/Auckland"]) {
      expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: tz, hour12: true })).toBe(
        formatTime(at, tz, false),
      );
      expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: tz })).toBe(formatTime(at, tz, true));
    }
  });

  it("applies the zone to the elapsed offset, not only to the start", () => {
    const at = new Date(new Date(AT_2145_KOLKATA).getTime() + 90 * 60 * 1000);
    expect(clockTime(AT_2145_KOLKATA, 90 * 60, { timeZone: "Asia/Kolkata" })).toBe(
      formatTime(at, "Asia/Kolkata", true),
    );
  });

  it("falls back to the browser zone when the setting is empty or invalid", () => {
    // formatTime throws a RangeError on these; an axis label must not.
    const plain = clockTime(AT_2145_KOLKATA, 0);
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "" })).toBe(plain);
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "   " })).toBe(plain);
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "Not/AZone" })).toBe(plain);
    expect(clockTimeWithSeconds(AT_2145_KOLKATA, 0, { timeZone: "Not/AZone" })).toBe(
      clockTimeWithSeconds(AT_2145_KOLKATA, 0),
    );
    expect(clockRange(AT_2145_KOLKATA, 0, 600, { timeZone: "Not/AZone" })).toBe(
      clockRange(AT_2145_KOLKATA, 0, 600),
    );
  });

  it("keeps the 12-hour choice when the zone is unusable", () => {
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "Not/AZone", hour12: true })).toBe(
      clockTime(AT_2145_KOLKATA, 0, { hour12: true }),
    );
  });

  it("still falls back to elapsed time when the start is unusable", () => {
    expect(clockTime("", 450, { timeZone: "Asia/Kolkata" })).toBe("7m 30s");
    expect(clockRange("nope", 420, 8100, { timeZone: "Asia/Kolkata", hour12: true })).toBe(
      "7m to 2h 15m",
    );
  });
});

describe.skipIf(!EN_LOCALE)("display timezone, en locale rendering", () => {
  const AT_2145_KOLKATA = "2026-07-28T16:15:00Z";

  it("renders the configured zone's wall clock, not the browser's", () => {
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "Asia/Kolkata" })).toBe("21:45");
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "Asia/Kolkata", hour12: true })).toBe(
      "09:45 PM",
    );
    expect(clockTime(AT_2145_KOLKATA, 0, { timeZone: "UTC" })).toBe("16:15");
  });

  it("crosses midnight in the configured zone", () => {
    // 18:25 UTC is 23:55 in Kolkata; ten minutes later is the next day.
    const start = "2026-07-28T18:25:00Z";
    expect(clockTime(start, 10 * 60, { timeZone: "Asia/Kolkata" })).toBe("00:05");
    expect(clockTime(start, 10 * 60, { timeZone: "Asia/Kolkata", hour12: true })).toBe(
      "12:05 AM",
    );
  });

  it("keeps seconds and ranges in the configured zone", () => {
    expect(clockTimeWithSeconds(AT_2145_KOLKATA, 125, { timeZone: "Asia/Kolkata" })).toBe(
      "21:47:05",
    );
    expect(clockRange(AT_2145_KOLKATA, 0, 30 * 60, { timeZone: "Asia/Kolkata" })).toBe(
      "21:45 to 22:15",
    );
  });
});
