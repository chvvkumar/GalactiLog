import {
  Component,
  For,
  Show,
  createSignal,
  createMemo,
  createEffect,
  onMount,
  untrack,
} from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { showToast } from "./Toast";
import { getErrorMessage } from "../utils/errors";
import { useSettingsContext } from "./SettingsProvider";
import Dialog from "./Dialog";
import Button from "./ui/Button";
import HelpPopover from "./HelpPopover";
import IconButton from "./ui/IconButton";
import WbppLevelEditor from "./wbpp/WbppLevelEditor";
import WbppQualityPanel from "./wbpp/WbppQualityPanel";
import WbppScriptMenu, { type ScriptOs } from "./wbpp/WbppScriptMenu";
import WbppFooter, { type CopyBlocker } from "./wbpp/WbppFooter";
import { detectOs, lastSegment, parentContext } from "./wbpp/paths";
import {
  isFsAccessSupported,
  CopyCancelledError,
  pickDirectory,
  queryHandlePermission,
  loadStoredHandle,
  storeHandle,
  HANDLE_KEYS,
  type PermState,
} from "../lib/wbppBrowserCopy";
import {
  startWbppCopy,
  stopWbppCopy,
  wbppCopyRunning,
  wbppCopyDone,
  wbppCopyTotal,
  wbppCopySpeed,
  wbppCopyError,
  wbppCopyFinished,
  clearWbppCopyError,
} from "../store/wbppCopyJob";
import {
  computeVerdicts,
  excludedSourceRelatives,
  excludedUnderSelectedLevels,
  type FrameVerdict,
  type QualityConfig,
} from "../lib/wbppQualityFilter";
import { loadWbppQualityState, saveWbppQualityState } from "../lib/wbppQualityStore";
import { contentWidthClass } from "../utils/format";
import type {
  WbppSessionPreview,
  WbppFolderLevel,
  WbppGenerateResponse,
  WbppCopyOperation,
  SessionDetail,
} from "../api/types";

interface Props {
  targetId: string;
  targetName: string;
  selectedDates: string[];
  sessionCache: Record<string, SessionDetail>;
  onClose: () => void;
}

type OsChoice = "auto" | ScriptOs;
type PermOrNone = PermState | "none";

const DEFAULT_EXCLUSIONS = [
  "WBPP", "PixInsight", "finals", "WORK_AREA",
  "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
];

// Raised body zone, matching the target detail page's section cards.
const CARD_CLASS =
  "bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4";

const FIELD_CLASS =
  "w-full text-xs px-2 py-1.5 bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:outline-none focus:border-theme-accent";

const ZONE_TITLE_CLASS =
  "text-xs font-semibold uppercase tracking-wider text-theme-text-secondary";

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
    case "granted": return "text-theme-success";
    case "denied": return "text-theme-error";
    case "prompt": return "text-theme-warning";
    default: return "text-theme-text-tertiary";
  }
}

/**
 * Export For Stacking (WBPP or SIRIL).
 *
 * Layout is header / body / footer, with the BODY as the only scroll container:
 * the primary action lives in the sticky footer beside a statement of what it is
 * about to do, so it can never scroll out of reach. `modal-surface` is repeated
 * on the sticky footer (WbppFooter) so body content does not bleed through it --
 * the same technique as ReleaseNotesModal's sticky header.
 *
 * The zones are ordered by the decision the user is making: where the files go,
 * the library root they come from, which folders go there, then the options that
 * modify that. App configuration (library root, staging, exclusions) lives in
 * the Library section, folded behind a "Change".
 */
const WbppExportModal: Component<Props> = (props) => {
  const ctx = useSettingsContext();
  const general = () => ctx.settings()?.general;

  const [libraryRoot, setLibraryRoot] = createSignal(general()?.wbpp_library_root ?? "");
  // Read-only here: the pinned script-type preference is edited in
  // Settings > External Tools > PixInsight Export. The modal only resolves it
  // into the script menu's default and round-trips it through saveAsDefaults.
  const [osChoice] = createSignal<OsChoice>((general()?.wbpp_default_os as OsChoice) ?? "auto");
  const [stagingPath, setStagingPath] = createSignal(general()?.wbpp_staging_path ?? "");
  const [exclusionsText, setExclusionsText] = createSignal(
    (general()?.wbpp_exclusions ?? DEFAULT_EXCLUSIONS).join("\n"),
  );

  const [sessions, setSessions] = createSignal<WbppSessionPreview[]>([]);
  const [chosenLevels, setChosenLevels] = createSignal<Record<string, number>>({});
  const [previewing, setPreviewing] = createSignal(false);

  const [generating, setGenerating] = createSignal(false);
  const [generated, setGenerated] = createSignal<WbppGenerateResponse | null>(null);
  const [copied, setCopied] = createSignal(false);
  const [showScript, setShowScript] = createSignal(false);

  // Which session rows are expanded to show their level editor. The parent owns
  // this so an editor can be reopened without the row remounting its own state.
  const [expandedDates, setExpandedDates] = createSignal<string[]>([]);
  // The app-config fields inside Options. Open by default only when there is no
  // library root yet, because then it is the one thing blocking the export.
  const [settingsOpen, setSettingsOpen] = createSignal(!(general()?.wbpp_library_root ?? "").trim());
  const [savedDefaults, setSavedDefaults] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);

  // Browser-native copy (File System Access API) state.
  const canBrowserCopy = isFsAccessSupported();
  const [srcHandle, setSrcHandle] = createSignal<any>(null);
  const [destHandle, setDestHandle] = createSignal<any>(null);
  const [srcPerm, setSrcPerm] = createSignal<PermOrNone>("none");
  const [destPerm, setDestPerm] = createSignal<PermOrNone>("none");
  let scriptRef: HTMLDivElement | undefined;

  // --- Quality filter state, persisted per rig ---
  // Session details keyed by date, seeded from props.sessionCache then filled in
  // for any selected date not already cached.
  const [qualitySessions, setQualitySessions] = createSignal<Record<string, SessionDetail>>({});
  const [qualityLoading, setQualityLoading] = createSignal(false);

  /**
   * The rig the selected sessions were shot on: the first non-null
   * `FrameRecord.rig` across the selected dates, reading the page's cache first
   * and any details this modal fetched itself second. Null until a frame with a
   * rig is available (or when none of the frames carry one), in which case the
   * store's rig-less fallback slot is used.
   */
  const rigId = createMemo<string | null>(() => {
    const fetched = qualitySessions();
    for (const date of props.selectedDates) {
      const detail = props.sessionCache[date] ?? fetched[date];
      for (const f of detail?.frames ?? []) {
        if (f.rig != null) return f.rig;
      }
    }
    return null;
  });

  // Hydrate the toggle and config from the per-rig store. The initial load uses
  // whatever rig resolves synchronously (the page cache usually answers at
  // once); the effect below re-hydrates if the rig resolves or changes later,
  // e.g. once an uncached session's frames arrive.
  let loadedForRig = rigId();
  const initialQualityState = loadWbppQualityState(loadedForRig);
  const [qualityFilterOn, setQualityFilterOn] = createSignal(initialQualityState.enabled);
  const [qualityConfig, setQualityConfig] = createSignal<QualityConfig>(initialQualityState.config);

  // Set by the panel's change handlers only, never by hydration. It decides who
  // wins a rig transition: the user's in-session edits, or the resolved rig's
  // stored state.
  let userEdited = false;
  const changeQualityEnabled = (on: boolean) => {
    userEdited = true;
    setQualityFilterOn(on);
  };
  const changeQualityConfig = (cfg: QualityConfig) => {
    userEdited = true;
    setQualityConfig(cfg);
  };

  /**
   * Rig transitions. With uncached sessions the rig starts null and resolves
   * only once a fetched session's frames arrive -- possibly after the user has
   * already tuned the filter. Rehydrating at that point would overwrite their
   * edits with the resolved rig's (likely empty) stored state, so edits win:
   * the in-memory state is written under the resolved rig's key instead. Only
   * an untouched modal hydrates from storage on a transition.
   */
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
    setQualityFilterOn(st.enabled);
    setQualityConfig(st.config);
  });

  /**
   * Write every change straight back to the per-rig store. The write is a cheap
   * synchronous local one, so there is no debounce and no flush-on-close to get
   * wrong. The mount run and the post-hydration runs write back exactly what was
   * just loaded, which is an idempotent no-op and simpler than suppression flags.
   */
  createEffect(() => {
    const state = { enabled: qualityFilterOn(), config: qualityConfig() };
    saveWbppQualityState(untrack(rigId), state);
  });

  /**
   * When the filter is switched on, seed from the page's cache and fetch the rest.
   * (Mirrors TargetDetailPage.tsx loadSessionDetail's GET.)
   *
   * This effect WRITES `qualitySessions`, so it must not TRACK it, or it becomes
   * its own trigger: write -> rerun -> write, fetching again on every pass. Hence
   * the untracked read below. The bug this replaced was invisible for a subtle
   * reason worth keeping in mind if this is edited again: the read used to be
   * `props.sessionCache[date] ?? qualitySessions()[date]`, and `??` short-circuits.
   * When every selected date was already in the page's cache, `qualitySessions()`
   * was never called, never tracked, and nothing looped. Only an uncached date --
   * exactly the case that needs the fetch -- reached the read, subscribed the
   * effect to its own output, and spun. Both the loop and the empty frame table
   * followed from that: each rerun reset state to `seeded`, which was built before
   * the in-flight fetch could resolve, so the arriving frames were overwritten by
   * the next pass and never landed.
   *
   * Dependencies are therefore the inputs only: the filter toggle, the selected
   * dates, the page's cache, and the target.
   */
  createEffect(() => {
    if (!qualityFilterOn()) return;
    const have = untrack(qualitySessions);
    const seeded: Record<string, SessionDetail> = {};
    const missing: string[] = [];
    for (const date of props.selectedDates) {
      const cached = props.sessionCache[date] ?? have[date];
      if (cached) seeded[date] = cached;
      else missing.push(date);
    }
    setQualitySessions(seeded);
    if (missing.length === 0) return;
    setQualityLoading(true);
    Promise.all(
      missing.map((date) =>
        (apiClient
          .GET("/api/targets/{target_id}/sessions/{date}", {
            params: { path: { target_id: props.targetId, date } },
          })
          .then(unwrap) as Promise<SessionDetail>)
          .then((detail) => [date, detail] as const)
          .catch(() => null),
      ),
    )
      .then((results) => {
        setQualitySessions((prev) => {
          const next = { ...prev };
          for (const r of results) if (r) next[r[0]] = r[1];
          return next;
        });
      })
      .finally(() => setQualityLoading(false));
  });

  // Verdicts, exclude set, and totals recompute reactively from the filter inputs.
  const verdicts = createMemo<FrameVerdict[]>(() =>
    qualityFilterOn()
      ? computeVerdicts(qualitySessions(), props.selectedDates, qualityConfig())
      : [],
  );
  const excludedSet = createMemo<string[]>(() => excludedSourceRelatives(verdicts()));

  // Preview needs nothing the async handle-loading above provides: it reads only
  // the library root (seeded synchronously from settings) and the props. Skips
  // silently when the root is unset -- the Options section already surfaces that.
  onMount(() => {
    if (previewing() || !libraryRoot().trim()) return;
    void loadPreview();
  });

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

  // The pinned preference wins over detection; the script menu only reports which
  // of the two produced the default, it does not resolve it.
  const effectiveOs = (): ScriptOs =>
    osChoice() === "auto" ? detectOs(libraryRoot()) : (osChoice() as ScriptOs);
  const defaultReason = (): "detected" | "preference" =>
    osChoice() === "auto" ? "detected" : "preference";
  const osLabel = (os: ScriptOs) => (os === "windows" ? "Windows" : "Linux / macOS");

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

  // The one place a session's selected level is resolved. Everything downstream
  // (the copy plan, the frame count, the byte total) reads this.
  const selections = createMemo<{ date: string; level: WbppFolderLevel }[]>(() => {
    const out: { date: string; level: WbppFolderLevel }[] = [];
    for (const s of sessions()) {
      if (!s.levels.length) continue;
      const idx = Math.max(
        0,
        Math.min(chosenLevels()[s.session_date] ?? s.default_level_index, s.levels.length - 1),
      );
      out.push({ date: s.session_date, level: s.levels[idx] });
    }
    return out;
  });

  const chosenIndexFor = (s: WbppSessionPreview): number =>
    Math.max(0, Math.min(chosenLevels()[s.session_date] ?? s.default_level_index, s.levels.length - 1));

  // The copy plan is derived purely from the previewed sessions + chosen levels,
  // so it is available without generating the script.
  const plan = createMemo<WbppCopyOperation[]>(() => {
    const chosen = selections();
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

  /**
   * The destination folder name for a session, but only when it differs from the
   * source folder's own name -- i.e. only when plan() disambiguated a collision
   * between two sessions that chose the same basename.
   *
   * Null the rest of the time, so the rename surfaces on the rows it actually
   * happens to rather than echoing a destination path onto every row.
   */
  const renamedEntryFor = (date: string): string | null => {
    const op = plan().find((o) => o.session_date === date);
    if (!op) return null;
    return op.dest_entry === lastSegment(op.source) ? null : op.dest_entry;
  };

  /**
   * The excluded frames that are actually inside the selected levels.
   *
   * `qTotals()` counts every failing light across the selected DATES, but
   * `level.frame_count` / `level.frame_bytes` describe one FOLDER subtree, which
   * may be narrower than the session. Subtracting the former from the latter mixes
   * two domains: a session split across .../Ha and .../OIII, with only Ha selected,
   * would have OIII's failures deducted from Ha's count and bytes -- understating
   * the size and, with enough failures, driving the count below zero.
   *
   * Scoping by source_relative membership puts both sides in the same domain, and
   * is how the backend and wbppBrowserCopy each decide what a level contains. The
   * result cannot go negative: a session's excluded frames under its level are a
   * subset of the lights that level's frame_count counted (both come from the same
   * LIGHT rows for that target and date).
   */
  const excludedInSelection = createMemo<FrameVerdict[]>(() =>
    qualityFilterOn()
      ? excludedUnderSelectedLevels(
          verdicts(),
          new Map(selections().map((s) => [s.date, s.level.relative_path])),
        )
      : [],
  );

  // Frames the copy will actually write: the selected levels' frames, less the
  // lights the quality filter drops from inside those levels.
  const frameCount = () =>
    selections().reduce((a, c) => a + c.level.frame_count, 0) - excludedInSelection().length;

  /**
   * The filter has emptied the export: the selected folders hold frames, and the
   * filter excludes every one of them.
   *
   * The panel warns about the SESSION-wide wipeout; this is the narrower and more
   * consequential one -- what the copy would actually write. They can disagree:
   * a filter that keeps frames elsewhere in the session can still take every
   * frame under the selected level. The guard requires the levels to hold frames
   * at all, so an empty folder is not blamed on the filter.
   *
   * Stated up here at the top of the body because the filter's own controls are
   * further down inside Options, and the one thing a user must not do is find
   * this out by opening an empty staging folder.
   */
  const filterEmptiedExport = () =>
    qualityFilterOn() &&
    selections().reduce((a, c) => a + c.level.frame_count, 0) > 0 &&
    frameCount() === 0;

  /**
   * Bytes the copy will actually write, or null when that is genuinely unknown.
   *
   * `frame_bytes` is null (not a partial sum) whenever any contributing frame has
   * an unrecorded size -- the backend makes that choice deliberately so the UI
   * never presents an undercount as fact. The same rule governs the filter's
   * subtraction: an excluded frame with a null `file_size` makes the remainder
   * unknowable. So: never coalesce, never sum around a null. One null anywhere
   * and the whole total is null, which WbppFooter renders as "—".
   *
   * Only frames inside the selected levels are subtracted -- see
   * `excludedInSelection`. A frame outside them contributed nothing to
   * `frame_bytes`, so deducting its size would understate the total.
   */
  const sizeBytes = createMemo<number | null>(() => {
    let total = 0;
    for (const c of selections()) {
      const b = c.level.frame_bytes;
      if (b == null) return null;
      total += b;
    }
    for (const v of excludedInSelection()) {
      const fs = v.frame.file_size;
      if (fs == null) return null;
      total -= fs;
    }
    return total;
  });

  // Frames across the selection, for the header subline. Before a preview there
  // are no level counts, so fall back to whatever the page already cached.
  const headerFrameCount = () =>
    sessions().length
      ? sessions().reduce((a, s) => a + s.total_frame_count, 0)
      : props.selectedDates.reduce((a, d) => a + (props.sessionCache[d]?.frames.length ?? 0), 0);

  /**
   * Where the in-browser copy writes. The File System Access API exposes no path
   * for a handle, only its name. Null when the API is unavailable (there is no
   * browser copy to describe) or no destination has been picked yet.
   *
   * Deliberately NOT falling back to stagingRoot(): that is where a *script*
   * writes, which is a different place reached by a different route. Presenting
   * one under the other's label is what made the footer's "→" ambiguous.
   */
  const copyDestination = (): string | null => {
    if (!canBrowserCopy) return null;
    const h = destHandle();
    return h ? h.name : null;
  };

  // Where a generated script writes. Always knowable (it is derived from the
  // library root and the staging override), so it is always shown -- on Chromium
  // too, where it used to be invisible behind the handle name.
  const scriptDestination = (): string | null => stagingRoot().trim() || null;

  const permissionGranted = () => srcPerm() === "granted" && destPerm() === "granted";

  /**
   * What stops a copy, or null when one can proceed.
   *
   * Null exactly when the pre-rewrite gate was open (`srcHandle && destHandle &&
   * srcPerm !== "denied" && destPerm !== "denied"`), so the primary is disabled in
   * precisely the states it was before -- this reports the reason, it does not
   * change the verdict. Without the gate the primary is enabled for users with no
   * source folder, or a denied permission, and the click can only fail into the
   * error banner.
   *
   * Ordered the way the user must resolve them: the destination is the first thing
   * zone 1 asks for, so a run with nothing chosen at all reports "destination"
   * rather than naming a later step.
   */
  const copyBlockedBy = (): CopyBlocker | null => {
    if (!destHandle()) return "destination";
    if (!srcHandle()) return "source";
    if (srcPerm() === "denied" || destPerm() === "denied") return "permission";
    return null;
  };

  const runCommand = (): string => {
    const g = generated();
    if (!g) return "";
    if (g.target_os !== "windows") {
      return `chmod +x ${g.filename} && ./${g.filename}`;
    }
    // Browser-downloaded scripts carry the Mark of the Web and are blocked even with
    // -ExecutionPolicy Bypass when policy is set by Group Policy. Unblock-File first,
    // then run. Double apostrophes for the single-quoted PowerShell literal.
    const name = `.\\${g.filename}`.replace(/'/g, "''");
    return `powershell -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '${name}'; & '${name}'"`;
  };

  const loadPreview = async () => {
    if (!libraryRoot().trim()) {
      setError("Enter your astrophotography library root path first.");
      return;
    }
    setError(null);
    setPreviewing(true);
    try {
      const resp = await apiClient
        .POST("/api/wbpp/preview", {
          body: {
            target_id: props.targetId,
            session_dates: props.selectedDates,
            chosen_levels: chosenLevels(),
            library_root: libraryRoot().trim(),
            target_os: targetOsParam(),
          },
        })
        .then(unwrap);
      setSessions(resp.sessions);
      setGenerated(null);
      const init: Record<string, number> = {};
      for (const s of resp.sessions) {
        init[s.session_date] = chosenLevels()[s.session_date] ?? s.default_level_index;
      }
      setChosenLevels(init);
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to load preview"));
    } finally {
      setPreviewing(false);
    }
  };

  const selectLevel = (sessionDate: string, index: number) => {
    setChosenLevels({ ...chosenLevels(), [sessionDate]: index });
    // The previously generated script is now stale (the plan updates reactively).
    setGenerated(null);
  };

  const toggleExpanded = (date: string) =>
    setExpandedDates((prev) => (prev.includes(date) ? prev.filter((d) => d !== date) : [...prev, date]));

  /**
   * The OS is an argument, not a signal read: the script menu decides which
   * flavour this click produces, so passing it through is what makes the menu
   * mean anything. Detection still happens in exactly one place (effectiveOs);
   * this only carries the answer.
   */
  const generate = async (os: ScriptOs) => {
    if (!libraryRoot().trim()) {
      setError("Enter your astrophotography library root path first.");
      return;
    }
    setError(null);
    setGenerating(true);
    setShowScript(false);
    try {
      const resp = await apiClient
        .POST("/api/wbpp/generate", {
          body: {
            target_id: props.targetId,
            target_name: props.targetName,
            session_dates: props.selectedDates,
            chosen_levels: chosenLevels(),
            library_root: libraryRoot().trim(),
            target_os: os,
            staging_path: stagingPath().trim() || null,
            exclusions: parsedExclusions(),
            excluded_source_relatives: excludedSet(),
          },
        })
        .then(unwrap);
      setGenerated(resp);
      setShowScript(true);
      // The trigger lives in the footer while the output lands in the body, so
      // bring it into view rather than leaving the click with no visible effect.
      queueMicrotask(() => scriptRef?.scrollIntoView?.({ block: "nearest" }));
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to generate script"));
    } finally {
      setGenerating(false);
    }
  };

  const saveAsDefaults = async () => {
    const current = general();
    if (!current) return;
    try {
      // The quality filter is NOT part of these defaults: it persists itself
      // per rig via the wbppQualityStore, not through GeneralSettings.
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
    } catch (e: unknown) {
      if (!(e instanceof CopyCancelledError)) setError(getErrorMessage(e, "Could not open the folder picker."));
    }
  };

  const chooseDest = async () => {
    setError(null);
    try {
      const h = await pickDirectory("readwrite", "wbpp-staging");
      setDestHandle(h);
      await storeHandle(HANDLE_KEYS.dest, h);
      setDestPerm(await queryHandlePermission(h, "readwrite"));
    } catch (e: unknown) {
      if (!(e instanceof CopyCancelledError)) setError(getErrorMessage(e, "Could not open the folder picker."));
    }
  };

  /**
   * Grant-then-copy in one click: runBrowserCopy (inside the store) requests
   * both permissions itself as its first act, still inside this click's user
   * gesture, then copies. The copy runs in the module-level wbppCopyJob store,
   * so closing this modal no longer loses it; the nav-bar job monitor shows
   * progress and Stop, and reopening the modal reattaches to the live state.
   */
  const startBrowserCopy = () => {
    if (wbppCopyRunning()) {
      setError("A WBPP copy is already running. Stop it from the Activity monitor first.");
      return;
    }
    if (!srcHandle() || !destHandle()) {
      setError("Choose a library folder and a destination folder first.");
      return;
    }
    if (!plan().length) {
      setError("Nothing to copy - preview the folder levels first.");
      return;
    }
    setError(null);
    clearWbppCopyError();
    void startWbppCopy({
      rootHandle: srcHandle(),
      destHandle: destHandle(),
      operations: plan(),
      exclusions: parsedExclusions(),
      excludedSourceRelatives: excludedSet(),
      targetName: props.targetName,
      // Take the permission state from what the request actually returned, on
      // the failing path as much as the succeeding one (see the store; these
      // setters are safe to call even after this modal unmounts).
      onPermission: (which, state) =>
        which === "source" ? setSrcPerm(state) : setDestPerm(state),
    });
  };

  const stopCopy = () => stopWbppCopy();

  return (
    <Dialog open aria-labelledby="wbpp-modal-title" class="p-4" onClose={props.onClose}>
      <div
        class={`modal-surface border border-theme-border-em rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] w-full max-h-[85vh] flex flex-col ${contentWidthClass(ctx.contentWidth())}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header: fixed. The target name is subject matter, not the action, so
            it sits in the subline and the title states only what this does. */}
        <div class="shrink-0 px-4 py-3 border-b border-theme-border flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-1">
              <h2 id="wbpp-modal-title" class="text-sm font-medium text-theme-text-primary">
                Export For Stacking
              </h2>
              <HelpPopover label="About exporting for stacking" title="Export for stacking">
                <p>Prepares selected frames for stacking in WBPP or SIRIL.</p>
                <p>1. Pick your library root (the local folder mirroring the server's FITS data root).</p>
                <p>2. Review the session folders to copy.</p>
                <p>3. Optionally filter frames by quality.</p>
                <p>4. Copy files in-browser or generate a script.</p>
              </HelpPopover>
            </div>
            <p class="text-tiny text-theme-text-secondary truncate">
              {props.targetName} · {props.selectedDates.length} session
              {props.selectedDates.length !== 1 ? "s" : ""} · {headerFrameCount()} frames
            </p>
          </div>
          <IconButton onClick={props.onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </IconButton>
        </div>

        {/* Body: the ONLY scroll container. */}
        <div data-testid="wbpp-modal-body" class="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4">
          <Show when={error() ?? wbppCopyError()}>
            <div class="text-xs text-theme-error bg-theme-error/10 border border-theme-error/30 rounded-[var(--radius-sm)] px-3 py-2">
              {error() ?? wbppCopyError()}
            </div>
          </Show>

          {/* Never ship zero frames silently. The filter's controls live further
              down inside Options, so the fact that they have emptied the export
              has to be stated where the user is already looking. */}
          <Show when={filterEmptiedExport()}>
            <div
              data-testid="wbpp-empty-export"
              class="text-xs text-theme-warning bg-theme-warning/10 border border-theme-warning/30 rounded-[var(--radius-sm)] px-3 py-2"
            >
              The quality filter excludes every frame in the selected folders, so this export
              would copy nothing. Loosen it under Options below, or switch it off to copy
              everything.
            </div>
          </Show>

          {/* Zone 1: Destination. Two routes write to two different places, so each
              is stated under its own label rather than one standing in for the other. */}
          <div class={CARD_CLASS}>
            <Show when={canBrowserCopy}>
              <div class="flex items-center gap-3">
                <span class={`${ZONE_TITLE_CLASS} shrink-0 w-20`}>Copy to</span>
                <span
                  class={`font-mono text-xs truncate flex-1 min-w-0 ${
                    copyDestination() ? "text-theme-text-primary" : "text-theme-text-tertiary"
                  }`}
                  title={copyDestination() ?? undefined}
                >
                  {copyDestination() ?? "Not set"}
                </span>
                <span class={`text-tiny shrink-0 ${permClass(destPerm())}`}>{permText(destPerm())}</span>
                <Button variant="secondary" size="sm" onClick={chooseDest}>
                  {destHandle() ? "Change..." : "Choose..."}
                </Button>
              </div>

              <div class="flex items-center gap-3 mt-2">
                <span class={`${ZONE_TITLE_CLASS} shrink-0 w-20`}>Copy from</span>
                <span
                  class={`font-mono text-xs truncate flex-1 min-w-0 ${
                    srcHandle() ? "text-theme-text-primary" : "text-theme-text-tertiary"
                  }`}
                >
                  {srcHandle() ? srcHandle().name : "Not set"}
                </span>
                <span class={`text-tiny shrink-0 ${permClass(srcPerm())}`}>{permText(srcPerm())}</span>
                <Button variant="secondary" size="sm" onClick={chooseSource}>
                  {srcHandle() ? "Change..." : "Choose..."}
                </Button>
              </div>
            </Show>

            {/* The script's destination, shown on every browser. It used to be
                displaced by the handle name on Chromium, leaving script users
                unable to see where their script would write. */}
            <div class={`flex items-center gap-3 ${canBrowserCopy ? "mt-2" : ""}`}>
              <span class={`${ZONE_TITLE_CLASS} shrink-0 w-20`}>Script to</span>
              <span
                class={`font-mono text-xs truncate flex-1 min-w-0 ${
                  scriptDestination() ? "text-theme-text-primary" : "text-theme-text-tertiary"
                }`}
                title={scriptDestination() ?? undefined}
              >
                {scriptDestination() ?? "Not set"}
              </span>
            </div>

            <Show
              when={canBrowserCopy}
              fallback={
                <p class="text-tiny text-theme-text-tertiary mt-2">
                  In-browser copy needs a Chromium browser (Chrome/Edge) over HTTPS or localhost.
                  Generate a script instead; it copies into the "Script to" path above.
                </p>
              }
            >
              <p class="text-tiny text-theme-text-tertiary mt-2">
                Two ways to move the files, each with its own destination: the in-browser copy
                writes into "Copy to", while a generated script writes into "Script to". Pick your
                library root (the folder that mirrors the server's FITS data root) as "Copy from";
                folders are remembered for next time.
              </p>
            </Show>

            <Show when={wbppCopyRunning() || wbppCopyFinished() !== null}>
              <div class="space-y-1 mt-3">
                <div class="h-1.5 bg-theme-elevated rounded-[var(--radius-sm)] overflow-hidden">
                  <div
                    class="h-full bg-theme-accent transition-all"
                    style={{
                      width: `${wbppCopyTotal() > 0 ? Math.round((wbppCopyDone() / wbppCopyTotal()) * 100) : (wbppCopyFinished() !== null ? 100 : 0)}%`,
                    }}
                  />
                </div>
                <Show when={wbppCopyFinished() !== null}>
                  <p class="text-tiny text-theme-text-tertiary">
                    Done. Copied {wbppCopyFinished()} file{wbppCopyFinished() !== 1 ? "s" : ""}. Open WBPP and use Add Directory on the destination.
                  </p>
                </Show>
              </div>
            </Show>
          </div>

          {/* Zone 2: Library. The root the folders are scanned under, with the
              app-config fields (staging, exclusions) folded behind "Change". */}
          <div class={CARD_CLASS}>
            <h3 class={ZONE_TITLE_CLASS}>
              <span class="text-theme-text-tertiary">Step 1 · </span>Library
            </h3>
            <div class="flex items-center gap-2 text-tiny text-theme-text-tertiary mt-2">
              <span class="truncate min-w-0">
                Library: <span class="font-mono">{libraryRoot().trim() || "not set"}</span> (
                {osLabel(effectiveOs())})
              </span>
              <button
                type="button"
                class="text-tiny text-theme-accent hover:text-theme-accent-hover transition-colors cursor-pointer shrink-0"
                onClick={() => setSettingsOpen(!settingsOpen())}
              >
                {settingsOpen() ? "Done" : "Change"}
              </button>
            </div>

            <Show when={settingsOpen()}>
              <div class="mt-3 space-y-3">
                <p class="text-tiny text-theme-text-tertiary">
                  These default to your Settings &gt; External Tools &gt; PixInsight Export values.
                  Changes here apply to this export only unless you save them as defaults.
                </p>

                <div>
                  <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
                    Library root (on your machine)
                  </label>
                  <input
                    type="text"
                    class={FIELD_CLASS}
                    placeholder="e.g. Z:\Astro or /mnt/astro"
                    value={libraryRoot()}
                    onInput={(e) => setLibraryRoot(e.currentTarget.value)}
                  />
                </div>

                <div>
                  <label class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide block mb-1">
                    Staging path (optional)
                  </label>
                  <input
                    type="text"
                    class={FIELD_CLASS}
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
                    class={`${FIELD_CLASS} font-mono`}
                    rows={4}
                    value={exclusionsText()}
                    onInput={(e) => setExclusionsText(e.currentTarget.value)}
                  />
                </div>

                <button
                  type="button"
                  class="text-tiny text-theme-accent hover:text-theme-accent-hover transition-colors cursor-pointer disabled:opacity-50"
                  onClick={saveAsDefaults}
                  disabled={!libraryRoot().trim()}
                >
                  {savedDefaults() ? "Saved!" : "Save as defaults"}
                </button>
              </div>
            </Show>
          </div>

          {/* Zone 3: Folders to copy */}
          <div class={CARD_CLASS}>
            <div class="flex items-center gap-2">
              <h3 class={ZONE_TITLE_CLASS}>
                <span class="text-theme-text-tertiary">Step 2 · </span>Folders to copy
              </h3>
              <Show when={sessions().length > 0}>
                {/* Rescanning a large library takes a while. A dimmed icon alone
                    reads as "broken", so the icon spins beside a word -- the
                    in-progress state the old "Loading..." text button carried. */}
                <div class="ml-auto flex items-center gap-1.5">
                  <Show when={previewing()}>
                    <span class="text-tiny text-theme-text-tertiary">Rescanning...</span>
                  </Show>
                  <IconButton
                    class="disabled:opacity-50"
                    onClick={loadPreview}
                    disabled={previewing() || !libraryRoot().trim()}
                    aria-label={previewing() ? "Rescanning folders" : "Rescan folders"}
                    title={previewing() ? "Rescanning..." : "Rescan folders"}
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      aria-hidden="true"
                      class={previewing() ? "animate-spin" : undefined}
                    >
                      <path d="M21 12a9 9 0 1 1-2.64-6.36" /><polyline points="21 3 21 9 15 9" />
                    </svg>
                  </IconButton>
                </div>
              </Show>
            </div>

            <Show
              when={sessions().length > 0}
              fallback={
                <div class="mt-3">
                  <Show
                    when={previewing()}
                    fallback={
                      <>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={loadPreview}
                          disabled={!libraryRoot().trim()}
                        >
                          Preview folder levels
                        </Button>
                        <p class="text-tiny text-theme-text-tertiary mt-2">
                          Preview the folder levels to choose which folder to copy for each session.
                        </p>
                      </>
                    }
                  >
                    <p class="text-tiny text-theme-text-tertiary">Scanning folder levels...</p>
                  </Show>
                </div>
              }
            >
              <div class="mt-2 divide-y divide-theme-border">
                <For each={sessions()}>
                  {(session) => {
                    const expanded = () => expandedDates().includes(session.session_date);
                    const level = () => session.levels[chosenIndexFor(session)];
                    return (
                      <div class="py-1">
                        {/* Collapsed, the full source path is hover detail only: the
                            row states the leaf, which is the part that differs. */}
                        <button
                          type="button"
                          class="w-full flex items-center gap-3 text-xs text-left px-1 py-1 rounded-[var(--radius-sm)] hover:bg-theme-hover transition-colors cursor-pointer"
                          aria-expanded={expanded()}
                          title={expanded() ? undefined : level()?.path}
                          onClick={() => toggleExpanded(session.session_date)}
                        >
                          <svg
                            width="12"
                            height="12"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            aria-hidden="true"
                            class={`shrink-0 text-theme-text-tertiary transition-transform ${
                              expanded() ? "rotate-90" : ""
                            }`}
                          >
                            <polyline points="9 6 15 12 9 18" />
                          </svg>
                          <span class="text-theme-text-primary tabular-nums shrink-0">
                            {session.session_date}
                          </span>
                          <span class="text-tiny text-theme-text-tertiary tabular-nums shrink-0">
                            {session.total_frame_count} frames
                          </span>
                          <Show
                            when={level()}
                            fallback={
                              <span class="text-tiny text-theme-text-tertiary flex-1">
                                No frames found for this session.
                              </span>
                            }
                          >
                            <span class="flex-1 min-w-0 font-mono flex items-baseline">
                              <span class="text-theme-text-tertiary truncate">
                                {parentContext(level()!.path)}
                              </span>
                              <span class="text-theme-text-secondary shrink-0">
                                {lastSegment(level()!.path)}
                              </span>
                            </span>
                          </Show>
                          {/* Only when this row's folder is being renamed to avoid
                              colliding with another session's identically-named
                              folder. Silence here meant the user learned their
                              LIGHT folder had become 2024-11-03_LIGHT by finding it. */}
                          <Show when={renamedEntryFor(session.session_date)}>
                            {(entry) => (
                              <span
                                class="text-tiny font-mono text-theme-text-tertiary shrink-0"
                                title={`Another selected session's folder has the same name, so this one is copied as "${entry()}".`}
                              >
                                → {entry()}
                              </span>
                            )}
                          </Show>
                        </button>
                        <Show when={expanded()}>
                          <div class="mt-1 mb-1 pl-6">
                            {/* The separator comes from effectiveOs(), which honors
                                the pinned wbpp_default_os. Deriving it from the
                                root's shape instead makes the editor disagree with
                                the generated script for a pinned OS whose root does
                                not look the part (e.g. windows + /mnt/astro). */}
                            <WbppLevelEditor
                              session={session}
                              chosenIndex={chosenIndexFor(session)}
                              onSelect={(i) => {
                                selectLevel(session.session_date, i);
                                setExpandedDates((prev) =>
                                  prev.filter((d) => d !== session.session_date),
                                );
                              }}
                              libraryRoot={libraryRoot()}
                              separator={sep()}
                            />
                          </div>
                        </Show>
                      </div>
                    );
                  }}
                </For>
              </div>
            </Show>
          </div>

          {/* Zone 4: Options */}
          <div class={CARD_CLASS}>
            <div class="flex items-center gap-2">
              <h3 class={ZONE_TITLE_CLASS}>
                <span class="text-theme-text-tertiary">Step 3 · </span>Options
              </h3>
              <HelpPopover label="About quality filters" title="Quality filters">
                <p>
                  Set quality limits above (HFR, eccentricity, and so on). A frame is
                  excluded from the copy when it breaks at least one limit. A limit without a
                  number filters nothing. A frame that was never measured for a limit is not
                  judged on it; a frame with no recorded quality data at all counts as
                  unmeasured, not excluded.
                </p>
                <p>
                  The eccentricity presets are starting points: 0.55 keeps stars that look
                  round, 0.65 sits at the edge of visible stretching, and 0.75 allows clearly
                  stretched stars, useful for salvaging a poor night.
                </p>
                <p>
                  Cell colors compare each frame with the selected baseline (this session or
                  the rig catalog) and are informational only; the limits alone decide the
                  verdict.
                </p>
                <p>
                  The quality limits are saved for each rig and are the same ones Copy Frame
                  List uses. Changing a limit here also changes what that list selects.
                </p>
              </HelpPopover>
            </div>

            <div class="mt-3">
              <WbppQualityPanel
                enabled={qualityFilterOn()}
                onEnabledChange={changeQualityEnabled}
                config={qualityConfig()}
                onConfigChange={changeQualityConfig}
                verdicts={verdicts()}
                loading={qualityLoading()}
                sessionDetails={qualitySessions()}
              />
            </div>
          </div>

          {/* Script output. Generated from the footer menu; lands here. */}
          <Show when={generated()}>
            {(g) => (
              <div ref={scriptRef} class={CARD_CLASS}>
                <h3 class={ZONE_TITLE_CLASS}>Script</h3>
                <div class="flex items-center gap-2 flex-wrap mt-3">
                  <Button variant="secondary" size="sm" onClick={downloadScript}>
                    Download {g().filename}
                  </Button>
                  <Button variant="secondary" size="sm" onClick={copyScript}>
                    {copied() ? "Copied!" : "Copy script"}
                  </Button>
                </div>
                <div class="text-tiny mt-2">
                  <span class="text-theme-text-tertiary">Then run: </span>
                  <code class="font-mono text-theme-text-secondary break-all">{runCommand()}</code>
                </div>
                <div class="mt-2">
                  <button
                    type="button"
                    class="text-tiny text-theme-accent hover:text-theme-accent-hover transition-colors cursor-pointer"
                    onClick={() => setShowScript(!showScript())}
                  >
                    {showScript() ? "Hide script" : "Show script"}
                  </button>
                  <Show when={showScript()}>
                    <pre class="mt-1 text-tiny font-mono bg-theme-surface border border-theme-border rounded-[var(--radius-sm)] p-2 max-h-72 overflow-auto text-theme-text-secondary whitespace-pre">{g().script}</pre>
                  </Show>
                </div>
              </div>
            )}
          </Show>
        </div>

        <WbppFooter
          frameCount={frameCount()}
          folderCount={plan().length}
          sizeBytes={sizeBytes()}
          destination={copyDestination()}
          scriptDestination={scriptDestination()}
          permissionGranted={permissionGranted()}
          blockedBy={copyBlockedBy()}
          canBrowserCopy={canBrowserCopy}
          copying={wbppCopyRunning()}
          copyProgress={
            wbppCopyRunning()
              ? { done: wbppCopyDone(), total: wbppCopyTotal(), speed: wbppCopySpeed() }
              : null
          }
          onCopy={startBrowserCopy}
          onStop={stopCopy}
          scriptMenu={
            <WbppScriptMenu
              defaultOs={effectiveOs()}
              defaultReason={defaultReason()}
              generating={generating()}
              disabled={!libraryRoot().trim()}
              hasScript={generated() !== null}
              onGenerate={generate}
            />
          }
        />
      </div>
    </Dialog>
  );
};

export default WbppExportModal;
