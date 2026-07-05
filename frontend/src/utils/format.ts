export function formatIntegration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h.toString().padStart(2, "0")}h ${m.toString().padStart(2, "0")}m`;
}

// Arcsecond unit glyph: the true double-prime (U+2033) is typographically
// correct for arcseconds, as opposed to the straight double-quote (U+0022).
// Used for guiding RMS and FWHM values throughout the app.
export const ARCSEC = "″";

export function formatArcsec(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !isFinite(value)) return "—";
  return `${value.toFixed(digits)}${ARCSEC}`;
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
