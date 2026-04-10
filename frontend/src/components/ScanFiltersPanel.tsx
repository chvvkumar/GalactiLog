import { Component, createSignal, createEffect, Show, For } from "solid-js";
import { scanFilters } from "../api/scanFilters";
import type {
  ScanFilters,
  NameRule,
  RuleAction,
  RuleType,
  RuleTarget,
  Verdict,
} from "../api/scanFilters";
import FolderBrowserModal from "./FolderBrowserModal";
import { showToast } from "./Toast";

const EMPTY: ScanFilters = { include_paths: [], exclude_paths: [], name_rules: [] };

const VERDICT_LABEL: Record<Verdict, string> = {
  included: "Included",
  excluded_by_path: "Excluded by path",
  excluded_by_rule: "Excluded by rule",
  excluded_by_missing_include: "Excluded (no include rule matched)",
};

interface Props {
  onConfigured?: () => void;
}

const ScanFiltersPanel: Component<Props> = (props) => {
  const [filters, setFilters] = createSignal<ScanFilters>(EMPTY);
  const [original, setOriginal] = createSignal<ScanFilters>(EMPTY);
  const [fitsRoot, setFitsRoot] = createSignal<string>("");
  const [dirty, setDirty] = createSignal(false);
  const [browsing, setBrowsing] = createSignal<null | "include" | "exclude">(null);
  const [saving, setSaving] = createSignal(false);
  const [testPath, setTestPath] = createSignal("");
  const [testKind, setTestKind] = createSignal<"auto" | "file" | "folder">("auto");
  const [testResult, setTestResult] = createSignal<
    null | { verdict: Verdict; matched: string[] }
  >(null);

  const ruleIsInvalid = (r: NameRule): string | null => {
    if (!r.pattern.trim()) return "empty pattern";
    if (r.type === "regex") {
      try { new RegExp(r.pattern); } catch { return "invalid regex"; }
    }
    return null;
  };
  const anyRuleInvalid = () => filters().name_rules.some((r) => ruleIsInvalid(r) !== null);
  const anyPathInvalid = () =>
    filters().include_paths.some((p) => !pathIsInsideRoot(p)) ||
    filters().exclude_paths.some((p) => !pathIsInsideRoot(p));
  const canSave = () => dirty() && !saving() && !anyRuleInvalid() && !anyPathInvalid();

  const load = async () => {
    try {
      const resp = await scanFilters.get();
      setFilters(resp.filters);
      setOriginal(JSON.parse(JSON.stringify(resp.filters)));
      setFitsRoot(resp.fits_root);
      setDirty(false);
    } catch (e: any) {
      showToast(e?.message ?? "Failed to load scan filters", "error");
    }
  };

  createEffect(() => { load(); });

  const markDirty = () => setDirty(true);

  const updateFilters = (patch: Partial<ScanFilters>) => {
    setFilters({ ...filters(), ...patch });
    markDirty();
  };

  const save = async () => {
    setSaving(true);
    try {
      const resp = await scanFilters.put(filters());
      setFilters(resp.filters);
      setOriginal(JSON.parse(JSON.stringify(resp.filters)));
      setDirty(false);
      showToast("Scan filters saved");
      props.onConfigured?.();
      window.dispatchEvent(new CustomEvent("scan-filters-configured"));
    } catch (e: any) {
      showToast(e?.message ?? "Failed to save filters", "error");
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    setFilters(JSON.parse(JSON.stringify(original())));
    setDirty(false);
  };

  const runTest = async () => {
    if (!testPath().trim()) return;
    try {
      const r = await scanFilters.test(testPath().trim(), testKind());
      setTestResult({ verdict: r.verdict, matched: r.matched_rule_ids });
    } catch (e: any) {
      showToast(e?.message ?? "Test failed", "error");
    }
  };

  const applyNow = async () => {
    try {
      const dry = await scanFilters.applyNow(true);
      if (dry.matched === 0) {
        showToast("No image rows match the current exclude rules");
        return;
      }
      const ok = window.confirm(
        `This will remove ${dry.matched} image row(s) matching the current ` +
        `exclude rules. Rows will return on next scan if rules change. Continue?`
      );
      if (!ok) return;
      const res = await scanFilters.applyNow(false);
      showToast(`Removed ${res.matched} image row(s)`);
    } catch (e: any) {
      showToast(e?.message ?? "Apply now failed", "error");
    }
  };

  const pathIsInsideRoot = (p: string): boolean => {
    const root = fitsRoot();
    if (!root) return true; // can't validate yet, defer to server
    const trimmed = p.trim().replace(/[\\/]+$/, "");
    const rootTrimmed = root.replace(/[\\/]+$/, "");
    return trimmed === rootTrimmed || trimmed.startsWith(rootTrimmed + "/");
  };

  const PathList: Component<{
    label: string;
    help: string;
    values: string[];
    onRemove: (idx: number) => void;
    onAdd: (value: string) => void;
    onBrowse: () => void;
  }> = (p) => {
    const [draft, setDraft] = createSignal("");
    const draftError = () => {
      const d = draft().trim();
      if (!d) return null;
      if (!pathIsInsideRoot(d)) return `Path must be inside ${fitsRoot()}`;
      return null;
    };
    return (
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <h4 class="text-sm font-medium text-theme-text-primary">{p.label}</h4>
          <button
            class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors"
            onClick={p.onBrowse}
          >
            Browse…
          </button>
        </div>
        <p class="text-xs text-theme-text-secondary">{p.help}</p>
        <Show
          when={p.values.length > 0}
          fallback={<p class="text-xs italic text-theme-text-tertiary">None</p>}
        >
          <ul class="space-y-1">
            <For each={p.values}>{(v, i) => (
              <li class="flex items-center gap-2 text-sm">
                <code class={`flex-1 truncate ${pathIsInsideRoot(v) ? "" : "text-theme-error"}`}>
                  {v}
                </code>
                <button
                  class="text-xs text-theme-error hover:underline"
                  onClick={() => p.onRemove(i())}
                >
                  Remove
                </button>
              </li>
            )}</For>
          </ul>
        </Show>
        <div class="flex gap-2">
          <input
            type="text"
            placeholder={`${fitsRoot() || "/data/fits"}/subfolder`}
            value={draft()}
            onInput={(e) => setDraft(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !draftError() && draft().trim()) {
                p.onAdd(draft().trim());
                setDraft("");
              }
            }}
            class={`flex-1 px-2 py-1 text-xs bg-theme-input border rounded ${
              draftError() ? "border-theme-error" : "border-theme-border"
            }`}
          />
          <button
            class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-hover transition-colors"
            disabled={!draft().trim() || !!draftError()}
            onClick={() => {
              p.onAdd(draft().trim());
              setDraft("");
            }}
          >
            Add
          </button>
        </div>
        <Show when={draftError()}>
          <p class="text-xs text-theme-error">{draftError()}</p>
        </Show>
      </div>
    );
  };

  return (
    <details
      id="scan-filters-panel"
      class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border"
    >
      <summary class="p-4 cursor-pointer text-sm font-medium text-theme-text-primary">
        Scan filters — {filters().include_paths.length} include path(s),{" "}
        {filters().exclude_paths.length} exclude path(s),{" "}
        {filters().name_rules.length} name rule(s)
        <Show when={dirty()}>
          <span class="ml-2 text-xs text-amber-400">unsaved</span>
        </Show>
      </summary>

      <div class="p-4 border-t border-theme-border space-y-6">
        <div class="text-xs text-theme-text-secondary space-y-2">
          <p>
            Scan filters control what the scanner walks and ingests. There are two
            kinds of rules working together:
          </p>
          <ul class="list-disc pl-4 space-y-1">
            <li>
              <strong>Paths</strong>: <em>include paths</em> narrow the scan to a
              subset of the data root (empty means scan everything).{" "}
              <em>Exclude paths</em> prune subtrees that should never be walked.
            </li>
            <li>
              <strong>Name rules</strong>: glob, substring, or regex patterns that
              match on file names or folder names. Exclude rules win over includes.
              When at least one include rule exists for a target (file or folder),
              that target must match one of them.
            </li>
          </ul>
          <p>
            Example: include path <code>{fitsRoot() || "/data/fits"}/2025</code>,
            exclude path <code>{fitsRoot() || "/data/fits"}/2025/rejected</code>,
            plus a file exclude rule <code>*_bad.fits</code> and a folder include
            regex <code>^M\d+$</code>. The scanner walks only 2025, skips{" "}
            <code>rejected</code>, drops any file ending in <code>_bad.fits</code>,
            and only keeps files whose parent folder name matches an{" "}
            <code>M</code>-catalog designation.
          </p>
        </div>

        <PathList
          label="Include paths"
          help="When empty, scans the entire configured data path. When set, scans only these folders (each must resolve inside the data root)."
          values={filters().include_paths}
          onRemove={(idx) => {
            const next = filters().include_paths.filter((_, i) => i !== idx);
            updateFilters({ include_paths: next });
          }}
          onAdd={(v) => updateFilters({ include_paths: [...filters().include_paths, v] })}
          onBrowse={() => setBrowsing("include")}
        />

        <PathList
          label="Exclude paths"
          help="Subtrees to skip entirely. Exclude always wins over include."
          values={filters().exclude_paths}
          onRemove={(idx) => {
            const next = filters().exclude_paths.filter((_, i) => i !== idx);
            updateFilters({ exclude_paths: next });
          }}
          onAdd={(v) => updateFilters({ exclude_paths: [...filters().exclude_paths, v] })}
          onBrowse={() => setBrowsing("exclude")}
        />

        <div class="space-y-2">
          <h4 class="text-sm font-medium text-theme-text-primary">Name rules</h4>
          <p class="text-xs text-theme-text-secondary">
            Rules are evaluated in order: excludes first, then include-narrowing.
            Glob examples: <code>*_bad.fits</code>, <code>*_calibration</code>.
            Substring examples: <code>rejected</code>, <code>test_</code>. Regex
            examples: <code>^M\d+$</code>, <code>.*_v[0-9]+\.fits</code>.
          </p>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead>
                <tr class="text-theme-text-secondary">
                  <th class="text-left p-1">On</th>
                  <th class="text-left p-1">Action</th>
                  <th class="text-left p-1">Type</th>
                  <th class="text-left p-1">Target</th>
                  <th class="text-left p-1">Pattern</th>
                  <th class="p-1"></th>
                </tr>
              </thead>
              <tbody>
                <For each={filters().name_rules}>{(rule, i) => (
                  <tr class="border-t border-theme-border">
                    <td class="p-1">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        onChange={(e) => {
                          const next = [...filters().name_rules];
                          next[i()] = { ...rule, enabled: e.currentTarget.checked };
                          updateFilters({ name_rules: next });
                        }}
                      />
                    </td>
                    <td class="p-1">
                      <select
                        value={rule.action}
                        onChange={(e) => {
                          const next = [...filters().name_rules];
                          next[i()] = { ...rule, action: e.currentTarget.value as RuleAction };
                          updateFilters({ name_rules: next });
                        }}
                        class="bg-theme-input border border-theme-border rounded px-1"
                      >
                        <option value="include">include</option>
                        <option value="exclude">exclude</option>
                      </select>
                    </td>
                    <td class="p-1">
                      <select
                        value={rule.type}
                        onChange={(e) => {
                          const next = [...filters().name_rules];
                          next[i()] = { ...rule, type: e.currentTarget.value as RuleType };
                          updateFilters({ name_rules: next });
                        }}
                        class="bg-theme-input border border-theme-border rounded px-1"
                      >
                        <option value="glob">glob</option>
                        <option value="substring">substring</option>
                        <option value="regex">regex</option>
                      </select>
                    </td>
                    <td class="p-1">
                      <select
                        value={rule.target}
                        onChange={(e) => {
                          const next = [...filters().name_rules];
                          next[i()] = { ...rule, target: e.currentTarget.value as RuleTarget };
                          updateFilters({ name_rules: next });
                        }}
                        class="bg-theme-input border border-theme-border rounded px-1"
                      >
                        <option value="file">file</option>
                        <option value="folder">folder</option>
                      </select>
                    </td>
                    <td class="p-1">
                      <input
                        type="text"
                        value={rule.pattern}
                        placeholder={
                          rule.type === "glob" ? "*_bad.fits" :
                          rule.type === "regex" ? "^M\\d+$" : "rejected"
                        }
                        onInput={(e) => {
                          const next = [...filters().name_rules];
                          next[i()] = { ...rule, pattern: e.currentTarget.value };
                          updateFilters({ name_rules: next });
                        }}
                        class={`w-full px-1 py-0.5 bg-theme-input border rounded font-mono ${
                          ruleIsInvalid(rule) ? "border-theme-error" : "border-theme-border"
                        }`}
                        title={ruleIsInvalid(rule) ?? ""}
                      />
                    </td>
                    <td class="p-1">
                      <button
                        class="text-red-400"
                        onClick={() => {
                          const next = filters().name_rules.filter((_, idx) => idx !== i());
                          updateFilters({ name_rules: next });
                        }}
                        aria-label="Remove rule"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                )}</For>
              </tbody>
            </table>
          </div>
          <button
            class="px-2 py-1 text-xs rounded border border-theme-border"
            onClick={() => {
              const newRule: NameRule = {
                id: crypto.randomUUID(),
                action: "exclude",
                type: "glob",
                pattern: "",
                target: "file",
                enabled: true,
              };
              updateFilters({ name_rules: [...filters().name_rules, newRule] });
            }}
          >
            Add rule
          </button>
        </div>

        <div class="space-y-2">
          <h4 class="text-sm font-medium text-theme-text-primary">Test a path</h4>
          <p class="text-xs text-theme-text-secondary">
            Paste a file or folder path to see how the current rules would treat it.
            The path does not need to exist on disk. Unsaved changes are not used;
            save first to test them.
          </p>
          <div class="space-y-1">
            <div class="flex gap-2 flex-wrap">
              <input
                type="text"
                value={testPath()}
                onInput={(e) => setTestPath(e.currentTarget.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runTest(); }}
                placeholder={`${fitsRoot() || "/data/fits"}/2025/M31/frame_bad.fits`}
                class="flex-1 min-w-0 px-2 py-1 text-xs bg-theme-input border border-theme-border rounded font-mono"
              />
              <select
                value={testKind()}
                onChange={(e) =>
                  setTestKind(e.currentTarget.value as "auto" | "file" | "folder")
                }
                class="px-2 py-1 text-xs bg-theme-input border border-theme-border rounded"
                title="Treat the path as a file, a folder, or auto-detect"
              >
                <option value="auto">auto</option>
                <option value="file">file</option>
                <option value="folder">folder</option>
              </select>
              <button
                class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium hover:bg-theme-hover transition-colors"
                onClick={runTest}
              >
                Test
              </button>
            </div>
            <Show when={testResult()}>
              <div class="text-xs">
                Verdict:{" "}
                <strong
                  class={
                    testResult()!.verdict === "included"
                      ? "text-green-400"
                      : "text-red-400"
                  }
                >
                  {VERDICT_LABEL[testResult()!.verdict]}
                </strong>
                <Show when={testResult()!.matched.length > 0}>
                  {" "}
                  — matched rules: {testResult()!.matched.join(", ")}
                </Show>
              </div>
            </Show>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
            disabled={!canSave()}
            onClick={save}
            title={anyRuleInvalid() ? "One or more rules have empty or invalid patterns" : anyPathInvalid() ? "One or more paths are outside the data root" : ""}
          >
            {saving() ? "Saving…" : "Save filters"}
          </button>
          <button
            class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-hover transition-colors"
            disabled={!dirty()}
            onClick={revert}
          >
            Revert
          </button>
          <button
            class="px-4 py-1.5 bg-theme-warning/15 text-theme-warning border border-theme-warning/30 rounded text-sm font-medium hover:bg-theme-warning/25 transition-colors"
            onClick={applyNow}
          >
            Apply now
          </button>
        </div>
      </div>

      <FolderBrowserModal
        open={browsing() !== null}
        fitsRoot={fitsRoot()}
        title={
          browsing() === "include" ? "Add include paths" : "Add exclude paths"
        }
        onCancel={() => setBrowsing(null)}
        onConfirm={(paths) => {
          const key =
            browsing() === "include" ? "include_paths" : "exclude_paths";
          const current = filters()[key];
          const merged = Array.from(new Set([...current, ...paths]));
          updateFilters({ [key]: merged } as Partial<ScanFilters>);
          setBrowsing(null);
        }}
      />
    </details>
  );
};

export default ScanFiltersPanel;
