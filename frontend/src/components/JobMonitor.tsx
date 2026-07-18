import { Component, For, Show, createSignal, createEffect, onCleanup } from "solid-js";
import { A } from "@solidjs/router";
import { useAuth } from "./AuthProvider";
import { useScan, scanStatus, refreshScanStatus } from "../store/scan";
import { rebuildStatus, refreshRebuildStatus } from "../store/rebuild";
import {
  monitorJobs,
  hasMonitorJobs,
  stripProgress,
  wireGlobalJobSources,
} from "../store/jobMonitor";
import {
  errorEvents,
  unseenErrorCount,
  markAllErrorsSeen,
  setActivitySeenAt,
} from "../store/activityErrors";
import type { ActiveJob } from "../api/types";

const IDLE_CHECK_MS = 30_000;
const PANEL_ERROR_LIMIT = 5;

function timeAgo(iso: string): string {
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const JobRow: Component<{ job: ActiveJob }> = (props) => (
  <div class="px-4 py-2.5 space-y-1.5 border-t border-theme-border first:border-t-0">
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-medium text-theme-text-primary truncate">{props.job.label}</span>
      <Show when={props.job.cancelable && props.job.onCancel}>
        <button
          onClick={() => props.job.onCancel?.()}
          class="px-2 py-0.5 text-xs border border-theme-border-em text-theme-text-secondary rounded-[var(--radius-sm)] hover:border-theme-error hover:text-theme-error transition-colors shrink-0"
        >
          Stop
        </button>
      </Show>
    </div>
    <div class="h-1 rounded-full overflow-hidden bg-theme-elevated">
      <Show
        when={props.job.progress !== undefined}
        fallback={
          <div
            data-jobmonitor-anim
            class="h-full w-[35%] rounded-full bg-theme-accent"
            style={{ animation: "jobmonitor-slide 1.4s ease-in-out infinite" }}
          />
        }
      >
        <div
          class="h-full rounded-full bg-theme-accent transition-all"
          style={{ width: `${Math.round((props.job.progress ?? 0) * 100)}%` }}
        />
      </Show>
    </div>
    <Show when={props.job.subLabel}>
      <div class="text-tiny text-theme-text-secondary tabular-nums truncate">
        {props.job.subLabel}
        <Show when={props.job.category === "wbpp_copy"}>
          <span class="text-theme-text-tertiary"> · runs in this tab; closing it stops the copy</span>
        </Show>
      </div>
    </Show>
  </div>
);

/**
 * Ambient job monitor, mounted inside NavBar's right cluster on every page:
 * a 2px aggregate progress strip on the header's bottom edge, an Activity
 * chip (job count + unseen-error badge), and an anchored job-center panel.
 * The strip and panel position absolutely against the header element (the
 * nearest positioned ancestor: the header is position: sticky), the same
 * technique NavBar's mobile dropdown uses.
 */
const JobMonitor: Component = () => {
  wireGlobalJobSources();
  const { user } = useAuth();
  // Ref-counted 2s poller while a scan is active, plus one status fetch on
  // mount. NavBar (and therefore this component) is mounted on every page
  // except /login, so the subscriber count never drops to zero mid-session.
  useScan();

  // Seed the server-side seen marker from the auth "me" payload.
  createEffect(() => {
    const u = user();
    if (u) setActivitySeenAt(u.activity_seen_at ?? null);
  });

  // Idle watch (planner-chosen mechanism, see plan header): while nothing is
  // known to run, one cheap status check every 30s detects scans or rebuilds
  // started elsewhere (auto-scan schedule, another tab). While a job runs,
  // the existing 2s pollers own freshness and this tick does nothing.
  const idleTimer = setInterval(() => {
    const s = scanStatus().state;
    if (s !== "scanning" && s !== "ingesting") void refreshScanStatus();
    if (rebuildStatus().state !== "running") void refreshRebuildStatus();
  }, IDLE_CHECK_MS);
  onCleanup(() => clearInterval(idleTimer));

  const [open, setOpen] = createSignal(false);
  let panelRef: HTMLDivElement | undefined;
  let chipRef: HTMLButtonElement | undefined;

  const onDocMouseDown = (e: MouseEvent) => {
    if (!open()) return;
    const t = e.target as Node;
    if (panelRef?.contains(t) || chipRef?.contains(t)) return;
    setOpen(false);
  };
  document.addEventListener("mousedown", onDocMouseDown);
  onCleanup(() => document.removeEventListener("mousedown", onDocMouseDown));

  const chipVisible = () => hasMonitorJobs() || unseenErrorCount() > 0;
  const jobCount = () => monitorJobs().length;
  const recentErrors = () => errorEvents().slice(0, PANEL_ERROR_LIMIT);

  return (
    <>
      <style>{`
        @keyframes jobmonitor-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }
        @keyframes jobmonitor-shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
        @keyframes jobmonitor-pulse { 0% { transform: scale(0.5); opacity: 0.4; } 70%, 100% { transform: scale(1.4); opacity: 0; } }
        @media (prefers-reduced-motion: reduce) {
          [data-jobmonitor-anim] { animation: none !important; }
        }
      `}</style>

      {/* Activity chip */}
      <Show when={chipVisible()}>
        <button
          ref={chipRef}
          onClick={() => setOpen(!open())}
          class={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium text-theme-text-primary transition-colors ${
            open()
              ? "bg-theme-accent/20 border-theme-accent/40"
              : "bg-theme-accent/10 border-theme-accent/25 hover:bg-theme-accent/15"
          }`}
          aria-expanded={open()}
          aria-label="Background activity"
        >
          <Show when={hasMonitorJobs()}>
            <span class="relative inline-block h-1.5 w-1.5 rounded-full bg-theme-accent">
              <span
                data-jobmonitor-anim
                class="absolute -inset-[3px] rounded-full bg-theme-accent opacity-40"
                style={{ animation: "jobmonitor-pulse 2s ease-out infinite" }}
              />
            </span>
          </Show>
          <span class="tabular-nums">
            {jobCount() > 0 ? `${jobCount()} job${jobCount() !== 1 ? "s" : ""}` : "Activity"}
          </span>
          <Show when={unseenErrorCount() > 0}>
            <span class="min-w-[16px] h-4 px-1 inline-flex items-center justify-center rounded-full bg-theme-error/20 text-theme-error text-[10px] font-semibold tabular-nums">
              {unseenErrorCount()}
            </span>
          </Show>
        </button>
      </Show>

      {/* Ambient 2px progress strip along the NavBar bottom edge */}
      <Show when={hasMonitorJobs()}>
        <div
          class="absolute left-0 right-0 -bottom-px h-0.5 overflow-hidden bg-theme-accent/15"
          aria-hidden="true"
        >
          <div
            class="absolute inset-y-0 left-0 bg-theme-accent transition-all duration-500"
            style={{ width: `${Math.round((stripProgress() ?? 1) * 100)}%` }}
          >
            <div
              data-jobmonitor-anim
              class="absolute inset-0 w-2/5"
              style={{
                background:
                  "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.45) 50%, transparent 100%)",
                animation: "jobmonitor-shimmer 1.8s ease-in-out infinite",
              }}
            />
          </div>
        </div>
      </Show>

      {/* Anchored job-center panel */}
      <Show when={open()}>
        <div
          ref={panelRef}
          class="absolute top-full right-4 mt-2 w-[400px] max-w-[calc(100vw-2rem)] glass-popover bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] shadow-[var(--shadow-md)] z-40"
        >
          <div class="px-4 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-theme-text-tertiary">
            Active jobs
          </div>
          <Show
            when={monitorJobs().length > 0}
            fallback={<div class="px-4 py-2 text-xs text-theme-text-tertiary">No jobs running.</div>}
          >
            <For each={monitorJobs()}>{(j) => <JobRow job={j} />}</For>
          </Show>

          <div class="border-t border-theme-border-em mt-2" />
          <div class="px-4 pt-3 pb-1 flex items-center justify-between">
            <span class="text-[11px] font-semibold uppercase tracking-wider text-theme-text-tertiary">
              Recent errors
            </span>
            <Show when={unseenErrorCount() > 0}>
              <button
                onClick={() => void markAllErrorsSeen()}
                class="text-tiny text-theme-text-secondary hover:text-theme-accent transition-colors"
              >
                Mark all seen
              </button>
            </Show>
          </div>
          <Show
            when={recentErrors().length > 0}
            fallback={<div class="px-4 py-2 text-xs text-theme-text-tertiary">No recent errors.</div>}
          >
            <For each={recentErrors()}>
              {(item) => (
                <div class="px-4 py-2 flex items-start gap-2.5 border-t border-theme-border first:border-t-0">
                  <span class="mt-1.5 h-1.5 w-1.5 rounded-full bg-theme-error shrink-0" />
                  <span class="text-xs text-theme-text-primary leading-snug min-w-0 flex-1">
                    {item.message}
                  </span>
                  <span class="text-tiny text-theme-text-tertiary tabular-nums whitespace-nowrap">
                    {timeAgo(item.timestamp)}
                  </span>
                </div>
              )}
            </For>
          </Show>

          <div class="border-t border-theme-border-em px-4 py-2.5 text-center">
            <A
              href="/settings"
              class="text-xs font-medium text-theme-accent hover:text-theme-accent-hover transition-colors"
              onClick={() => setOpen(false)}
            >
              View all activity
            </A>
          </div>
        </div>
      </Show>
    </>
  );
};

export default JobMonitor;
