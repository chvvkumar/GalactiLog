// First-run setup wizard client.
import type { components } from "./generated/schema";
import { apiClient } from "./generated/client";
import { unwrap } from "./unwrap";

export type SetupState = components["schemas"]["BootstrapSetup"];

export const setupApi = {
  /** Stamps general.setup_completed_at server-side. Admin only. */
  async markComplete(): Promise<void> {
    await apiClient.POST("/api/settings/setup-complete", {}).then(unwrap);
  },
};
