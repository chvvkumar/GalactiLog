/**
 * Extracts a human-readable message from an unknown catch-block value.
 * Prefer `e.message` when present (covers Error and ApiError), otherwise
 * stringify the value or return the provided fallback.
 */
export function getErrorMessage(e: unknown, fallback = "An unexpected error occurred"): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string" && e.length > 0) return e;
  return fallback;
}
