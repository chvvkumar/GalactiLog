/** Short time: "10:32 PM" or "22:32" when use24h is true */
export function formatTime(date: Date | string, timezone: string, use24h = false): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: timezone, hour12: !use24h });
}

/** Short date: "3/31/2026" depending on locale */
export function formatDate(date: Date | string, timezone: string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleDateString([], { timeZone: timezone });
}

/** Date + time: "3/31/2026, 10:32 PM" or "3/31/2026, 22:32" when use24h is true */
export function formatDateTime(date: Date | string, timezone: string, use24h = false): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleString([], { timeZone: timezone, hour: "2-digit", minute: "2-digit", hour12: !use24h });
}

/** Human-readable timezone abbreviation for labels: "UTC", "EST", "PST", etc. */
export function timezoneLabel(timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat([], { timeZone: timezone, timeZoneName: "short" }).formatToParts(new Date());
    const tzPart = parts.find((p) => p.type === "timeZoneName");
    return tzPart?.value ?? timezone;
  } catch {
    return timezone;
  }
}

/**
 * Descriptive name for a zone: "Central Time" for America/Chicago.
 *
 * Prefers the generic long name so the label does not flip between standard
 * and daylight wording twice a year, falls back to the seasonal long name,
 * and finally to the zone id itself when the runtime knows neither (or when
 * the zone is not loadable at all).
 *
 * A bare "GMT" or "GMT-03:00" is rejected rather than returned: it says less
 * than the zone id it would sit beside, and for UTC the seasonal name that
 * follows it ("Coordinated Universal Time") is the useful one.
 */
export function timezoneFriendlyName(timezone: string): string {
  for (const style of ["longGeneric", "long"] as const) {
    try {
      const parts = new Intl.DateTimeFormat([], { timeZone: timezone, timeZoneName: style }).formatToParts(new Date());
      const name = parts.find((p) => p.type === "timeZoneName")?.value;
      if (name && name !== timezone && !/^(GMT|UTC)([+-]|$)/.test(name)) return name;
    } catch {
      // Try the next style, then give up and return the zone id.
    }
  }
  return timezone;
}

/**
 * Every IANA zone name this runtime knows, or null when it cannot say.
 *
 * Intl.supportedValuesOf is the only list available without shipping a zone
 * database of our own. Returning null rather than an empty array keeps the
 * two outcomes distinct for callers: a null means "render a free-text field
 * instead", where an empty array would render an empty dropdown the user
 * cannot escape.
 */
export function supportedTimeZones(): string[] | null {
  if (typeof Intl.supportedValuesOf !== "function") return null;
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.length > 0 ? [...zones] : null;
  } catch {
    return null;
  }
}

/**
 * True when `tz` is a zone name the runtime's Intl database recognises.
 * Empty/whitespace input is false: the settings field treats "no value" as
 * "not configured" and never submits it through this check.
 */
export function isValidTimeZone(tz: string): boolean {
  if (!tz.trim()) return false;
  try {
    new Intl.DateTimeFormat([], { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}
