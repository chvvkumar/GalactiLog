import { Component, Show, For, createSignal, createEffect } from "solid-js";
import { api } from "../api/client";
import type { ScanStatus, ActivityEntry, RebuildStatus } from "../types";

const ActivityFeed: Component<{
  scanStatus: ScanStatus;
  rebuildStatus: RebuildStatus;
  stopping: boolean;
  scanError: string | null;
  onResetAndRescan: () => void;
  onDismissStalled: () => void;
}> = (props) => {
  const [activity, setActivity] = createSignal<ActivityEntry[]>([]);
  const [prevState, setPrevState] = createSignal<string>("idle");

  const fetchActivity = async () => {
    try { setActivity(await api.getActivity()); } catch { /* ignore */ }
  };

  fetchActivity();

  // Refresh activity when scan or rebuild state transitions to complete/idle/error
  createEffect(() => {
    const scanState = props.scanStatus.state;
    const rebuildState = props.rebuildStatus.state;
    const prev = prevState();
    const current = `${scanState}:${rebuildState}`;
    if (current !== prev) {
      setPrevState(current);
      if (scanState === "complete" || scanState === "idle" || rebuildState === "complete" || rebuildState === "error") {
        fetchActivity();
      }
    }
  });

  const clearLog = async () => {
    try {
      await api.clearActivity();
      setActivity([]);
    } catch { /* ignore */ }
  };

  const isActive = () => {
    const s = props.scanStatus.state;
    return s === "scanning" || s === "ingesting";
  };

  const progressPct = () => {
    const s = props.scanStatus;
    if (s.total === 0) return 0;
    return Math.min(100, Math.round(((s.completed + s.failed) / s.total) * 100));
  };

  const elapsed = () => {
    const s = props.scanStatus;
    if (!s.started_at) return null;
    const end = s.completed_at || Date.now() / 1000;
    return Math.round(end - s.started_at);
  };

  const formatDuration = (secs: number) => {
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s}s`;
  };

  const throughput = () => {
    const el = elapsed();
    if (!el || el === 0 || props.scanStatus.completed === 0) return null;
    return (props.scanStatus.completed / el).toFixed(1);
  };

  const stateLabel = () => {
    if (props.stopping) return "Stopping...";
    switch (props.scanStatus.state) {
      case "scanning": return "Discovering files...";
      case "ingesting": return "Ingesting";
      default: return "";
    }
  };

  const lostCount = () => {
    const s = props.scanStatus;
    return s.total - s.completed - s.failed;
  };

  const formatTime = (ts: number) =>
    new Date(ts * 1000).toLocaleString([], { timeZone: "UTC", hour: "2-digit", minute: "2-digit" }) + " UTC";

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Activity</h3>
        <Show when={activity().length > 0 && !isActive()}>
          <button
            onClick={clearLog}
            class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          >
            Clear
          </button>
        </Show>
      </div>

      <Show when={props.scanError}>
        <p class="text-xs text-theme-error">{props.scanError}</p>
      </Show>

      {/* Live scan progress */}
      <Show when={isActive()}>
        <div class="space-y-2 border border-theme-border-em rounded-[var(--radius-md)] p-3">
          <div class="flex justify-between text-xs text-theme-text-secondary">
            <span class="flex items-center gap-2">
              <span class="w-2 h-2 bg-theme-accent rounded-full animate-pulse flex-shrink-0" />
              {stateLabel()}
            </span>
            <Show when={props.scanStatus.state === "scanning"}>
              <span>{props.scanStatus.discovered > 0 ? `${props.scanStatus.discovered.toLocaleString()} files found` : ""}</span>
            </Show>
            <Show when={props.scanStatus.state === "ingesting"}>
              <span>{props.scanStatus.completed + props.scanStatus.failed} / {props.scanStatus.total}</span>
            </Show>
          </div>
          <Show when={props.scanStatus.state === "scanning"}>
            <div class="w-full bg-theme-base rounded-full h-2 overflow-hidden">
              <div class="bg-theme-accent h-2 rounded-full animate-pulse w-full opacity-30" />
            </div>
          </Show>
          <Show when={props.scanStatus.state === "ingesting"}>
            <div class="w-full bg-theme-base rounded-full h-2">
              <div class="bg-theme-accent h-2 rounded-full transition-all" style={{ width: `${progressPct()}%` }} />
            </div>
            <div class="flex gap-4 text-xs text-theme-text-secondary">
              <Show when={elapsed() != null}>
                <span>Elapsed: {formatDuration(elapsed()!)}</span>
              </Show>
              <Show when={throughput() != null}>
                <span>{throughput()} files/s</span>
              </Show>
            </div>
          </Show>
        </div>
      </Show>

      {/* Live rebuild progress */}
      <Show when={props.rebuildStatus.state === "running"}>
        <div class="flex items-center gap-2 border border-theme-border-em rounded-[var(--radius-md)] p-3">
          <span class="w-2 h-2 bg-theme-accent rounded-full animate-pulse flex-shrink-0" />
          <span class="text-xs text-theme-text-primary">{props.rebuildStatus.message || "Running..."}</span>
        </div>
      </Show>

      {/* Stalled warning */}
      <Show when={props.scanStatus.state === "stalled"}>
        <div class="bg-theme-warning/20 border border-theme-warning/50 rounded-[var(--radius-md)] p-3 space-y-2">
          <span class="text-theme-warning text-sm font-medium">Scan stalled</span>
          <p class="text-xs text-theme-warning/80">
            {props.scanStatus.completed + props.scanStatus.failed} of {props.scanStatus.total} files were processed
            ({props.scanStatus.completed} ingested, {props.scanStatus.failed} failed)
            but {lostCount()} tasks stopped responding.
          </p>
          <p class="text-xs text-theme-warning/60">
            Already-ingested files are safe. A rescan will pick up the {lostCount()} remaining files.
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={props.onResetAndRescan}
              class="px-3 py-1.5 bg-theme-accent text-theme-text-primary rounded text-xs font-medium hover:bg-theme-accent/80 transition-colors"
            >
              Reset & Rescan
            </button>
            <button
              onClick={props.onDismissStalled}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-theme-accent hover:text-theme-text-primary transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      </Show>

      {/* Failed files (expandable) */}
      <Show when={(props.scanStatus.failed_files?.length ?? 0) > 0}>
        <FailedFilesSection files={props.scanStatus.failed_files!} />
      </Show>

      {/* Historical activity log */}
      <Show when={activity().length > 0}>
        <div class="space-y-1">
          <For each={activity()}>
            {(entry) => (
              <div class="flex gap-3 text-xs py-1.5 border-t border-theme-border first:border-0">
                <span class="text-theme-text-secondary flex-shrink-0 min-w-[4.5rem]">
                  {formatTime(entry.timestamp)}
                </span>
                <span class={
                  entry.type.includes("failed") ? "text-theme-error" :
                  entry.type.includes("stopped") || entry.type.includes("stalled") || entry.type.includes("warning") ? "text-theme-warning" :
                  entry.type.startsWith("migration_") ? "text-theme-text-secondary" :
                  "text-theme-text-primary"
                }>
                  {entry.message}
                </span>
              </div>
            )}
          </For>
        </div>
      </Show>

      {/* Empty state */}
      <Show when={!isActive() && props.rebuildStatus.state !== "running" && props.scanStatus.state !== "stalled" && activity().length === 0 && !props.scanError}>
        <p class="text-xs text-theme-text-secondary">No recent activity</p>
      </Show>
    </div>
  );
};

const FailedFilesSection: Component<{ files: { file: string; error: string }[] }> = (props) => {
  const [expanded, setExpanded] = createSignal(false);
  return (
    <div class="space-y-1">
      <button
        onClick={() => setExpanded((v) => !v)}
        class="text-xs text-theme-error hover:underline"
      >
        {expanded() ? "Hide" : "Show"} {props.files.length} failed file{props.files.length > 1 ? "s" : ""}
      </button>
      <Show when={expanded()}>
        <div class="max-h-40 overflow-y-auto space-y-1">
          <For each={props.files}>
            {(f) => (
              <div class="border border-theme-border rounded px-2 py-1">
                <div class="text-xs text-theme-text-secondary break-all">{f.file}</div>
                <div class="text-xs text-theme-error/70 truncate" title={f.error}>{f.error}</div>
              </div>
            )}
          </For>
        </div>
      </Show>
    </div>
  );
};

export default ActivityFeed;
