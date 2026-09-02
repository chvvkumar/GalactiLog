// Create-mosaic-from-sessions client (cookie-authed).
//
// Deliberately NOT routed through the generated apiClient, same precedent as
// apiKeys.ts: these routes are new and generated/schema.d.ts has not been
// regenerated (`npm run gen:api` needs a live backend), so `paths` has no
// "/api/mosaics/from-sessions" entry and the typed client rejects the call.
// Errors are still translated through the shared unwrap.ts::toApiError so call
// sites keep branching on `instanceof ApiError`.
// ponytail: bare fetch skips authMiddleware's 401-refresh retry; move these
// two calls onto apiClient once the schema is regenerated.
import { toApiError } from "./unwrap";

export interface MosaicPrefillRow {
  session_date: string;
  panel_label: string | null;
  frame_count: number;
}

export interface MosaicPrefill {
  base_name: string | null;
  rows: MosaicPrefillRow[];
  mosaics: { id: string; name: string }[];
}

export interface FromSessionsPanelEntry {
  /** Final (possibly user-edited) panel name. */
  panel_label: string;
  /** The underlying prefill rows: the backend claims frames by the ORIGINAL
   * prefill label, so each row carries it alongside its date. */
  rows: { session_date: string; original_panel_label: string | null }[];
}

export interface CreateMosaicFromSessionsRequest {
  mode: "new" | "existing";
  name?: string;
  mosaic_id?: string;
  target_id: string;
  panels: FromSessionsPanelEntry[];
}

export interface CreateMosaicFromSessionsResponse {
  id: string;
  name: string;
  panel_count: number;
  claimed_frames: number;
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
  return (await res.json()) as T;
}

export const mosaicsFromSessionsApi = {
  prefill: (targetId: string, dates: string[]): Promise<MosaicPrefill> =>
    request<MosaicPrefill>(
      `/api/mosaics/from-sessions/prefill?target_id=${encodeURIComponent(targetId)}&dates=${encodeURIComponent(dates.join(","))}`,
    ),

  create: (body: CreateMosaicFromSessionsRequest): Promise<CreateMosaicFromSessionsResponse> =>
    request<CreateMosaicFromSessionsResponse>("/api/mosaics/from-sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
