// Every apiClient.GET/POST/PUT/DELETE(...) call (frontend/src/api/generated/client.ts)
// returns `{ data, error, response }` and does NOT throw on a non-2xx response --
// that's openapi-fetch's contract. `unwrap` is the ONE place that translates that
// shape into the throw-on-error behavior the rest of the app already expects,
// preserving parity with the old hand-written client.ts's `fetchJson`/`ApiError`
// (a `.status` plus a detail-derived `.message`). Downstream consumers (toasts,
// lib/emitWithToast.ts) branch on `instanceof ApiError` / `.status` -- every
// migrated call site must throw through this helper so those consumers keep
// matching.
//
// 401-refresh is handled entirely by T2's authMiddleware on the generated client
// (see ./authMiddleware.ts) -- this helper does NOT retry requests or dispatch
// `auth:expired`; it only translates whatever final response comes back after
// the middleware has already attempted a refresh.

const FALLBACK_MESSAGES: Record<number, string> = {
  400: "Invalid request",
  403: "Permission denied",
  404: "Not found",
  409: "Conflict - resource already exists",
  422: "Validation error",
  500: "Server error - please try again later",
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function messageFromErrorBody(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail !== undefined) return JSON.stringify(detail);
  }
  return FALLBACK_MESSAGES[status] ?? "Something went wrong";
}

/** Builds an ApiError from an openapi-fetch error body, matching the old
 * client.ts's `extractApiError`/`fetchJson` message derivation exactly:
 * a string `detail` field is used verbatim, a non-string `detail` (e.g. the
 * FastAPI validation-error array) is stringified, and anything else falls
 * back to a fixed per-status message. */
export function toApiError(error: unknown, status: number): ApiError {
  return new ApiError(status, messageFromErrorBody(error, status));
}

/**
 * Unwraps an openapi-fetch result: returns `data` on success, throws an
 * `ApiError` (status + detail-derived message) on failure. Intended usage in
 * a TanStack Query `queryFn`/mutation body:
 *
 *   queryFn: ({ signal }) => apiClient.GET("/x", { params, signal }).then(unwrap)
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  // Throw whenever the response is non-2xx, matching the old client.ts
  // fetchJson which threw unconditionally on `!resp.ok`. openapi-fetch leaves
  // `result.error` undefined for a non-2xx response with an EMPTY body (an
  // nginx 502/504 during a backend restart, or a bare 204) because it never
  // parses a body -- gating only on `result.error` would let those infra
  // failures through as a fake success with undefined data. Gate on
  // `response.ok` instead; `toApiError` falls back to the per-status message
  // table when there is no parseable detail body.
  if (!result.response.ok) {
    throw toApiError(result.error, result.response.status);
  }
  return result.data as T;
}
