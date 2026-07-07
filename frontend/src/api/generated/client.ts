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

// NOTE: unlike the old hand-written client.ts (whose fetchJson prepended
// `API_BASE = VITE_API_URL || "/api"` to path strings like "/scan/status"),
// the generated `paths` type's keys already embed the full server-mounted
// prefix (e.g. "/api/scan/status" -- see backend/app/api/router.py's
// `APIRouter(prefix="/api")`). Setting baseUrl to "/api" here would double
// it to "/api/api/scan/status". baseUrl is therefore "" (relative to the
// current origin), which the vite dev proxy and production nginx both
// already route correctly for "/api/..." paths.
export const apiClient = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
});

apiClient.use(authMiddleware);
