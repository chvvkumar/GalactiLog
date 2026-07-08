// Integration time: displays hours/minutes, and seconds whenever the
// remainder is non-zero. Both totals and per-row breakdowns are formatted
// from their own exact (rounded-to-the-second) values, so breakdown rows
// always sum exactly to the displayed total (see AUD-027).
export function formatIntegration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const hh = h.toString().padStart(2, "0");
  const mm = m.toString().padStart(2, "0");
  if (s === 0) return `${hh}h ${mm}m`;
  return `${hh}h ${mm}m ${s.toString().padStart(2, "0")}s`;
}

// Byte sizes: decimal (SI, 1000-based) units, used app-wide (AUD-025).
// Matches the convention already used by most pages (Statistics storage
// breakdown, Database overview); Settings > Metrics previously used binary
// (1024-based) units and has been migrated to this convention.
export function formatBytes(bytes: number): string {
  if (!isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1e3) return `${Math.round(bytes)} B`;
  if (bytes < 1e6) return `${(bytes / 1e3).toFixed(0)} KB`;
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(0)} MB`;
  if (bytes < 1e12) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${(bytes / 1e12).toFixed(2)} TB`;
}

// Arcsecond unit glyph: the true double-prime (U+2033) is typographically
// correct for arcseconds, as opposed to the straight double-quote (U+0022)
// (AUD-026). Used for guiding RMS and FWHM values throughout the app.
export const ARCSEC = "″";

export function formatArcsec(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !isFinite(value)) return "—";
  return `${value.toFixed(digits)}${ARCSEC}`;
}

// Parses a "YYYY-MM-DD" date key using local calendar semantics (year/month/day
// components), instead of `new Date(iso)` which ECMAScript parses as UTC
// midnight and can roll the date back a day in negative-UTC-offset timezones
// (AUD-023).
export function parseLocalDateKey(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

const WIDTH_CLASSES: Record<string, string> = {
  "full": "",
  "wide": "max-w-[1792px] mx-auto",
  "standard": "max-w-screen-2xl mx-auto",
  "compact": "max-w-7xl mx-auto",
};

export function contentWidthClass(width: string): string {
  return WIDTH_CLASSES[width] ?? "";
}
