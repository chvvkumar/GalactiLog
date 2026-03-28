import { Component, Show, For, createSignal, createEffect, onCleanup } from "solid-js";
import { useScan } from "../store/scan";
import { useSettingsContext } from "./SettingsProvider";
import { api } from "../api/client";

type FrameFilter = "all" | "light_only";

const ScanManager: Component = () => {
  const { scanStatus, scanError, isActive, startScan, startRegeneration, resetScan, stopPolling } = useScan();
  const { settings } = useSettingsContext();
  const [expanded, setExpanded] = createSignal(true);
  const [frameFilter, setFrameFilter] = createSignal<FrameFilter>("all");
  const [dbSummary, setDbSummary] = createSignal<import("../types").DbSummary | null>(null);

  const refreshDbSummary = async () => {
    try { setDbSummary(await api.getDbSummary()); } catch { /* ignore */ }
  };
  refreshDbSummary();

  // Refresh DB summary when scan completes or goes idle
  createEffect(() => {
    const s = scanStatus().state;
    if (s === "complete" || s === "idle") refreshDbSummary();
  });

  // Sync frameFilter from server settings once loaded
  createEffect(() => {
    const s = settings();
    if (s) {
      setFrameFilter(s.general.include_calibration ? "all" : "light_only");
    }
  });

  onCleanup(stopPolling);

  const progressPct = () => {
    const s = scanStatus();
    if (s.total === 0) return 0;
    return Math.round(((s.completed + s.failed) / s.total) * 100);
  };

  const elapsed = () => {
    const s = scanStatus();
    if (!s.started_at) return null;
    const end = s.completed_at || Date.now() / 1000;
    return Math.round(end - s.started_at);
  };

  const throughput = () => {
    const el = elapsed();
    if (!el || el === 0 || scanStatus().completed === 0) return null;
    return (scanStatus().completed / el).toFixed(1);
  };

  const formatDuration = (secs: number) => {
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s}s`;
  };

  const stateLabel = () => {
    switch (scanStatus().state) {
      case "scanning": return "Discovering files...";
      case "ingesting": return "Ingesting";
      case "complete": return "Complete";
      case "stalled": return "Stalled";
      default: return "Ready";
    }
  };

  const lostCount = () => {
    const s = scanStatus();
    return s.total - s.completed - s.failed;
  };

  const handleResetAndRescan = async () => {
    await resetScan();
    startScan({ includeCalibration: frameFilter() === "all" });
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center">
        <h3 class="text-theme-text-primary font-medium">Scan & Ingest</h3>
        <div class="flex gap-2">
          <button
            onClick={() => startScan({ includeCalibration: frameFilter() === "all" })}
            disabled={isActive()}
            class="px-4 py-1.5 bg-theme-accent text-theme-text-primary rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/80 transition-colors"
          >
            {isActive() ? "Scanning..." : "Scan Directory"}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 text-sm">
        <span class="text-theme-text-secondary text-xs">Include:</span>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="frame-filter"
            checked={frameFilter() === "all"}
            onChange={() => setFrameFilter("all")}
            disabled={isActive()}
            class="accent-astro-accent"
          />
          <span class={`text-xs ${frameFilter() === "all" ? "text-theme-text-primary" : "text-theme-text-secondary"}`}>All frames</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input
            type="radio"
            name="frame-filter"
            checked={frameFilter() === "light_only"}
            onChange={() => setFrameFilter("light_only")}
            disabled={isActive()}
            class="accent-astro-accent"
          />
          <span class={`text-xs ${frameFilter() === "light_only" ? "text-theme-text-primary" : "text-theme-text-secondary"}`}>Light frames only</span>
        </label>
      </div>

      <Show when={scanError()}>
        <p class="text-xs text-theme-error">{scanError()}</p>
      </Show>

      {/* Stalled state — explain what happened and offer remediation */}
      <Show when={scanStatus().state === "stalled"}>
        <div class="bg-theme-warning/20 border border-theme-warning/50 rounded-[var(--radius-md)] p-3 space-y-2">
          <div class="flex items-start gap-2">
            <span class="text-theme-warning text-sm font-medium">Scan stalled</span>
          </div>
          <p class="text-xs text-theme-warning/80">
            {scanStatus().completed + scanStatus().failed} of {scanStatus().total} files were processed
            ({scanStatus().completed} ingested, {scanStatus().failed} failed)
            but {lostCount()} tasks stopped responding — likely due to a container restart or worker crash.
          </p>
          <p class="text-xs text-theme-warning/60">
            Already-ingested files are safe. A rescan will pick up the {lostCount()} remaining files.
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={handleResetAndRescan}
              class="px-3 py-1.5 bg-theme-accent text-theme-text-primary rounded text-xs font-medium hover:bg-theme-accent/80 transition-colors"
            >
              Reset & Rescan
            </button>
            <button
              onClick={resetScan}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-theme-accent hover:text-theme-text-primary transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </Show>

      <Show when={isActive()}>
        <div class="space-y-1">
          <div class="flex justify-between text-xs text-theme-text-secondary">
            <span>{stateLabel()}</span>
            <span>{scanStatus().completed + scanStatus().failed} / {scanStatus().total}</span>
          </div>
          <div class="w-full bg-theme-base rounded-full h-2">
            <div class="bg-theme-accent h-2 rounded-full transition-all" style={{ width: `${progressPct()}%` }} />
          </div>
        </div>
      </Show>

      <Show when={!isActive() && scanStatus().state === "complete"}>
        <div class="flex justify-between items-center text-xs">
          <span class="text-theme-success">Complete</span>
          <span class="text-theme-text-secondary">
            {scanStatus().completed} ingested
            {scanStatus().csv_enriched > 0 ? ` \u00b7 ${scanStatus().csv_enriched} with CSV metrics` : ""}
            {scanStatus().completed_at ? ` \u00b7 ${new Date(scanStatus().completed_at! * 1000).toLocaleString()}` : ""}
          </span>
        </div>
      </Show>

      <Show when={!isActive() && scanStatus().state === "idle" && scanStatus().completed_at}>
        <div class="text-xs text-theme-text-secondary">
          Last scan: {new Date(scanStatus().completed_at! * 1000).toLocaleString()}
          {scanStatus().completed > 0 ? ` \u00b7 ${scanStatus().completed} ingested` : ""}
          {scanStatus().csv_enriched > 0 ? ` \u00b7 ${scanStatus().csv_enriched} with CSV` : ""}
        </div>
      </Show>

      <Show when={scanStatus().state !== "idle" && scanStatus().state !== "stalled"}>
        <button onClick={() => setExpanded((v) => !v)} class="text-xs text-theme-accent hover:underline w-full text-left">
          {expanded() ? "Hide details" : "Show details"}
        </button>
      </Show>

      <Show when={expanded() && scanStatus().state !== "idle" && scanStatus().state !== "stalled"}>
        <div class="border-t border-theme-border pt-3 space-y-2 text-xs">
          <div class="grid grid-cols-2 gap-y-1.5 gap-x-4">
            <span class="text-theme-text-secondary">Status</span><span class="text-theme-text-primary">{stateLabel()}</span>
            <span class="text-theme-text-secondary">Total</span><span class="text-theme-text-primary">{scanStatus().total}</span>
            <span class="text-theme-text-secondary">Completed</span><span class="text-theme-success">{scanStatus().completed}</span>
            <span class="text-theme-text-secondary">Failed</span><span class={scanStatus().failed > 0 ? "text-theme-error" : "text-theme-text-secondary"}>{scanStatus().failed}</span>
            <Show when={scanStatus().csv_enriched > 0}>
              <span class="text-theme-text-secondary">CSV Enriched</span><span class="text-theme-info">{scanStatus().csv_enriched}</span>
            </Show>
            <Show when={elapsed() != null}>
              <span class="text-theme-text-secondary">Elapsed</span><span class="text-theme-text-primary">{formatDuration(elapsed()!)}</span>
            </Show>
            <Show when={throughput() != null}>
              <span class="text-theme-text-secondary">Throughput</span><span class="text-theme-text-primary">{throughput()} files/s</span>
            </Show>
          </div>
          <Show when={scanStatus().total > 0}>
            <div class="w-full bg-theme-base rounded-full h-3 overflow-hidden flex">
              <div class="bg-theme-success h-3 transition-all" style={{ width: `${(scanStatus().completed / scanStatus().total) * 100}%` }} />
              <div class="bg-theme-error h-3 transition-all" style={{ width: `${(scanStatus().failed / scanStatus().total) * 100}%` }} />
            </div>
          </Show>
          <Show when={(scanStatus().failed_files?.length ?? 0) > 0}>
            <div class="mt-2 space-y-1">
              <span class="text-theme-error font-medium">Failed files:</span>
              <div class="max-h-40 overflow-y-auto space-y-1">
                <For each={scanStatus().failed_files}>
                  {(f) => (
                    <div class="border border-theme-border rounded px-2 py-1">
                      <div class="text-theme-text-secondary break-all">{f.file}</div>
                      <div class="text-theme-error/70 truncate" title={f.error}>{f.error}</div>
                    </div>
                  )}
                </For>
              </div>
            </div>
          </Show>
        </div>
      </Show>

      {/* Database Summary */}
      <Show when={dbSummary()}>
        <div class="border-t border-theme-border pt-3 mt-1">
          <div class="grid grid-cols-5 gap-2 text-center">
            <div>
              <div class="text-sm font-medium text-theme-text-primary">{dbSummary()!.total_images.toLocaleString()}</div>
              <div class="text-xs text-theme-text-secondary">Total Images</div>
            </div>
            <div>
              <div class="text-sm font-medium text-theme-text-primary">{dbSummary()!.light_frames.toLocaleString()}</div>
              <div class="text-xs text-theme-text-secondary">Light Frames</div>
            </div>
            <div>
              <div class="text-sm font-medium text-theme-text-primary">{dbSummary()!.resolved_targets}</div>
              <div class="text-xs text-theme-text-secondary">Targets</div>
            </div>
            <div>
              <div class={`text-sm font-medium ${dbSummary()!.unresolved_images > 0 ? "text-theme-warning" : "text-theme-text-primary"}`}>
                {dbSummary()!.unresolved_images}
              </div>
              <div class="text-xs text-theme-text-secondary">Unresolved</div>
            </div>
            <div>
              <div class="text-sm font-medium text-theme-info">{dbSummary()!.csv_enriched.toLocaleString()}</div>
              <div class="text-xs text-theme-text-secondary">CSV Enriched</div>
            </div>
          </div>
          <Show when={dbSummary()!.cached_simbad > 0 || dbSummary()!.pending_merges > 0}>
            <div class="flex gap-4 mt-2 text-xs text-theme-text-secondary justify-center">
              <Show when={dbSummary()!.cached_simbad > 0}>
                <span>{dbSummary()!.cached_simbad} SIMBAD cached ({dbSummary()!.cached_negative} negative)</span>
              </Show>
              <Show when={dbSummary()!.pending_merges > 0}>
                <span class="text-theme-warning">{dbSummary()!.pending_merges} pending merges</span>
              </Show>
            </div>
          </Show>
        </div>
      </Show>

      {/* Database Maintenance */}
      <RebuildTargetsSection disabled={isActive()} onRegenThumbnails={startRegeneration} onRefreshSummary={refreshDbSummary} />

    </div>
  );
};


const RebuildTargetsSection: Component<{ disabled: boolean; onRegenThumbnails: () => void; onRefreshSummary: () => void }> = (props) => {
  const [showFullConfirm, setShowFullConfirm] = createSignal(false);
  const [rebuildState, setRebuildState] = createSignal<import("../types").RebuildStatus>({
    state: "idle", mode: "", message: "", started_at: null, completed_at: null, details: {},
  });
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const fetchRebuildStatus = async () => {
    try {
      const status = await api.getRebuildStatus();
      const prev = rebuildState().state;
      setRebuildState(status);
      if (status.state !== "running") {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        if (prev === "running" && status.state === "complete") props.onRefreshSummary();
      }
    } catch { /* ignore */ }
  };

  // Check on mount if a rebuild is running
  onCleanup(() => { if (pollTimer) clearInterval(pollTimer); });
  fetchRebuildStatus();

  const startPolling = () => {
    if (pollTimer) return;
    fetchRebuildStatus();
    pollTimer = setInterval(fetchRebuildStatus, 2000);
  };

  const isRunning = () => rebuildState().state === "running";

  const runAction = async (action: () => Promise<any>) => {
    setShowFullConfirm(false);
    try {
      await action();
      startPolling();
    } catch (e: any) {
      setRebuildState((prev) => ({
        ...prev, state: "error" as const, message: e?.message || "Failed to start",
      }));
    }
  };

  const detailEntries = () => {
    const d = rebuildState().details;
    if (!d || Object.keys(d).length === 0) return [];
    const labels: Record<string, string> = {
      resolved: "Targets resolved",
      failed: "Failed to resolve",
      total: "Total object names",
      redirected_merged: "Orphaned images fixed",
      linked_unresolved: "Unresolved images linked",
      aliases_updated: "Target aliases updated",
      rederived: "Targets re-derived from cache",
      names_rebuilt: "Names rebuilt",
      stale_candidates_removed: "Stale candidates removed",
    };
    return Object.entries(d)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({ label: labels[k] || k, value: v }));
  };

  return (
    <div class="border-t border-theme-border pt-3 mt-3 space-y-3">
      <h4 class="text-theme-text-primary text-sm font-medium">Target Database Maintenance</h4>

      {/* Quick Fix */}
      <div class="flex justify-between items-center">
        <div>
          <p class="text-xs text-theme-text-primary">Quick Fix</p>
          <p class="text-xs text-theme-text-secondary">
            Re-links orphaned images to existing targets by matching OBJECT headers against known aliases.
            Updates target names and aliases from SIMBAD cache. Does not contact SIMBAD or create new targets.
          </p>
        </div>
        <button
          onClick={() => runAction(api.smartRebuildTargets)}
          disabled={props.disabled || isRunning()}
          class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
        >
          {isRunning() && rebuildState().mode === "smart" ? "Running..." : "Quick Fix"}
        </button>
      </div>

      {/* Regenerate Thumbnails */}
      <div class="flex justify-between items-center">
        <div>
          <p class="text-xs text-theme-text-primary">Regenerate Thumbnails</p>
          <p class="text-xs text-theme-text-secondary">
            Re-creates all image thumbnails using current stretch settings.
            Does not affect targets, resolution status, or any database records.
          </p>
        </div>
        <button
          onClick={() => props.onRegenThumbnails()}
          disabled={props.disabled || isRunning()}
          class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
        >
          Regenerate
        </button>
      </div>

      {/* Full Rebuild */}
      <div class="flex justify-between items-center">
        <div>
          <p class="text-xs text-theme-text-primary">Full Rebuild</p>
          <p class="text-xs text-theme-text-secondary">
            Deletes all targets, merge history, and suggested merges, then re-resolves every unique
            OBJECT name from FITS headers via SIMBAD. Uses cached results when available.
          </p>
        </div>
        <button
          onClick={() => setShowFullConfirm(true)}
          disabled={props.disabled || isRunning()}
          class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 hover:text-theme-error transition-colors"
        >
          {isRunning() && rebuildState().mode === "full" ? "Running..." : "Full Rebuild"}
        </button>
      </div>

      <Show when={showFullConfirm()}>
        <div class="bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-error font-medium">Are you sure?</p>
          <p class="text-xs text-theme-error/70">
            This will delete all target records, merge history, and suggested merges.
            All targets will be re-resolved from scratch using SIMBAD. Fast if results
            are cached from a previous run. First run may take 30 minutes or more
            depending on the number of unique targets and SIMBAD response times.
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => runAction(api.rebuildTargets)}
              class="px-3 py-1.5 bg-theme-error text-theme-text-primary rounded text-xs font-medium hover:opacity-90 transition-colors"
            >
              Yes, rebuild everything
            </button>
            <button
              onClick={() => setShowFullConfirm(false)}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-white hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </Show>

      {/* Status / Progress */}
      <Show when={rebuildState().state === "running"}>
        <div class="bg-theme-base rounded p-2 space-y-1">
          <div class="flex items-center gap-2">
            <div class="w-2 h-2 bg-theme-accent rounded-full animate-pulse" />
            <span class="text-xs text-theme-text-primary">{rebuildState().message || "Running..."}</span>
          </div>
        </div>
      </Show>

      {/* Results */}
      <Show when={rebuildState().state === "complete"}>
        <div class="bg-theme-base rounded p-2 space-y-1">
          <div class="flex justify-between items-center">
            <span class="text-xs text-theme-success">{rebuildState().message}</span>
            <span class="text-xs text-theme-text-secondary">
              {rebuildState().completed_at
                ? new Date(rebuildState().completed_at! * 1000).toLocaleString()
                : ""}
            </span>
          </div>
          <Show when={detailEntries().length > 0}>
            <div class="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1">
              <For each={detailEntries()}>
                {(e) => (
                  <>
                    <span class="text-xs text-theme-text-secondary">{e.label}</span>
                    <span class="text-xs text-theme-text-primary">{e.value}</span>
                  </>
                )}
              </For>
            </div>
          </Show>
        </div>
      </Show>

      <Show when={rebuildState().state === "error"}>
        <p class="text-xs text-theme-error">{rebuildState().message}</p>
      </Show>
    </div>
  );
};


export default ScanManager;
