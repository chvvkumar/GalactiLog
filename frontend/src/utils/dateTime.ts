/** Short time: "10:32 PM" or "22:32" depending on locale */
export function formatTime(date: Date | string, timezone: string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: timezone });
}

/** Short date: "3/31/2026" depending on locale */
export function formatDate(date: Date | string, timezone: string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleDateString([], { timeZone: timezone });
}

/** Date + time: "3/31/2026, 10:32 PM" */
export function formatDateTime(date: Date | string, timezone: string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return typeof date === "string" ? date : "";
  return d.toLocaleString([], { timeZone: timezone, hour: "2-digit", minute: "2-digit" });
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
