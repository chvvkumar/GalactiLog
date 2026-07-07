// openapi-fetch client generated against ./schema.d.ts.
//
// T2 attaches the single 401-refresh middleware here (see ../authMiddleware.ts
// for the implementation -- kept in its own hand-written module so a
// `npm run gen:api` regeneration of this file never clobbers it). T3
// migrates the ~90 hand-written api.xxx() call sites in ../client.ts over to
// this client; until then this module is exported but unused by page code.
import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { authMiddleware } from "../authMiddleware";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export const apiClient = createClient<paths>({
  baseUrl: API_BASE,
  credentials: "same-origin",
});

apiClient.use(authMiddleware);
