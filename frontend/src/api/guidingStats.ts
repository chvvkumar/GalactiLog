import { apiClient } from "./generated/client";
import { unwrap } from "./unwrap";
import type { GuidingStatsResponse } from "./types";

export const guidingStats = {
  get: (signal?: AbortSignal): Promise<GuidingStatsResponse> =>
    apiClient.GET("/api/stats/guiding", { signal }).then(unwrap),
};
