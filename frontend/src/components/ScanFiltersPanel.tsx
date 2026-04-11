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
import SettingsHelpSection from "./settings/SettingsHelpSection";
import { showToast } from "./Toast";

const EMPTY: ScanFilters = { include_paths: [], exclude_paths: [], name_rules: [] };

const VERDICT_LABEL: Record<Verdict, string> = {
  included: "Will be scanned",
  excluded_by_path: "Skipped: excluded by path",
  excluded_by_rule: "Skipped: matched an exclude rule",
  excluded_by_missing_include: "Skipped: no include rule matched",
};

const VERDICT_HINT: Record<Verdict, string> = {
  included: "No rule caused this path to be skipped.",
  excluded_by_path: "A parent folder is listed under Exclude paths.",
  excluded_by_rule: "A name rule with action=exclude matched.",
  excluded_by_missing_include:
    "Include rules are set, but none of them matched this path.",
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
  const [applying, setApplying] = createSignal(false);
  const [testPath, setTestPath] = createSignal("");
  const [testKind, setTestKind] = createSignal<"auto" | "file" | "folder">("auto");
  const [testResult, setTestResult] = createSignal<
    null | { verdict: Verdict; matched: string[] }
  >(null);
  const [testing, setTesting] = createSignal(false);

  const describeRule = (id: string): string => {
    const r = filters().name_rules.find((x) => x.id === id);
    if (!r) return id.slice(0, 8);
    return `${r.action} ${r.type} on ${r.target}: ${r.pattern}`;
  };

  // Regex validation runs on the backend (Python `re`) because the scanner
  // uses that engine. Validating with `new RegExp(...)` here would reject
  // Python-only syntax like `(?i)foo` or `(?P<name>)` even though the
  // scanner accepts them. We cache results by pattern string so rendering
  // stays synchronous.
  const [regexCache, setRegexCache] = createSignal<Record<string, string | null>>({});
  const regexPending = new Set<string>();

  const validatePattern = (pattern: string) => {
    if (regexPending.has(pattern) || pattern in regexCache()) return;
    regexPending.add(pattern);
    scanFilters.validateRegex(pattern).then(
      (r) => {
        regexPending.delete(pattern);
        setRegexCache({ ...regexCache(), [pattern]: r.ok ? null : (r.error ?? "invalid regex") });
      },
      () => {
        regexPending.delete(pattern);
        // Network failure: don't block the user. Treat as valid for now;
        // the backend will reject on save if it's truly broken.
        setRegexCache({ ...regexCache(), [pattern]: null });
      },
    );
  };

  createEffect(() => {
    for (const r of filters().name_rules) {
      if (r.type === "regex" && r.pattern.trim()) validatePattern(r.pattern);
    }
  });

  const ruleIsInvalid = (r: NameRule): string | null => {
    if (!r.pattern.trim()) return "empty pattern";
    if (r.type === "regex") {
      const cached = regexCache()[r.pattern];
      if (cached === undefined) return null; // optimistic while validating
      return cached;
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
    if (!testPath().trim() || testing()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await scanFilters.test(testPath().trim(), testKind());
      setTestResult({ verdict: r.verdict, matched: r.matched_rule_ids });
    } catch (e: any) {
      showToast(e?.message ?? "Test failed", "error");
    } finally {
      setTesting(false);
    }
  };

  const applyNow = async () => {
    if (dirty()) {
      showToast(
        "Save your filter changes before running Apply now. It operates on " +
        "the last saved filters, not unsaved edits.",
        "error",
      );
      return;
    }
    setApplying(true);
    try {
      const dry = await scanFilters.applyNow(true);
      if (dry.matched === 0) {
        showToast(
          "Nothing to clean up. The saved filters do not exclude any " +
          "existing image rows in the catalog."
        );
        return;
      }
      const sample = (dry.sample_paths ?? []).slice(0, 10);
      const preview = sample.length > 0
        ? "\n\nExamples:\n" + sample.join("\n") +
          (dry.matched > sample.length ? `\n... and ${dry.matched - sample.length} more` : "")
        : "";
      const ok = window.confirm(
        `This will permanently remove ${dry.matched} image row(s) from the ` +
        `catalog because they are excluded by the saved filters. The files ` +
        `on disk are not touched, and rows will return on the next scan if ` +
        `the filters are relaxed.${preview}\n\nContinue?`
      );
      if (!ok) return;
      const res = await scanFilters.applyNow(false);
      showToast(`Removed ${res.matched} image row(s) from the catalog`);
    } catch (e: any) {
      showToast(e?.message ?? "Apply now failed", "error");
    } finally {
      setApplying(false);
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
      <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-2">
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
      </section>
    );
  };

  const firstVisit = (() => {
    try {
      const key = "galactilog.scanFiltersPanel.visited";
      if (localStorage.getItem(key)) return false;
      localStorage.setItem(key, "1");
      return true;
    } catch {
      return false;
    }
  })();

  return (
    <details
      id="scan-filters-panel"
      open={firstVisit}
      class="rounded-[var(--radius-sm)] border border-theme-border"
    >
      <summary class="p-3 cursor-pointer text-sm font-medium text-theme-text-primary">
        Path & name rules — {filters().include_paths.length} include path(s),{" "}
        {filters().exclude_paths.length} exclude path(s),{" "}
        {filters().name_rules.length} name rule(s)
        <Show when={dirty()}>
          <span class="ml-2 text-xs text-amber-400">unsaved</span>
        </Show>
      </summary>

      <div class="p-4 border-t border-theme-border space-y-6">
        <SettingsHelpSection tabId="scan_path_name_rules">
          <div class="space-y-3 text-xs text-theme-text-secondary">
            <p>
              Filtering happens in <strong class="text-theme-text-primary">two layers</strong>, applied in order.
            </p>

            <div class="space-y-1">
              <p class="text-theme-text-primary font-medium">1. Paths, which folders to walk</p>
              <ul class="list-disc pl-5 space-y-0.5">
                <li>
                  <strong>Include paths</strong> limit the scan to specific subtrees.
                  <em> Empty means scan everything under the data root.</em>
                </li>
                <li>
                  <strong>Exclude paths</strong> skip subtrees entirely.
                  <em> Exclude always wins over include.</em>
                </li>
              </ul>
            </div>

            <div class="space-y-1">
              <p class="text-theme-text-primary font-medium">2. Name rules, which files and folders to keep</p>
              <ul class="list-disc pl-5 space-y-0.5">
                <li>
                  Patterns match against <strong>file names</strong> or <strong>folder names</strong>, using
                  <strong> wildcard</strong>, <strong>substring</strong>, or <strong>regex</strong>.
                </li>
                <li>
                  <strong>Exclude rules</strong> are checked first, then <strong>include rules</strong> narrow the result.
                </li>
                <li>
                  If any include rule exists for a target kind (file or folder), that target
                  <strong> must</strong> match at least one.
                </li>
              </ul>
            </div>

            <div class="space-y-1">
              <p class="text-theme-text-primary font-medium">Example</p>
              <pre class="bg-theme-input border border-theme-border rounded p-2 font-mono text-label leading-relaxed whitespace-pre-wrap break-all">
{`include path   ${fitsRoot() || "/data/fits"}/2025
exclude path   ${fitsRoot() || "/data/fits"}/2025/rejected
exclude rule   *_bad.fits      (wildcard, file)
include rule   ^M\\d+$          (regex, folder)`}
              </pre>
              <p>
                Result: scans only <code>2025</code>, skips <code>rejected/</code>, drops any file ending in
                {" "}<code>_bad.fits</code>, and only keeps files whose parent folder name is an M-catalog
                designation like <code>M31</code> or <code>M42</code>.
              </p>
            </div>
          </div>
        </SettingsHelpSection>

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

        <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-2">
          <h4 class="text-sm font-medium text-theme-text-primary">Name rules</h4>
          <SettingsHelpSection tabId="scan_name_rules_syntax">
            <p class="text-xs text-theme-text-secondary">
              Pattern syntax: <strong>wildcard</strong> uses <code>*</code> for any
              characters and <code>?</code> for a single character (e.g.{" "}
              <code>*_bad.fits</code>, <code>*_calibration</code>).{" "}
              <strong>Substring</strong> matches anywhere inside the name,
              case-insensitive (e.g. <code>rejected</code>, <code>test_</code>).{" "}
              <strong>Regex</strong> is a full regular expression (e.g.{" "}
              <code>^M\d+$</code>, <code>.*_v[0-9]+\.fits</code>).
            </p>
          </SettingsHelpSection>
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
                        <option value="glob">wildcard</option>
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
        </section>

        <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-2">
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
                class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium hover:bg-theme-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={runTest}
                disabled={testing() || !testPath().trim()}
              >
                {testing() ? "Testing…" : "Test"}
              </button>
            </div>
            <Show when={testResult()}>
              <div class="text-xs space-y-0.5">
                <div>
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
                </div>
                <Show when={testResult()!.matched.length > 0}>
                  <ul class="list-disc list-inside text-theme-text-secondary">
                    <For each={testResult()!.matched}>
                      {(id) => (
                        <li class="font-mono">{describeRule(id)}</li>
                      )}
                    </For>
                  </ul>
                </Show>
                <div class="text-theme-text-secondary">
                  {VERDICT_HINT[testResult()!.verdict]}
                  <Show
                    when={
                      testResult()!.verdict === "included" &&
                      filters().name_rules.some((r) => r.action === "exclude")
                    }
                  >
                    {" "}None of your exclude rules matched this path. If you
                    expected one to match, double-check the pattern against
                    the exact filename.
                  </Show>
                </div>
              </div>
            </Show>
          </div>
        </section>

        <div class="flex flex-wrap gap-2">
          <button
            class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
            disabled={!canSave()}
            onClick={save}
            title={
              anyRuleInvalid()
                ? "One or more rules have empty or invalid patterns"
                : anyPathInvalid()
                ? "One or more paths are outside the data root"
                : "Store the current filters. Future scans will use them. Does not touch the existing catalog."
            }
          >
            {saving() ? "Saving…" : "Save rules"}
          </button>
          <button
            class="px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-hover transition-colors"
            disabled={!dirty()}
            onClick={revert}
            title="Discard unsaved changes and reload the last saved filters"
          >
            Revert
          </button>
          <button
            class="px-4 py-1.5 bg-theme-warning/15 text-theme-warning border border-theme-warning/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-warning/25 transition-colors"
            disabled={dirty() || applying()}
            onClick={applyNow}
            title={
              dirty()
                ? "Save your filter changes first. Apply now operates on the last saved filters."
                : "Remove already-ingested image rows that match the current exclude rules. Destructive. You will see a confirmation with the row count and example paths before anything is deleted."
            }
          >
            {applying() ? "Checking\u2026" : "Apply now"}
          </button>
        </div>
      </div>

      <FolderBrowserModal
        open={browsing() !== null}
        fitsRoot={fitsRoot()}
        title={
          browsing() === "include" ? "Add include paths" : "Add exclude paths"
        }
        existing={
          browsing() === "include"
            ? filters().include_paths
            : filters().exclude_paths
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
