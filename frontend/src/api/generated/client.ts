// Bare openapi-fetch client generated against ./schema.d.ts.
//
// T1: no auth middleware yet -- that is T2's job (client.use(...) for a
// 401-refresh middleware). T3 migrates the ~90 hand-written api.xxx() call
// sites in ../client.ts over to this client; until then this module is
// exported but unused.
import createClient from "openapi-fetch";
import type { paths } from "./schema";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export const apiClient = createClient<paths>({
  baseUrl: API_BASE,
  credentials: "same-origin",
});
