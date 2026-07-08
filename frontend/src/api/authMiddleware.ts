// openapi-fetch middleware for the generated client (frontend/src/api/generated/client.ts).
// Detects a 401 response, attempts a single dedup'd session refresh via the
// shared authRefresh.ts primitive, retries the original request once on
// success, and dispatches the existing `auth:expired` window event on
// terminal failure -- mirroring today's `fetchWithRefresh` semantics
// (client.ts) exactly, just implemented as middleware instead of a bespoke
// fetch wrapper.
//
// Kept in its own hand-written module (not inlined into generated/client.ts)
// so a `npm run gen:api` regeneration never clobbers it.
//
// Retry mechanism note: by the time onResponse runs, the original Request's
// body (if any) has already been consumed by the underlying fetch() call, so
// `request.clone()` inside onResponse throws ("body already used") for any
// non-GET request with a body. To retry safely we stash an unconsumed clone
// in onRequest (before the body is read) keyed by the request object itself,
// then reuse that clone for the retry in onResponse.
import type { Middleware } from "openapi-fetch";
import { refreshSession } from "./authRefresh";

const retryableClones = new WeakMap<Request, Request>();

export const authMiddleware: Middleware = {
  onRequest({ request }) {
    retryableClones.set(request, request.clone());
  },

  async onResponse({ request, response }) {
    const path = new URL(request.url).pathname;
    const retryClone = retryableClones.get(request);
    retryableClones.delete(request);

    if (
      response.status === 401 &&
      !path.endsWith("/auth/refresh") &&
      !path.endsWith("/auth/login")
    ) {
      const ok = await refreshSession();
      if (ok && retryClone) {
        return fetch(retryClone);
      }
      window.dispatchEvent(new CustomEvent("auth:expired"));
    }
    return response;
  },
};
