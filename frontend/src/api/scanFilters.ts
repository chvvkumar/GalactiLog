// Migrated off the old hand-written fetchJson/client.ts (Slice 14) so this
// module no longer blocks Slice 15's teardown of api/client.ts. ScanFilters*
// interfaces are kept as hand-written (not repointed to api/types' generated
// ScanFiltersIn/Out) because they precisely match this module's own request/
// response shapes and are the source of truth for ScanFiltersPanel.tsx's
// createStore-driven editing. The generated ScanFiltersIn/ValidateRegexOut
// types mark several backend-Pydantic-default fields optional (OpenAPI drops
// the defaults); the backend always populates them, so responses are cast at
// the boundary below -- same precedent as SettingsProvider.tsx's bootstrap
// cast, not a behavior change.
import { apiClient } from "./generated/client";
import { unwrap } from "./unwrap";

export type RuleAction = "include" | "exclude";
export type RuleType = "glob" | "substring" | "regex";
export type RuleTarget = "file" | "folder";

export interface NameRule {
  id: string;
  action: RuleAction;
  type: RuleType;
  pattern: string;
  target: RuleTarget;
  enabled: boolean;
}

export interface ScanFilters {
  include_paths: string[];
  exclude_paths: string[];
  name_rules: NameRule[];
}

export interface ScanFiltersResponse {
  configured: boolean;
  filters: ScanFilters;
  fits_root: string;
}

export type Verdict =
  | "included"
  | "excluded_by_path"
  | "excluded_by_rule"
  | "excluded_by_missing_include";

export interface TestResult {
  verdict: Verdict;
  matched_rule_ids: string[];
}

export interface BrowseEntry {
  name: string;
  path: string;
  has_children: boolean;
}

export interface ApplyNowResult {
  dry_run: boolean;
  matched: number;
  sample_paths?: string[];
}

export interface ValidateRegexResult {
  ok: boolean;
  error: string | null;
}

export const scanFilters = {
  get: (): Promise<ScanFiltersResponse> =>
    apiClient.GET("/api/scan/filters", {}).then(unwrap).then((r) => r as unknown as ScanFiltersResponse),

  put: (filters: ScanFilters): Promise<ScanFiltersResponse> =>
    apiClient.PUT("/api/scan/filters", { body: filters }).then(unwrap).then((r) => r as unknown as ScanFiltersResponse),

  test: (
    path: string,
    targetKind: "auto" | "file" | "folder" = "auto",
  ): Promise<TestResult> =>
    apiClient.POST("/api/scan/filters/test", { body: { path, target_kind: targetKind } }).then(unwrap),

  validateRegex: (pattern: string): Promise<ValidateRegexResult> =>
    apiClient
      .POST("/api/scan/filters/validate-regex", { body: { pattern } })
      .then(unwrap)
      .then((r) => r as ValidateRegexResult),

  applyNow: (dryRun: boolean): Promise<ApplyNowResult> =>
    apiClient
      .POST("/api/scan/filters/apply-now", { params: { query: { dry_run: dryRun } } })
      .then(unwrap),

  browse: (path?: string): Promise<BrowseEntry[]> =>
    apiClient.GET("/api/scan/browse", { params: { query: { path } } }).then(unwrap),
};
