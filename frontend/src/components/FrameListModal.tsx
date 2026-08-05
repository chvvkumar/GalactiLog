import {
  Component,
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
  isIncluded,
  selectedFrames,
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
  // Sparse per-row overrides keyed by source_relative. Cleared on ANY change
  // that alters what the computed verdicts mean (constraints, baseline, the
  // enable flag, mode, include-unmeasured): a hand edit must never silently
  // survive a semantics change it was not made under.
  const [overrides, setOverrides] = createSignal<Record<string, boolean>>({});
  const [format, setFormat] = createSignal<FrameListFormat>("explorer");
  const [baseFolder, setBaseFolder] = createSignal(general()?.frame_list_base_folder ?? "");

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
    if (missing.length === 0) return;
    setLoading(true);
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
        setSessionDetails((prev) => {
          const next = { ...prev };
          for (const r of results) if (r) next[r[0]] = r[1];
          return next;
        });
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

  const opts = (): FrameSelectionOptions => ({
    mode: mode(),
    includeUnmeasured: includeUnmeasured(),
    overrides: overrides(),
  });

  const selected = createMemo<FrameVerdict[]>(() => selectedFrames(effectiveVerdicts(), opts()));

  const rowIncluded = (v: FrameVerdict): boolean => isIncluded(effective(v), opts());

  // Flip the row to the opposite of its current answer; when that lands back
  // on the computed value, drop the key so the override map stays sparse.
  const toggleInclude = (v: FrameVerdict) => {
    const key = v.frame.source_relative;
    const computed = isIncluded(effective(v), {
      mode: mode(),
      includeUnmeasured: includeUnmeasured(),
      overrides: {},
    });
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

  const nameCount = () => selected().length;
  const namesWord = () => (nameCount() === 1 ? "name" : "names");
  const copyLabel = () =>
    format() === "script"
      ? `Copy script (${nameCount()} ${namesWord()})`
      : `Copy ${nameCount()} ${namesWord()}`;

  const doCopy = async () => {
    const names = selected().map((v) => v.frame.file_name);
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
                  The chips decide which frames are good and which are bad; the toggle picks
                  which set is copied. Bad is only frames a chip rejected. Frames missing all
                  constrained metrics are unmeasured and join the good list only while the
                  include unmeasured box is checked. The checkbox on a row overrides its
                  verdict for this copy, and edits are discarded when a threshold changes.
                </p>
                <p>
                  Explorer search pastes into the Windows search box and works best under a
                  few dozen names. Names is one file per line for any other tool. Script
                  finds each name under the base folder and moves it into a _rejected
                  subfolder after a confirmation prompt; the same name can exist in more than
                  one place, so the script lists every match first and the base folder is
                  best pointed at a single session.
                </p>
                <p>
                  Thresholds are saved per rig and shared with Export For Stacking: changing
                  them here also changes what that export excludes.
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

            <span class="ml-auto text-tiny text-theme-text-tertiary whitespace-nowrap">
              <span class="tabular-nums font-semibold text-theme-text-primary">
                {selected().length}
              </span>{" "}
              of <span class="tabular-nums">{totals().total}</span> frames selected
              <span class="text-theme-text-secondary">
                {" "}· <span class="tabular-nums">{totals().copy}</span> pass /{" "}
                <span class="tabular-nums">{totals().fail}</span> fail /{" "}
                <span class="tabular-nums">{totals().unmeasured}</span> unmeasured
              </span>
            </span>
          </div>

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

        {/* Footer: format, base folder for the script, and the copy action. */}
        <div class="shrink-0 px-4 py-3 border-t border-theme-border flex items-center flex-wrap gap-2">
          <select
            aria-label="Format"
            class={`${FIELD_CLASS} cursor-pointer shrink-0`}
            value={format()}
            onChange={(e) => setFormat(e.currentTarget.value as FrameListFormat)}
          >
            <option value="explorer">Explorer search string</option>
            <option value="names">Names, one per line</option>
            <option value="script">Move script</option>
          </select>
          <Show when={format() === "script"}>
            <input
              type="text"
              aria-label="Base folder"
              class={`${FIELD_CLASS} font-mono flex-1 min-w-48`}
              placeholder="D:\Staging\M31 or /mnt/staging"
              value={baseFolder()}
              onInput={(e) => setBaseFolder(e.currentTarget.value)}
            />
          </Show>
          <div class="ml-auto shrink-0">
            <Button variant="primary" size="sm" disabled={copyDisabled()} onClick={() => void doCopy()}>
              {copyLabel()}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
};

export default FrameListModal;
