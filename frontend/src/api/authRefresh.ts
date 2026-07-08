// Single shared refresh primitive. Every consumer that needs to attempt a
// session refresh (the old client.ts fetchJson/fetchWithRefresh layer, the
// generated openapi-fetch client's 401 middleware, and AuthProvider's boot
// probe) must call refreshSession() rather than re-implement the POST
// /auth/refresh + dedup dance itself. This keeps exactly one in-flight
// refresh request at a time even when multiple layers hit a 401 storm at
// once.
//
// This module has no dependency on openapi-fetch or TanStack Query -- it is
// the shared leaf all three consumers import.

const API_BASE = import.meta.env.VITE_API_URL || "/api";

let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  try {
    const resp = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "same-origin",
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Ensures at most one in-flight /auth/refresh call at a time; concurrent
 * callers await the same promise. Returns true if refresh succeeded, false
 * otherwise (never throws).
 */
export async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}
