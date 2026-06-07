import { Component, For, Show, createSignal } from "solid-js";
import { api } from "../api/client";
import { showToast } from "./Toast";
import { useSettingsContext } from "./SettingsProvider";
import type { WbppSessionPreview, WbppFolderLevel, WbppGenerateResponse } from "../types";

interface Props {
  targetId: string;
  targetName: string;
  selectedDates: string[];
  onClose: () => void;
}

type OsChoice = "auto" | "windows" | "posix";

const DEFAULT_EXCLUSIONS = [
  "WBPP", "PixInsight", "finals", "WORK_AREA",
  "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
];

function detectOs(root: string): "windows" | "posix" {
  return /^[A-Za-z]:\\|\\/.test(root) ? "windows" : "posix";
}

function lastSegment(path: string): string {
  const parts = path.split(/[/\\]/).filter((p) => p.length > 0);
  return parts.length ? parts[parts.length - 1] : path;
}

const WbppExportModal: Component<Props> = (props) => {
  const ctx = useSettingsContext();
  const general = () => ctx.settings()?.general;

  const [libraryRoot, setLibraryRoot] = createSignal(general()?.wbpp_library_root ?? "");
  const [osChoice, setOsChoice] = createSignal<OsChoice>(
    (general()?.wbpp_default_os as OsChoice) ?? "auto",
  );
  const [stagingPath, setStagingPath] = createSignal(general()?.wbpp_staging_path ?? "");
  const [exclusionsText, setExclusionsText] = createSignal(
    (general()?.wbpp_exclusions ?? DEFAULT_EXCLUSIONS).join("\n"),
  );

  const [sessions, setSessions] = createSignal<WbppSessionPreview[]>([]);
  const [chosenLevels, setChosenLevels] = createSignal<Record<string, number>>({});
  const [previewOs, setPreviewOs] = createSignal<string>("");
  const [previewing, setPreviewing] = createSignal(false);
  const [generating, setGenerating] = createSignal(false);
  const [generated, setGenerated] = createSignal<WbppGenerateResponse | null>(null);
  const [copied, setCopied] = createSignal(false);
  const [showScript, setShowScript] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);

  const runCommand = (): string => {
    const g = generated();
    if (!g) return "";
    return g.target_os === "windows"
      ? `powershell -ExecutionPolicy Bypass -File .\\${g.filename}`
      : `chmod +x ${g.filename} && ./${g.filename}`;
  };

  const effectiveOs = (): "windows" | "posix" =>
    osChoice() === "auto" ? detectOs(libraryRoot()) : (osChoice() as "windows" | "posix");

  const targetOsParam = (): string | null => (osChoice() === "auto" ? null : osChoice());

  const parsedExclusions = (): string[] =>
    exclusionsText()
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

  const loadPreview = async () => {
    if (!libraryRoot().trim()) {
      setError("Enter your astrophotography library root path first.");
      return;
    }
    setError(null);
    setPreviewing(true);
    try {
      const resp = await api.wbppPreview({
        target_id: props.targetId,
        session_dates: props.selectedDates,
        chosen_levels: chosenLevels(),
        library_root: libraryRoot().trim(),
        target_os: targetOsParam(),
      });
      setSessions(resp.sessions);
      setPreviewOs(resp.target_os);
      setGenerated(null);
      // Initialize chosen levels to each session's default.
      const init: Record<string, number> = {};
      for (const s of resp.sessions) {
        init[s.session_date] = chosenLevels()[s.session_date] ?? s.default_level_index;
      }
      setChosenLevels(init);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load preview");
    } finally {
      setPreviewing(false);
    }
  };

  const selectLevel = (sessionDate: string, index: number) => {
    setChosenLevels({ ...chosenLevels(), [sessionDate]: index });
    // The previously generated script is now stale.
    setGenerated(null);
  };

  const generate = async () => {
    if (!libraryRoot().trim()) {
      setError("Enter your astrophotography library root path first.");
      return;
    }
    setError(null);
    setGenerating(true);
    setShowScript(false);
    try {
      const resp = await api.wbppGenerate({
        target_id: props.targetId,
        target_name: props.targetName,
        session_dates: props.selectedDates,
        chosen_levels: chosenLevels(),
        library_root: libraryRoot().trim(),
        target_os: targetOsParam(),
        staging_path: stagingPath().trim() || null,
        exclusions: parsedExclusions(),
      });
      setGenerated(resp);
      // Remember these export preferences so they prefill next time.
      const current = general();
      if (current) {
        try {
          await ctx.saveGeneral({
            ...current,
            wbpp_library_root: libraryRoot().trim() || null,
            wbpp_default_os: osChoice() === "auto" ? null : osChoice(),
            wbpp_staging_path: stagingPath().trim() || null,
            wbpp_exclusions: parsedExclusions(),
          });
        } catch {
          // Persisting preferences is best-effort; ignore failures.
        }
      }
    } catch (e: any) {
      setError(e?.message ?? "Failed to generate script");
    } finally {
      setGenerating(false);
    }
  };

  const downloadScript = () => {
    const g = generated();
    if (!g) return;
    const blob = new Blob([g.script], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = g.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast("WBPP script downloaded");
  };

  const copyScript = async () => {
    const g = generated();
    if (!g) return;
    try {
      await navigator.clipboard.writeText(g.script);
      setCopied(true);
      showToast("Script copied to clipboard");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Could not copy to clipboard.");
    }
  };

  return (
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={props.onClose}
    >
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-4xl w-full mx-4 max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border flex items-center justify-between">
          <h2 class="text-sm font-medium text-theme-text-primary">
            Export to WBPP - {props.targetName}
          </h2>
          <button
            class="text-theme-text-secondary hover:text-theme-text-primary"
            onClick={props.onClose}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
        </div>

        <div class="p-4 space-y-4">
          <p class="text-xs text-theme-text-secondary">
            Generates a copy script that stages the selected session folders so you can
            point PixInsight WBPP "Add Directory" at the staging root on your machine.
          </p>

          {/* Library root */}
          <div>
            <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
              Library root (on your machine)
            </label>
            <input
              type="text"
              class="w-full text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent"
              placeholder="e.g. Z:\Astro or /mnt/astro"
              value={libraryRoot()}
              onInput={(e) => setLibraryRoot(e.currentTarget.value)}
            />
            <p class="text-tiny text-theme-text-tertiary mt-1">
              The folder on your machine that mirrors the server's FITS data root.
            </p>
          </div>

          {/* OS selector */}
          <div>
            <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
              Script type
            </label>
            <select
              class="text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent"
              value={osChoice()}
              onChange={(e) => setOsChoice(e.currentTarget.value as OsChoice)}
            >
              <option value="auto">Auto-detect</option>
              <option value="windows">Windows (PowerShell .ps1)</option>
              <option value="posix">Linux / macOS (shell .sh)</option>
            </select>
            <Show when={osChoice() === "auto" && libraryRoot().trim()}>
              <span class="text-tiny text-theme-text-tertiary ml-2">
                Detected: {effectiveOs() === "windows" ? "Windows" : "Linux / macOS"}
              </span>
            </Show>
          </div>

          {/* Staging path */}
          <div>
            <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
              Staging path (optional)
            </label>
            <input
              type="text"
              class="w-full text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent"
              placeholder="Default: <library root>/_WBPP_staging/<target>"
              value={stagingPath()}
              onInput={(e) => setStagingPath(e.currentTarget.value)}
            />
          </div>

          {/* Exclusions */}
          <div>
            <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
              Excluded folder patterns (one per line)
            </label>
            <textarea
              class="w-full text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded text-theme-text-primary font-mono focus:outline-none focus:border-theme-accent"
              rows={4}
              value={exclusionsText()}
              onInput={(e) => setExclusionsText(e.currentTarget.value)}
            />
          </div>

          {/* Preview button */}
          <div>
            <button
              class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary disabled:opacity-50"
              onClick={loadPreview}
              disabled={previewing() || !libraryRoot().trim()}
            >
              {previewing() ? "Loading..." : "Preview folder levels"}
            </button>
          </div>

          {/* Error */}
          <Show when={error()}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded px-3 py-2">
              {error()}
            </div>
          </Show>

          {/* Per-session level pickers */}
          <Show when={sessions().length > 0}>
            <div class="space-y-3">
              <div class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide">
                Per-session folder level
              </div>
              <p class="text-tiny text-theme-text-tertiary">
                Pick which folder to copy for each session, from shallowest (closest to the
                library root) to deepest. A marked level (!) also contains other targets or
                dates and would be copied along with this session.
              </p>
              <For each={sessions()}>
                {(session) => (
                  <div class="bg-theme-elevated rounded p-3">
                    <div class="flex items-center justify-between mb-2">
                      <span class="text-xs font-medium text-theme-text-primary">
                        {session.session_date}
                      </span>
                      <span class="text-tiny text-theme-text-tertiary">
                        {session.total_frame_count} frames
                      </span>
                    </div>
                    <Show
                      when={session.levels.length > 0}
                      fallback={
                        <span class="text-tiny text-theme-text-tertiary">
                          No frames found for this session.
                        </span>
                      }
                    >
                      <div class="flex flex-wrap items-center gap-1">
                        <For each={session.levels}>
                          {(level: WbppFolderLevel, i) => (
                            <>
                              <Show when={i() > 0}>
                                <span class="text-theme-text-tertiary text-xs">/</span>
                              </Show>
                              <button
                                class={`text-tiny px-2 py-0.5 rounded border transition-colors ${
                                  chosenLevels()[session.session_date] === i()
                                    ? "bg-theme-accent/15 text-theme-accent border-theme-accent/30"
                                    : "bg-theme-surface text-theme-text-secondary border-theme-border hover:text-theme-text-primary"
                                }`}
                                title={
                                  level.is_contaminated
                                    ? `Also contains${
                                        level.other_targets.length
                                          ? ` other targets: ${level.other_targets.join(", ")}`
                                          : ""
                                      }${
                                        level.other_dates.length
                                          ? ` other dates: ${level.other_dates.join(", ")}`
                                          : ""
                                      }`
                                    : level.path
                                }
                                onClick={() => selectLevel(session.session_date, i())}
                              >
                                {lastSegment(level.path)}
                                <Show when={level.is_contaminated}>
                                  <span class="text-theme-error ml-1">!</span>
                                </Show>
                              </button>
                            </>
                          )}
                        </For>
                      </div>
                      <Show when={chosenLevels()[session.session_date] != null}>
                        <p class="text-tiny text-theme-text-tertiary mt-1 font-mono break-all">
                          {session.levels[chosenLevels()[session.session_date]]?.path}
                        </p>
                      </Show>
                    </Show>
                  </div>
                )}
              </For>
              <Show when={previewOs()}>
                <p class="text-tiny text-theme-text-tertiary">
                  Script type: {previewOs() === "windows" ? "Windows (PowerShell)" : "Linux / macOS (shell)"}
                </p>
              </Show>
            </div>
          </Show>

          {/* Generated output: compact summary + actions, script behind a toggle */}
          <Show when={generated()}>
            {(g) => (
              <div class="space-y-3 border-t border-theme-border pt-4">
                {/* Primary actions */}
                <div class="flex items-center gap-2">
                  <button
                    class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors"
                    onClick={downloadScript}
                  >
                    Download {g().filename}
                  </button>
                  <button
                    class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary"
                    onClick={copyScript}
                  >
                    {copied() ? "Copied!" : "Copy script"}
                  </button>
                </div>

                {/* Compact copy plan: one line per session */}
                <div class="text-tiny text-theme-text-tertiary">
                  {g().operations.length} folder{g().operations.length !== 1 ? "s" : ""} →{" "}
                  <span class="font-mono text-theme-text-secondary break-all">{g().staging_root}</span>
                </div>
                <div class="space-y-0.5">
                  <For each={g().operations}>
                    {(op) => (
                      <div
                        class="text-tiny font-mono text-theme-text-secondary truncate"
                        title={`${op.source}  →  ${op.destination}`}
                      >
                        {op.session_date}: {lastSegment(op.destination)}
                      </div>
                    )}
                  </For>
                </div>

                {/* Run command */}
                <div class="text-tiny">
                  <span class="text-theme-text-tertiary">Then run: </span>
                  <code class="font-mono text-theme-text-secondary break-all">{runCommand()}</code>
                </div>

                {/* Script preview behind a toggle */}
                <div>
                  <button
                    class="text-tiny text-theme-text-tertiary hover:text-theme-text-primary"
                    onClick={() => setShowScript(!showScript())}
                  >
                    {showScript() ? "▾ Hide script" : "▸ Show script"}
                  </button>
                  <Show when={showScript()}>
                    <pre class="mt-1 text-tiny font-mono bg-theme-base border border-theme-border rounded p-2 max-h-72 overflow-auto text-theme-text-secondary whitespace-pre">{g().script}</pre>
                  </Show>
                </div>
              </div>
            )}
          </Show>
        </div>

        <div class="p-4 border-t border-theme-border flex gap-2 justify-end">
          <button
            class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary"
            onClick={props.onClose}
          >
            Close
          </button>
          <button
            class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
            onClick={generate}
            disabled={generating() || !libraryRoot().trim()}
          >
            {generating() ? "Generating..." : generated() ? "Regenerate script" : "Generate script"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default WbppExportModal;
