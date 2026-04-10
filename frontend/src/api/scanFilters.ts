import { fetchJson } from "./client";

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
}

export const scanFilters = {
  get: (): Promise<ScanFiltersResponse> =>
    fetchJson<ScanFiltersResponse>("/scan/filters"),

  put: (filters: ScanFilters): Promise<ScanFiltersResponse> =>
    fetchJson<ScanFiltersResponse>("/scan/filters", {
      method: "PUT",
      body: JSON.stringify(filters),
    }),

  test: (
    path: string,
    targetKind: "auto" | "file" | "folder" = "auto",
  ): Promise<TestResult> =>
    fetchJson<TestResult>("/scan/filters/test", {
      method: "POST",
      body: JSON.stringify({ path, target_kind: targetKind }),
    }),

  applyNow: (dryRun: boolean): Promise<ApplyNowResult> =>
    fetchJson<ApplyNowResult>(
      `/scan/filters/apply-now?dry_run=${dryRun}`,
      { method: "POST" },
    ),

  browse: (path?: string): Promise<BrowseEntry[]> => {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    return fetchJson<BrowseEntry[]>(`/scan/browse${q}`);
  },
};
