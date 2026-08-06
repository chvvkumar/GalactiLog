import {
  Component,
  For,
  Show,
  createSignal,
  createMemo,
  createEffect,
  untrack,
} from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { showToast } from "./Toast";
import { useSettingsContext } from "./SettingsProvider";
import Dialog from "./Dialog";
import Button from "./ui/Button";
import HelpPopover from "./HelpPopover";
import IconButton from "./ui/IconButton";
import WbppQualityPanel from "./wbpp/WbppQualityPanel";
import { detectOs, type PathOs } from "./wbpp/paths";
import {
  computeVerdicts,
  qualityTotals,
  type FrameVerdict,
  type QualityConfig,
} from "../lib/wbppQualityFilter";
import { loadWbppQualityState, saveWbppQualityState } from "../lib/wbppQualityStore";
import {
  isFsAccessSupported,
  pickDirectory,
  CopyCancelledError,
} from "../lib/wbppBrowserCopy";
import {
  scanForNames,
  moveMatches,
  type MoveScan,
  type MoveResult,
} from "../lib/frameListBrowserMove";
import {
  isIncluded,
  selectedFrames,
  overrideKey,
  explorerSearchString,
  plainNameList,
  moveScript,
  type FrameListMode,
  type FrameSelectionOptions,
} from "../lib/frameListFormats";
import { contentWidthClass } from "../utils/format";
import type { SessionDetail } from "../api/types";

interface Props {
  targetId: string;
  targetName: string;
  selectedDates: string[];
  sessionCache: Record<string, SessionDetail>;
  onClose: () => void;
}

type FrameListFormat = "explorer" | "names" | "script";

const FIELD_CLASS =
  "text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:outline-none focus:border-theme-accent";

/**
 * Copy Frame List: the third export route on the target detail page. Renders
 * the shared quality panel (same thresholds, same per-rig store as the WBPP
 * export) with per-row include overrides and a full-path column, and copies
 * the good or bad frame NAMES as an Explorer search string, a plain list, or a
 * move/delete script -- so bad frames can be bulk deleted before stacking.
 *
 * Chrome, session fetch, rig resolution, and persistence all mirror
 * WbppExportModal so the two export modals read and behave as siblings.
 */
const FrameListModal: Component<Props> = (props) => {
  const ctx = useSettingsContext();
  const general = () => ctx.settings()?.general;

  // Session details keyed by date, seeded from props.sessionCache then filled
  // in for any selected date not already cached.
  const [sessionDetails, setSessionDetails] = createSignal<Record<string, SessionDetail>>({});
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);
  // Selected dates whose detail fetch failed: the table silently covering only
  // part of the selection would misrepresent what the copy/move acts on.
  const [failedDates, setFailedDates] = createSignal<string[]>([]);

  /**
   * The rig the selected sessions were shot on: the first non-null
   * `FrameRecord.rig` across the selected dates, reading the page's cache
   * first and any details this modal fetched itself second. Null until a frame
   * with a rig is available, in which case the store's rig-less fallback slot
   * is used. Mirrors WbppExportModal so both modals resolve the SAME store key.
   */
  const rigId = createMemo<string | null>(() => {
    const fetched = sessionDetails();
    for (const date of props.selectedDates) {
      const detail = props.sessionCache[date] ?? fetched[date];
      for (const f of detail?.frames ?? []) {
        if (f.rig != null) return f.rig;
      }
    }
    return null;
  });

  // Hydrate the toggle and config from the per-rig store; the effect below
  // re-hydrates if the rig resolves or changes later (see WbppExportModal).
  let loadedForRig = rigId();
  const initialQualityState = loadWbppQualityState(loadedForRig);
  const [qualityFilterOn, setQualityFilterOn] = createSignal(initialQualityState.enabled);
  const [qualityConfig, setQualityConfig] = createSignal<QualityConfig>(initialQualityState.config);

  const [mode, setMode] = createSignal<FrameListMode>("bad");
  const [includeUnmeasured, setIncludeUnmeasured] = createSignal(true);
  // Sparse per-row overrides keyed by the lib's overrideKey (session date +
  // source_relative, since the same source_relative can appear under two
  // selected dates). Cleared on ANY change
  // that alters what the computed verdicts mean (constraints, baseline, the
  // enable flag, mode, include-unmeasured): a hand edit must never silently
  // survive a semantics change it was not made under.
  const [overrides, setOverrides] = createSignal<Record<string, boolean>>({});
  const [format, setFormat] = createSignal<FrameListFormat>("explorer");
  const [baseFolder, setBaseFolder] = createSignal(
    general()?.frame_list_base_folder ?? general()?.wbpp_library_root ?? "",
  );

  // Set by the change handlers only, never by hydration. Decides who wins a
  // rig transition: the user's in-session edits, or the rig's stored state.
  let userEdited = false;
  const changeQualityEnabled = (on: boolean) => {
    userEdited = true;
    setOverrides({});
    setQualityFilterOn(on);
  };
  const changeQualityConfig = (cfg: QualityConfig) => {
    userEdited = true;
    setOverrides({});
    setQualityConfig(cfg);
  };
  const changeMode = (m: FrameListMode) => {
    if (m === mode()) return;
    setOverrides({});
    setMode(m);
  };
  const changeIncludeUnmeasured = (on: boolean) => {
    setOverrides({});
    setIncludeUnmeasured(on);
  };

  // Rig transitions: edits win, an untouched modal hydrates from storage.
  // Mirrors WbppExportModal; hydration replaces the config, so the overrides
  // reset with it.
  createEffect(() => {
    const rig = rigId();
    if (rig === loadedForRig) return;
    loadedForRig = rig;
    if (userEdited) {
      saveWbppQualityState(rig, {
        enabled: untrack(qualityFilterOn),
        config: untrack(qualityConfig),
      });
      return;
    }
    const st = loadWbppQualityState(rig);
    setOverrides({});
    setQualityFilterOn(st.enabled);
    setQualityConfig(st.config);
  });

  // Write every change straight back to the per-rig store (shared with the
  // WBPP export modal: tuning a threshold here retunes that export too).
  createEffect(() => {
    const state = { enabled: qualityFilterOn(), config: qualityConfig() };
    saveWbppQualityState(untrack(rigId), state);
  });

  /**
   * Seed from the page's cache and fetch any missing selected date. Same shape
   * as WbppExportModal's fetch effect, including the untracked read of this
   * effect's own output (see the loop postmortem there), but unconditional:
   * the frame list always needs the frames, there is no filter toggle gating
   * whether they exist.
   */
  createEffect(() => {
    const have = untrack(sessionDetails);
    const seeded: Record<string, SessionDetail> = {};
    const missing: string[] = [];
    for (const date of props.selectedDates) {
      const cached = props.sessionCache[date] ?? have[date];
      if (cached) seeded[date] = cached;
      else missing.push(date);
    }
    setSessionDetails(seeded);
    if (missing.length === 0) {
      setFailedDates([]);
      return;
    }
    setLoading(true);
    Promise.all(
      missing.map((date) =>
        (apiClient
          .GET("/api/targets/{target_id}/sessions/{date}", {
            params: { path: { target_id: props.targetId, date } },
          })
          .then(unwrap) as Promise<SessionDetail>)
          .then((detail) => ({ date, detail: detail as SessionDetail | null }))
          .catch(() => ({ date, detail: null as SessionDetail | null })),
      ),
    )
      .then((results) => {
        setSessionDetails((prev) => {
          const next = { ...prev };
          for (const r of results) if (r.detail) next[r.date] = r.detail;
          return next;
        });
        setFailedDates(results.filter((r) => r.detail == null).map((r) => r.date));
      })
      .finally(() => setLoading(false));
  });

  const verdicts = createMemo<FrameVerdict[]>(() =>
    computeVerdicts(sessionDetails(), props.selectedDates, qualityConfig()),
  );
  const totals = createMemo(() => qualityTotals(verdicts()));

  // With the master toggle off no gate is running, so every frame reads as a
  // pass for selection purposes (matching the panel, which shows every row as
  // Copy): bad mode selects nothing, good mode selects everything.
  const neutralize = (v: FrameVerdict): FrameVerdict => ({
    ...v,
    keep: true,
    reason: "pass",
    failures: [],
    failedBy: null,
  });
  const effective = (v: FrameVerdict): FrameVerdict => (qualityFilterOn() ? v : neutralize(v));
  const effectiveVerdicts = createMemo<FrameVerdict[]>(() =>
    qualityFilterOn() ? verdicts() : verdicts().map(neutralize),
  );

  const selectionOpts = (): FrameSelectionOptions => ({
    mode: mode(),
    includeUnmeasured: includeUnmeasured(),
    overrides: overrides(),
  });

  const rowIncluded = (v: FrameVerdict): boolean => isIncluded(effective(v), selectionOpts());

  const selected = createMemo<FrameVerdict[]>(() =>
    selectedFrames(effectiveVerdicts(), selectionOpts()),
  );

  // The clipboard formats and the browser move address files by bare name, so
  // a name shared by frames across the selected sessions must appear once:
  // duplicating it would double-count the button and double-list the payload.
  // First-seen order is preserved.
  const uniqueNames = createMemo<string[]>(() => {
    const seen = new Set<string>();
    const names: string[] = [];
    for (const v of selected()) {
      const n = v.frame.file_name;
      if (seen.has(n)) continue;
      seen.add(n);
      names.push(n);
    }
    return names;
  });

  // Flip the row to the opposite of its current answer; when that lands back
  // on the computed (override-free) value, drop the key so the map stays sparse.
  const toggleInclude = (v: FrameVerdict) => {
    const key = overrideKey(v);
    const computed = isIncluded(effective(v), { ...selectionOpts(), overrides: {} });
    const next = !rowIncluded(v);
    setOverrides((prev) => {
      const map = { ...prev };
      if (next === computed) delete map[key];
      else map[key] = next;
      return map;
    });
  };

  // The persisted script-type preference wins; detection from the base folder
  // is the fallback for an unset preference only.
  const scriptOs = (): PathOs =>
    (general()?.wbpp_default_os as PathOs | null | undefined) ?? detectOs(baseFolder());

  const copyDisabled = () =>
    selected().length === 0 || (format() === "script" && baseFolder().trim() === "");

  const nameCount = () => uniqueNames().length;
  const namesWord = () => (nameCount() === 1 ? "name" : "names");
  const copyLabel = () =>
    format() === "script"
      ? `Copy script (${nameCount()} ${namesWord()})`
      : `Copy ${nameCount()} ${namesWord()}`;

  const doCopy = async () => {
    const names = uniqueNames();
    let text: string;
    if (format() === "explorer") text = explorerSearchString(names);
    else if (format() === "names") text = plainNameList(names);
    else text = moveScript(names, baseFolder().trim(), scriptOs());
    try {
      await navigator.clipboard.writeText(text);
      setError(null);
      showToast(
        format() === "script"
          ? `Move script for ${names.length} ${namesWord()} copied to clipboard`
          : `${names.length} ${namesWord()} copied to clipboard`,
      );
    } catch {
      setError("Could not copy to clipboard.");
      return;
    }
    // Remember the base folder for next time, same route as the WBPP modal's
    // wbpp_library_root. Best effort: a failed save must not undo the copy.
    if (format() === "script") {
      const current = general();
      if (current && (current.frame_list_base_folder ?? "") !== baseFolder().trim()) {
        try {
          await ctx.saveGeneral({
            ...current,
            frame_list_base_folder: baseFolder().trim() || null,
          });
        } catch {
          // The copy already succeeded; losing the remembered folder is not
          // worth an error banner.
        }
      }
    }
  };

  // --- Browser-native move to _rejected -------------------------------------
  //
  // Chromium-only (File System Access API). The picked handle is NOT persisted
  // across sessions: every move starts with an explicit pick, keeping consent
  // obvious for an operation that relocates the user's files. Browsers without
  // the API render no button at all; the script format covers them.
  const [moveScan, setMoveScan] = createSignal<MoveScan | null>(null);
  const [moving, setMoving] = createSignal(false);
  const [moveProgress, setMoveProgress] = createSignal<{ done: number; total: number } | null>(null);
  const [moveFailures, setMoveFailures] = createSignal<MoveResult["failed"]>([]);
  let moveAbort: AbortController | null = null;

  // The browser move acts on ONE picked folder, so it only works one session
  // at a time: with several sessions selected the picked folder cannot reach
  // them all, and a partial move would look complete.
  const multiSession = () => props.selectedDates.length > 1;

  // How many distinct names a scan searched for: unique matched names plus the
  // names with zero hits. Denominators the missing warning can cite.
  const scannedNameCount = (scan: MoveScan): number => {
    const matched = new Set<string>();
    for (const m of scan.matches) matched.add(m.name);
    return matched.size + scan.missing.length;
  };

  // Per-name hit counts for the confirm panel's collision notes.
  const matchCounts = createMemo<Map<string, number>>(() => {
    const counts = new Map<string, number>();
    const scan = moveScan();
    if (scan) {
      for (const m of scan.matches) counts.set(m.name, (counts.get(m.name) ?? 0) + 1);
    }
    return counts;
  });

  // Pick a folder, scan it for the selected names, and show the confirm panel.
  // A dismissed picker is a silent no-op.
  const startMovePick = async () => {
    setMoveFailures([]);
    let root;
    try {
      root = await pickDirectory("readwrite", "frame-list-base");
    } catch (e) {
      if (e instanceof CopyCancelledError) return;
      setError(e instanceof Error ? e.message : "Could not open the folder picker.");
      return;
    }
    try {
      setError(null);
      setMoveScan(await scanForNames(root, uniqueNames()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not scan the picked folder.");
    }
  };

  const runMove = async () => {
    const scan = moveScan();
    if (!scan || moving()) return;
    moveAbort = new AbortController();
    setMoving(true);
    setMoveProgress({ done: 0, total: scan.matches.length });
    try {
      const result = await moveMatches(
        scan,
        (done, total) => setMoveProgress({ done, total }),
        moveAbort.signal,
      );
      setMoveFailures(result.failed);
      showToast(
        `${result.moved} file${result.moved === 1 ? "" : "s"} moved to _rejected`,
      );
      setMoveScan(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Move failed.");
    } finally {
      setMoving(false);
      setMoveProgress(null);
      moveAbort = null;
    }
  };

  const stopMove = () => moveAbort?.abort();

  const segmentClass = (active: boolean) =>
    active
      ? "bg-theme-accent/20 text-theme-accent font-medium"
      : "bg-theme-input text-theme-text-tertiary hover:text-theme-text-primary";

  return (
    <Dialog open aria-labelledby="frame-list-modal-title" class="p-4" onClose={props.onClose}>
      <div
        class={`modal-surface border border-theme-border-em rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] w-full max-h-[85vh] flex flex-col ${contentWidthClass(ctx.contentWidth())}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header: fixed. Mirrors WbppExportModal's chrome. */}
        <div class="shrink-0 px-4 py-3 border-b border-theme-border flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-1">
              <h2 id="frame-list-modal-title" class="text-sm font-medium text-theme-text-primary">
                Copy Frame List
              </h2>
              <HelpPopover label="About the frame list" title="Copy frame list">
                <p>
                  Set quality limits above (HFR, eccentricity, and so on), then use Good or
                  Bad to choose which frames go in the list. A frame is bad when it breaks at
                  least one limit. A frame with no recorded quality data counts as
                  unmeasured: it is never bad, and it joins the good list only while the
                  include unmeasured box is checked. The checkbox on each row lets you add or
                  remove one frame by hand; hand edits are cleared whenever a limit changes.
                </p>
                <p>
                  Explorer search is for the Windows search box: paste it there and Explorer
                  finds the listed files. It works best with up to a few dozen files. Names
                  gives one file name per line for use with any other tool. Script produces a
                  small PowerShell or Bash script that looks for each file under the base
                  folder and moves it into a _rejected subfolder, asking for confirmation
                  before touching anything. File names can repeat across targets, so the
                  script shows every match first; pointing the base folder at a single
                  session avoids surprises.
                </p>
                <p>
                  The Move button does the same as the script without leaving the browser:
                  pick the folder, review the matches, and the files move to _rejected.
                </p>
                <p>
                  The quality limits are saved for each rig and are the same ones Export For
                  Stacking uses. Changing a limit here also changes which frames that export
                  leaves out.
                </p>
              </HelpPopover>
            </div>
            <p class="text-tiny text-theme-text-secondary truncate">
              {props.targetName} · {props.selectedDates.length} session
              {props.selectedDates.length !== 1 ? "s" : ""}
            </p>
          </div>
          <IconButton onClick={props.onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </IconButton>
        </div>

        {/* Body: the only scroll container. */}
        <div data-testid="frame-list-modal-body" class="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-3">
          <Show when={error()}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2">
              {error()}
            </div>
          </Show>

          <Show when={moveFailures().length > 0}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2 space-y-1">
              <p>Some files could not be moved:</p>
              <For each={moveFailures()}>
                {(f) => (
                  <p class="font-mono text-tiny truncate">
                    {f.relPath}: {f.message}
                  </p>
                )}
              </For>
            </div>
          </Show>

          {/* Toolbar: which set is copied, and the running tally. */}
          <div class="flex items-center flex-wrap gap-3">
            <div class="inline-flex border border-theme-border rounded-[var(--radius-sm)] overflow-hidden shrink-0">
              <button
                type="button"
                aria-pressed={mode() === "good"}
                title="Copy the frames the chips keep"
                class={`h-6 px-2.5 text-tiny cursor-pointer ${segmentClass(mode() === "good")}`}
                onClick={() => changeMode("good")}
              >
                Good
              </button>
              <button
                type="button"
                aria-pressed={mode() === "bad"}
                title="Copy the frames a chip rejected"
                class={`h-6 px-2.5 text-tiny cursor-pointer border-l border-theme-border ${segmentClass(mode() === "bad")}`}
                onClick={() => changeMode("bad")}
              >
                Bad
              </button>
            </div>

            <Show when={mode() === "good"}>
              <label class="flex items-center gap-2 cursor-pointer shrink-0">
                <input
                  type="checkbox"
                  aria-label="Include unmeasured"
                  class="w-3.5 h-3.5 rounded-[var(--radius-sm)] border-theme-border cursor-pointer"
                  checked={includeUnmeasured()}
                  onChange={(e) => changeIncludeUnmeasured(e.currentTarget.checked)}
                />
                <span class="text-xs text-theme-text-primary">Include unmeasured</span>
              </label>
            </Show>

            {/* Mode-aware tally: the headline is the list being copied (the
                same count the Copy/Move buttons carry), the graded segment is
                the chips' verdict split, with the unmeasured slice flagged
                when the include checkbox pulls it into the good list and any
                hand edits counted at the end. */}
            <span class="ml-auto text-tiny text-theme-text-tertiary whitespace-nowrap">
              {mode() === "bad" ? "Bad list: " : "Good list: "}
              <span class="tabular-nums font-semibold text-theme-text-primary">
                {selected().length}
              </span>{" "}
              of <span class="tabular-nums">{totals().total}</span> frames
              <span class="text-theme-text-secondary">
                {" "}· graded <span class="tabular-nums">{totals().copy}</span> good /{" "}
                <span class="tabular-nums">{totals().fail}</span> bad /{" "}
                <span class="tabular-nums">{totals().unmeasured}</span> unmeasured
                <Show when={mode() === "good" && includeUnmeasured() && totals().unmeasured > 0}>
                  , included
                </Show>
                <Show when={Object.keys(overrides()).length > 0}>
                  {" "}({Object.keys(overrides()).length} overridden)
                </Show>
              </span>
            </span>
          </div>

          <Show when={failedDates().length > 0}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2">
              Could not load {failedDates().length} of {props.selectedDates.length} sessions:{" "}
              {failedDates().join(", ")}. The list below covers only the loaded sessions.
            </div>
          </Show>

          <WbppQualityPanel
            enabled={qualityFilterOn()}
            onEnabledChange={changeQualityEnabled}
            config={qualityConfig()}
            onConfigChange={changeQualityConfig}
            verdicts={verdicts()}
            loading={loading()}
            sessionDetails={sessionDetails()}
            isIncluded={rowIncluded}
            onToggleInclude={toggleInclude}
            showFullPath
          />
        </div>

        {/* Footer: format, base folder for the script, and the copy action.
            While a browser-move scan is confirmed or running, the confirm
            panel replaces the whole row. */}
        <div class="shrink-0 px-4 py-3 border-t border-theme-border">
          <Show
            when={moveScan()}
            fallback={
              <div class="flex items-center flex-wrap gap-2">
                <select
                  aria-label="Format"
                  class={`${FIELD_CLASS} cursor-pointer shrink-0`}
                  value={format()}
                  onChange={(e) => setFormat(e.currentTarget.value as FrameListFormat)}
                >
                  <option value="explorer">Windows Explorer search (paste into search box)</option>
                  <option value="names">File name list (one per line)</option>
                  <option value="script">
                    {scriptOs() === "windows" ? "PowerShell" : "Bash"} script (move to _rejected)
                  </option>
                </select>
                <div
                  class="flex-1 min-w-48"
                  title={
                    format() !== "script"
                      ? "Base folder is used only by the move script format"
                      : undefined
                  }
                >
                  <input
                    type="text"
                    aria-label="Base folder"
                    class={`${FIELD_CLASS} font-mono w-full disabled:opacity-50`}
                    placeholder="D:\Staging\M31 or /mnt/staging"
                    disabled={format() !== "script"}
                    value={baseFolder()}
                    onInput={(e) => setBaseFolder(e.currentTarget.value)}
                  />
                </div>
                <div class="ml-auto shrink-0 flex items-center gap-2">
                  <Show when={isFsAccessSupported()}>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={nameCount() === 0 || multiSession()}
                      title={
                        multiSession()
                          ? "Browser move works one session at a time: the browser can only reach files inside the single folder you pick."
                          : undefined
                      }
                      onClick={() => void startMovePick()}
                    >
                      Move {nameCount()} to _rejected
                    </Button>
                  </Show>
                  <Button variant="primary" size="sm" disabled={copyDisabled()} onClick={() => void doCopy()}>
                    {copyLabel()}
                  </Button>
                </div>
              </div>
            }
          >
            {(scan) => (
              <div class="space-y-2">
                <p class="text-xs text-theme-text-primary">
                  <span class="tabular-nums font-semibold">{scan().matches.length}</span> files
                  matched, <span class="tabular-nums">{scan().missing.length}</span> missing.{" "}
                  <span class="text-theme-text-secondary">
                    Files move to _rejected inside the picked folder.
                  </span>
                </p>
                <Show when={scan().missing.length > 0}>
                  <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2">
                    {scan().missing.length} of {scannedNameCount(scan())} files were not found
                    under {scan().root.name}. Check that you picked the folder that contains this
                    session's frames.
                  </div>
                </Show>
                <div class="max-h-40 overflow-y-auto border border-theme-border rounded-[var(--radius-sm)] text-tiny font-mono">
                  <For each={scan().matches}>
                    {(m) => (
                      <div class="px-2 py-0.5 truncate text-theme-text-primary">
                        {m.relPath}
                        <Show when={(matchCounts().get(m.name) ?? 0) > 1}>
                          <span class="text-theme-warning font-sans">
                            {" "}matches {matchCounts().get(m.name)} files
                          </span>
                        </Show>
                      </div>
                    )}
                  </For>
                  <For each={scan().missing}>
                    {(n) => (
                      <div class="px-2 py-0.5 truncate text-theme-text-tertiary">missing: {n}</div>
                    )}
                  </For>
                </div>
                <Show
                  when={moving()}
                  fallback={
                    <div class="flex items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        disabled={scan().matches.length === 0}
                        onClick={() => void runMove()}
                      >
                        Move {scan().matches.length}
                      </Button>
                      <Button variant="secondary" size="sm" onClick={() => setMoveScan(null)}>
                        Back
                      </Button>
                    </div>
                  }
                >
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-theme-text-secondary tabular-nums">
                      Moving {moveProgress()?.done ?? 0} of {moveProgress()?.total ?? 0}
                    </span>
                    <Button variant="secondary" size="sm" onClick={stopMove}>
                      Stop
                    </Button>
                  </div>
                </Show>
              </div>
            )}
          </Show>
        </div>
      </div>
    </Dialog>
  );
};

export default FrameListModal;
