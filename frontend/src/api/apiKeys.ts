// Admin API key management (cookie-authed).
//
// Deliberately NOT routed through the generated apiClient: these routes are new
// and generated/schema.d.ts has not been regenerated (`npm run gen:api` needs a
// live backend), so `paths` has no "/api/apikeys" entry and the typed client
// rejects the call. Errors are still translated through the shared
// unwrap.ts::toApiError so call sites keep branching on `instanceof ApiError`.
// ponytail: bare fetch skips authMiddleware's 401-refresh retry; move these
// four calls onto apiClient once the schema is regenerated.
import { toApiError } from "./unwrap";

export interface ApiKey {
  id: string;
  name: string;
  /** Non-secret leading fragment, e.g. "glg_a1b2c3". */
  prefix: string;
  can_write: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** Create response only: `key` is the full raw secret, returned exactly once. */
export interface CreatedApiKey {
  key: string;
  id: string;
  name: string;
  prefix: string;
  can_write: boolean;
  created_at: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    throw toApiError(await res.json().catch(() => undefined), res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const apiKeysApi = {
  list: (): Promise<ApiKey[]> => request<ApiKey[]>("/api/apikeys"),

  create: (name: string, canWrite: boolean): Promise<CreatedApiKey> =>
    request<CreatedApiKey>("/api/apikeys", {
      method: "POST",
      body: JSON.stringify({ name, can_write: canWrite }),
    }),

  /** Revokes the key. The row stays listed with `revoked_at` set. */
  revoke: (id: string): Promise<void> =>
    request<void>(`/api/apikeys/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
