import { Component, For, Show, createSignal, createMemo, onMount } from "solid-js";
import { api } from "../api/client";
import { showToast } from "./Toast";
import { useSettingsContext } from "./SettingsProvider";
import {
  isFsAccessSupported,
  runBrowserCopy,
  CopyCancelledError,
  pickDirectory,
  queryHandlePermission,
  requestHandlePermission,
  loadStoredHandle,
  storeHandle,
  HANDLE_KEYS,
  type PermState,
} from "../lib/wbppBrowserCopy";
import type { WbppSessionPreview, WbppFolderLevel, WbppGenerateResponse, WbppCopyOperation } from "../types";

interface Props {
  targetId: string;
  targetName: string;
  selectedDates: string[];
  onClose: () => void;
}

type OsChoice = "auto" | "windows" | "posix";
type PermOrNone = PermState | "none";

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

function permText(p: PermOrNone): string {
  switch (p) {
    case "granted": return "access granted";
    case "denied": return "access denied";
    case "prompt": return "needs permission";
    case "unsupported": return "unsupported";
    default: return "not selected";
  }
}

function permClass(p: PermOrNone): string {
  switch (p) {
    case "granted": return "text-green-400";
    case "denied": return "text-theme-error";
    case "prompt": return "text-yellow-400";
    default: return "text-theme-text-tertiary";
  }
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
  const [showLevels, setShowLevels] = createSignal(true);
  const [previewing, setPreviewing] = createSignal(false);

  const [generating, setGenerating] = createSignal(false);
  const [generated, setGenerated] = createSignal<WbppGenerateResponse | null>(null);
  const [copied, setCopied] = createSignal(false);
  const [showScript, setShowScript] = createSignal(false);

  // Defaults come from Settings; overrides are per-export. Auto-expand when no
  // default library root is configured, since one is required.
  const [showOverrides, setShowOverrides] = createSignal(!(general()?.wbpp_library_root ?? "").trim());
  const [savedDefaults, setSavedDefaults] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);

  // Browser-native copy (File System Access API) state.
  const canBrowserCopy = isFsAccessSupported();
  const [srcHandle, setSrcHandle] = createSignal<any>(null);
  const [destHandle, setDestHandle] = createSignal<any>(null);
  const [srcPerm, setSrcPerm] = createSignal<PermOrNone>("none");
  const [destPerm, setDestPerm] = createSignal<PermOrNone>("none");
  const [copying, setCopying] = createSignal(false);
  const [copyDone, setCopyDone] = createSignal(0);
  const [copyTotal, setCopyTotal] = createSignal(0);
  const [copyLabel, setCopyLabel] = createSignal("");
  const [copyFinished, setCopyFinished] = createSignal<number | null>(null);
  let abortController: AbortController | null = null;

  onMount(async () => {
    if (!canBrowserCopy) return;
    const s = await loadStoredHandle(HANDLE_KEYS.source);
    if (s) {
      setSrcHandle(s);
      setSrcPerm(await queryHandlePermission(s, "read"));
    }
    const d = await loadStoredHandle(HANDLE_KEYS.dest);
    if (d) {
      setDestHandle(d);
      setDestPerm(await queryHandlePermission(d, "readwrite"));
    }
  });

  const effectiveOs = (): "windows" | "posix" =>
    osChoice() === "auto" ? detectOs(libraryRoot()) : (osChoice() as "windows" | "posix");

  const targetOsParam = (): string | null => (osChoice() === "auto" ? null : osChoice());

  const parsedExclusions = (): string[] =>
    exclusionsText()
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

  const sep = (): string => (effectiveOs() === "windows" ? "\\" : "/");

  const stagingRoot = (): string => {
    const override = stagingPath().trim();
    if (override) return override;
    const lib = libraryRoot().trim().replace(/[\\/]+$/, "");
    return `${lib}${sep()}_WBPP_staging${sep()}${props.targetName.replace(/ /g, "_")}`;
  };

  // The copy plan is derived purely from the previewed sessions + chosen levels,
  // so it is available without generating the script.
  const plan = createMemo<WbppCopyOperation[]>(() => {
    const chosen: { date: string; level: WbppFolderLevel }[] = [];
    for (const s of sessions()) {
      if (!s.levels.length) continue;
      const idx = Math.max(0, Math.min(chosenLevels()[s.session_date] ?? s.default_level_index, s.levels.length - 1));
      chosen.push({ date: s.session_date, level: s.levels[idx] });
    }
    const basenames = chosen.map((c) => lastSegment(c.level.path));
    const counts: Record<string, number> = {};
    for (const b of basenames) counts[b] = (counts[b] ?? 0) + 1;
    const root = stagingRoot();
    return chosen.map((c, i) => {
      const base = basenames[i];
      const entry = counts[base] > 1 ? `${c.date}_${base}` : base;
      return {
        session_date: c.date,
        source: c.level.path,
        source_relative: c.level.relative_path,
        dest_entry: entry,
        destination: `${root}${sep()}${entry}`,
      };
    });
  });

  const runCommand = (): string => {
    const g = generated();
    if (!g) return "";
    return g.target_os === "windows"
      ? `powershell -ExecutionPolicy Bypass -File .\\${g.filename}`
      : `chmod +x ${g.filename} && ./${g.filename}`;
  };

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
      setShowLevels(true);
      setGenerated(null);
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
    // The previously generated script is now stale (the plan updates reactively).
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
      setShowScript(true);
    } catch (e: any) {
      setError(e?.message ?? "Failed to generate script");
    } finally {
      setGenerating(false);
    }
  };

  const saveAsDefaults = async () => {
    const current = general();
    if (!current) return;
    try {
      await ctx.saveGeneral({
        ...current,
        wbpp_library_root: libraryRoot().trim() || null,
        wbpp_default_os: osChoice() === "auto" ? null : osChoice(),
        wbpp_staging_path: stagingPath().trim() || null,
        wbpp_exclusions: parsedExclusions(),
      });
      setSavedDefaults(true);
      showToast("Saved as defaults");
      setTimeout(() => setSavedDefaults(false), 1500);
    } catch {
      setError("Could not save defaults.");
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

  // --- Browser folder handles + permissions ---

  const chooseSource = async () => {
    setError(null);
    try {
      const h = await pickDirectory("read", "wbpp-library");
      setSrcHandle(h);
      await storeHandle(HANDLE_KEYS.source, h);
      setSrcPerm(await queryHandlePermission(h, "read"));
    } catch (e: any) {
      if (!(e instanceof CopyCancelledError)) setError(e?.message ?? "Could not open the folder picker.");
    }
  };

  const chooseDest = async () => {
    setError(null);
    try {
      const h = await pickDirectory("readwrite", "wbpp-staging");
      setDestHandle(h);
      await storeHandle(HANDLE_KEYS.dest, h);
      setDestPerm(await queryHandlePermission(h, "readwrite"));
    } catch (e: any) {
      if (!(e instanceof CopyCancelledError)) setError(e?.message ?? "Could not open the folder picker.");
    }
  };

  const grantSource = async () => {
    const h = srcHandle();
    if (!h) return;
    try { setSrcPerm(await requestHandlePermission(h, "read")); } catch { /* ignore */ }
  };

  const grantDest = async () => {
    const h = destHandle();
    if (!h) return;
    try { setDestPerm(await requestHandlePermission(h, "readwrite")); } catch { /* ignore */ }
  };

  const startBrowserCopy = async () => {
    if (!srcHandle() || !destHandle()) {
      setError("Choose a library folder and a destination folder first.");
      return;
    }
    if (!plan().length) {
      setError("Nothing to copy - preview the folder levels first.");
      return;
    }
    setError(null);
    setCopyFinished(null);
    setCopyDone(0);
    setCopyTotal(0);
    setCopyLabel("");
    abortController = new AbortController();
    setCopying(true);
    try {
      const result = await runBrowserCopy(srcHandle(), destHandle(), {
        operations: plan(),
        exclusions: parsedExclusions(),
        onProgress: (done, total, label) => {
          setCopyDone(done);
          setCopyTotal(total);
          setCopyLabel(label);
        },
        signal: abortController.signal,
      });
      setCopyFinished(result.copied);
      setSrcPerm("granted");
      setDestPerm("granted");
      showToast(`Copied ${result.copied} file${result.copied !== 1 ? "s" : ""} to ${result.destinationName}`);
    } catch (e: any) {
      if (!(e instanceof CopyCancelledError)) setError(e?.message ?? "Browser copy failed.");
    } finally {
      setCopying(false);
      abortController = null;
    }
  };

  const stopCopy = () => abortController?.abort();

  const copyReady = () => !!srcHandle() && !!destHandle() && srcPerm() !== "denied" && destPerm() !== "denied";

  // Raised section card, matching the target page.
  const cardClass =
    "bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4";

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

        <div class="p-4 space-y-4 bg-theme-base">
          <p class="text-xs text-theme-text-secondary">
            Stages the selected session folders for PixInsight WBPP. Copy directly in your
            browser, or download a script to run on the machine where PixInsight is installed.
          </p>

          {/* Settings card */}
          <div class={`${cardClass} space-y-3`}>
            {/* Defaults summary + override toggle */}
            <div class="flex items-center justify-between gap-2">
              <div class="text-tiny text-theme-text-tertiary truncate">
                <Show
                  when={libraryRoot().trim()}
                  fallback={<span class="text-theme-error">No library root set - set defaults in Settings or override below.</span>}
                >
                  <span class="font-mono text-theme-text-secondary">{libraryRoot()}</span>
                  {" · "}
                  {effectiveOs() === "windows" ? "Windows" : "Linux / macOS"}
                  {stagingPath().trim() ? " · custom staging" : " · default staging"}
                </Show>
              </div>
              <button
                class="text-tiny text-theme-text-tertiary hover:text-theme-text-primary shrink-0"
                onClick={() => setShowOverrides(!showOverrides())}
              >
                {showOverrides() ? "▾ Hide settings" : "▸ Override settings"}
              </button>
            </div>

            {/* Override settings (defaults live in Settings > AstroBin & NINA) */}
            <Show when={showOverrides()}>
              <div class="space-y-4 border-t border-theme-border pt-3">
                <p class="text-tiny text-theme-text-tertiary">
                  These default to your Settings &gt; AstroBin &amp; NINA &gt; PixInsight Export values.
                  Changes here apply to this export only unless you save them as defaults.
                </p>

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
              </div>

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

                <button
                  class="text-tiny text-theme-accent hover:text-theme-accent-hover transition-colors disabled:opacity-50"
                  onClick={saveAsDefaults}
                  disabled={!libraryRoot().trim()}
                >
                  {savedDefaults() ? "Saved!" : "Save as defaults"}
                </button>
              </div>
            </Show>
          </div>

          {/* Error */}
          <Show when={error()}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded px-3 py-2">
              {error()}
            </div>
          </Show>

          {/* Folder levels card */}
          <div class={`${cardClass} space-y-3`}>
            <div>
              <button
                class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary disabled:opacity-50"
                onClick={loadPreview}
                disabled={previewing() || !libraryRoot().trim()}
              >
                {previewing() ? "Loading..." : sessions().length ? "Refresh folder levels" : "Preview folder levels"}
              </button>
            </div>

            {/* Per-session level pickers (collapsible) */}
            <Show when={sessions().length > 0}>
              <button
                class="flex items-center gap-1 text-xs font-medium text-theme-text-secondary uppercase tracking-wide hover:text-theme-text-primary"
                onClick={() => setShowLevels(!showLevels())}
              >
                <span>{showLevels() ? "▾" : "▸"}</span> Per-session folder level
              </button>
              <Show when={showLevels()}>
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
              </Show>
            </Show>
          </div>

          {/* Copy plan + copy controls card (available once previewed) */}
          <Show when={plan().length > 0}>
            <div class={`${cardClass} space-y-3`}>
              <div class="text-tiny text-theme-text-tertiary">
                {plan().length} folder{plan().length !== 1 ? "s" : ""} →{" "}
                <span class="font-mono text-theme-text-secondary break-all">{stagingRoot()}</span>
              </div>
              <div class="space-y-0.5">
                <For each={plan()}>
                  {(op) => (
                    <div
                      class="text-tiny font-mono text-theme-text-secondary truncate"
                      title={`${op.source}  →  ${op.destination}`}
                    >
                      {op.session_date}: {op.dest_entry}
                    </div>
                  )}
                </For>
              </div>

              {/* Browser copy */}
              <Show
                when={canBrowserCopy}
                fallback={
                  <p class="text-tiny text-theme-text-tertiary">
                    In-browser copy needs a Chromium browser (Chrome/Edge) over HTTPS or localhost.
                    Use "Generate script" below to download a copy script instead.
                  </p>
                }
              >
                <div class="space-y-2 bg-theme-base border border-theme-border rounded p-3">
                  <div class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide">
                    Copy in browser
                  </div>

                  {/* Source folder row */}
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-tiny text-theme-text-tertiary w-24">Library folder</span>
                    <button
                      class="text-tiny px-2 py-0.5 bg-theme-surface border border-theme-border rounded hover:text-theme-text-primary text-theme-text-secondary"
                      onClick={chooseSource}
                    >
                      {srcHandle() ? "Change..." : "Choose..."}
                    </button>
                    <Show when={srcHandle()}>
                      <span class="text-tiny font-mono text-theme-text-secondary truncate max-w-[12rem]">{srcHandle().name}</span>
                    </Show>
                    <span class={`text-tiny ${permClass(srcPerm())}`}>{permText(srcPerm())}</span>
                    <Show when={srcHandle() && srcPerm() === "prompt"}>
                      <button class="text-tiny text-theme-accent hover:text-theme-accent-hover" onClick={grantSource}>Grant access</button>
                    </Show>
                  </div>

                  {/* Destination folder row */}
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-tiny text-theme-text-tertiary w-24">Destination</span>
                    <button
                      class="text-tiny px-2 py-0.5 bg-theme-surface border border-theme-border rounded hover:text-theme-text-primary text-theme-text-secondary"
                      onClick={chooseDest}
                    >
                      {destHandle() ? "Change..." : "Choose..."}
                    </button>
                    <Show when={destHandle()}>
                      <span class="text-tiny font-mono text-theme-text-secondary truncate max-w-[12rem]">{destHandle().name}</span>
                    </Show>
                    <span class={`text-tiny ${permClass(destPerm())}`}>{permText(destPerm())}</span>
                    <Show when={destHandle() && destPerm() === "prompt"}>
                      <button class="text-tiny text-theme-accent hover:text-theme-accent-hover" onClick={grantDest}>Grant access</button>
                    </Show>
                  </div>
                  <p class="text-tiny text-theme-text-tertiary">
                    Pick your library root (the folder that mirrors the server's FITS data root) and a destination.
                    Folders are remembered for next time.
                  </p>

                  {/* Copy / Stop */}
                  <div class="flex items-center gap-2">
                    <button
                      class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
                      onClick={startBrowserCopy}
                      disabled={copying() || !copyReady()}
                    >
                      {copying() ? "Copying..." : "Copy files now"}
                    </button>
                    <Show when={copying()}>
                      <button
                        class="text-xs px-3 py-1.5 bg-theme-surface border border-theme-border rounded hover:text-theme-text-primary text-theme-text-secondary transition-colors"
                        onClick={stopCopy}
                      >
                        Stop
                      </button>
                    </Show>
                  </div>

                  {/* Progress */}
                  <Show when={copying() || copyFinished() !== null}>
                    <div class="space-y-1">
                      <div class="h-1.5 bg-theme-elevated rounded overflow-hidden">
                        <div
                          class="h-full bg-theme-accent transition-all"
                          style={{
                            width: `${copyTotal() > 0 ? Math.round((copyDone() / copyTotal()) * 100) : (copyFinished() !== null ? 100 : 0)}%`,
                          }}
                        />
                      </div>
                      <Show
                        when={copyFinished() === null}
                        fallback={
                          <p class="text-tiny text-theme-text-tertiary">
                            Done. Copied {copyFinished()} file{copyFinished() !== 1 ? "s" : ""}. Open WBPP and use Add Directory on the destination.
                          </p>
                        }
                      >
                        <p class="text-tiny text-theme-text-tertiary truncate">
                          {copyTotal() > 0 ? `${copyDone()} / ${copyTotal()} - ` : "Scanning... "}
                          <span class="font-mono">{copyLabel()}</span>
                        </p>
                      </Show>
                    </div>
                  </Show>
                </div>
              </Show>

              {/* Script output (only after Generate script) */}
              <Show when={generated()}>
                {(g) => (
                  <div class="space-y-2">
                    <div class="flex items-center gap-2 flex-wrap">
                      <button
                        class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary"
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
                    <div class="text-tiny">
                      <span class="text-theme-text-tertiary">Then run: </span>
                      <code class="font-mono text-theme-text-secondary break-all">{runCommand()}</code>
                    </div>
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
