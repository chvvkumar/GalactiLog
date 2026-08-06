import { isValidTimeZone } from "./dateTime";

/**
 * Compact duration for guiding readouts: "45s", "7m 30s", "2h 15m".
 * Distinct from utils/format.ts's formatIntegration, which always pads to
 * "HHh MMm" because it totals a whole night; guiding durations are often
 * seconds long and read badly as "00h 00m 45s".
 */
export function formatSecondsShort(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return "0s";
  // Branch on the raw value rather than the rounded one: 59.6s is a sub-minute
  // duration and reads as "60s", not as "1m".
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes < 60) return secs === 0 ? `${minutes}m` : `${minutes}m ${secs}s`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins === 0 ? `${hours}h` : `${hours}h ${mins}m`;
}

/*
 * Wall clock presentation for the guide graph.
 *
 * The chart domain stays in elapsed seconds since the session's first frame,
 * because that is what the PHD2 log records and what zoom, pan and slicing
 * arithmetic operate on. Only labels convert to the clock, so a frame's
 * timestamp can be matched against the graph by eye.
 *
 * Limitation: the conversion renders in the *browser's* timezone, not the
 * observatory's. This deployment runs both in the same zone, so the label is
 * the observer's local time. Viewed from another zone the labels shift by the
 * offset difference; a per-site timezone would have to come from the session
 * record to fix that.
 */

/** Trailing "Z", "+HH:MM", "-HHMM" and friends. */
const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;
/** A time component, i.e. not a bare "2026-07-28" (already UTC by spec). */
const HAS_TIME = /\d{2}:\d{2}/;

/**
 * Milliseconds for the session start, or null if the value is unusable.
 *
 * A datetime with no zone designator is read as UTC. The API documents
 * started_at as UTC, but `Date.parse` treats a zoneless date-time as *local*,
 * which would silently shift every label by the browser's offset.
 */
function startMs(startedAtIso: string): number | null {
  if (typeof startedAtIso !== "string") return null;
  const raw = startedAtIso.trim();
  if (!raw) return null;
  const normalized = HAS_TIME.test(raw) && !HAS_ZONE.test(raw) ? `${raw}Z` : raw;
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
}

/** Local wall clock date for start + elapsed, or null if either is unusable. */
function clockAt(startedAtIso: string, elapsedSeconds: number): Date | null {
  const base = startMs(startedAtIso);
  if (base === null || !isFinite(elapsedSeconds)) return null;
  // Truncate rather than round: a clock reads 21:45 until 21:46 actually
  // arrives, and truncating keeps clockTimeWithSeconds' minute equal to
  // clockTime's for the same instant.
  const date = new Date(base + Math.trunc(elapsedSeconds * 1000));
  return isFinite(date.getTime()) ? date : null;
}

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

function hhmm(date: Date): string {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/** How the graph should read the clock. Both fields come from user settings. */
export interface ClockOptions {
  /** True renders "09:45 PM". Defaults to false, the ISO-style "21:45". */
  hour12?: boolean;
  /**
   * IANA zone to render in, normally the user's display timezone setting.
   * Empty, whitespace, or a zone the runtime does not recognise falls back to
   * the browser's own zone. Omitting it does the same.
   */
  timeZone?: string;
}

/**
 * The reading, delegated to the same Intl options `utils/dateTime`'s
 * `formatTime` uses for the session dropdown. Both readings sit in the same
 * panel, so they have to agree character for character: whether the hour pads,
 * how the meridiem is spelled and spaced, and how a locale that has no
 * meridiem falls back are all decisions this must not make independently.
 */
function localeClock(
  date: Date,
  withSeconds: boolean,
  hour12: boolean,
  timeZone?: string,
): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" as const } : {}),
    ...(timeZone ? { timeZone } : {}),
    hour12,
  });
}

/**
 * Renders one instant under the caller's options.
 *
 * The plain 24-hour, browser-zone case is built by hand rather than through
 * Intl, because that is the graph's default reading and it must stay a
 * zero-padded "21:45" in every locale: a locale with non-Latin digits would
 * otherwise change the axis out from under the arithmetic the labels describe.
 * Every case the user explicitly asked for, a 12-hour clock or a display
 * timezone, goes through Intl so it matches the dropdown.
 *
 * An unusable timezone degrades to the browser's zone instead of propagating
 * the RangeError that `Intl` raises and `formatTime` lets through. A label that
 * throws takes the whole graph down with it, and the setting is validated
 * before it is stored, so this is a guard and not an expected path.
 */
function renderClock(date: Date, withSeconds: boolean, opts: ClockOptions): string {
  const hour12 = opts.hour12 ?? false;
  const timeZone = (opts.timeZone ?? "").trim();
  if (timeZone && isValidTimeZone(timeZone)) {
    return localeClock(date, withSeconds, hour12, timeZone);
  }
  if (hour12) return localeClock(date, withSeconds, true);
  return withSeconds ? `${hhmm(date)}:${pad2(date.getSeconds())}` : hhmm(date);
}

/**
 * Clock time of night for a point on the graph: "21:45", "02:10", or "09:45 PM"
 * under a 12-hour setting.
 *
 * Days roll over on their own, so a session starting at 23:50 reads 00:10
 * twenty minutes in. Falls back to elapsed duration when the session start is
 * missing or unparseable, so the axis degrades to the old reading instead of
 * printing garbage.
 *
 * Callers that display alongside the session dropdown should pass the same
 * settings it uses, the display timezone and the inverse of `use24hTime`, so
 * the whole panel reads one way.
 */
export function clockTime(
  startedAtIso: string,
  elapsedSeconds: number,
  opts: ClockOptions = {},
): string {
  const date = clockAt(startedAtIso, elapsedSeconds);
  if (!date) return formatSecondsShort(elapsedSeconds);
  return renderClock(date, false, opts);
}

/** As clockTime, to the second: "21:47:05". For tooltips, where one frame is one point. */
export function clockTimeWithSeconds(
  startedAtIso: string,
  elapsedSeconds: number,
  opts: ClockOptions = {},
): string {
  const date = clockAt(startedAtIso, elapsedSeconds);
  if (!date) return formatSecondsShort(elapsedSeconds);
  return renderClock(date, true, opts);
}

/** The visible window as clock times: "21:45 to 22:15". */
export function clockRange(
  startedAtIso: string,
  fromSeconds: number,
  toSeconds: number,
  opts: ClockOptions = {},
): string {
  const from = clockTime(startedAtIso, fromSeconds, opts);
  const to = clockTime(startedAtIso, toSeconds, opts);
  return `${from} to ${to}`;
}
