import {
  Component,
  For,
  Show,
  createSignal,
  createEffect,
  onMount,
  onCleanup,
  batch,
} from "solid-js";
import { A } from "@solidjs/router";
import { activeJobs, hasActiveJobs } from "../store/activeJobs";
import { api } from "../api/client";
import { useSettingsContext } from "./SettingsProvider";
import type {
  ActivityEvent,
  ActivityCategory,
  ActivitySeverity,
  ActiveJob,
} from "../types";
import FailedFilesList from "./activity/FailedFilesList";
import EnrichmentFailureList from "./activity/EnrichmentFailureList";
import DetailsJsonFallback from "./activity/DetailsJsonFallback";
import KeyValueDetails from "./activity/KeyValueDetails";

const SEVERITY_ICON: Record<ActivitySeverity, string> = {
  info: "\u25CF", // filled circle
  warning: "\u25B2", // filled triangle
  error: "\u2715", // cross
};

const SEVERITY_CLASS: Record<ActivitySeverity, string> = {
  info: "text-theme-text-secondary",
  warning: "text-theme-warning",
  error: "text-theme-error",
};

const CATEGORY_LABELS: Record<ActivityCategory, string> = {
  scan: "scan",
  rebuild: "reb",
  thumbnail: "thumb",
  enrichment: "enrich",
  mosaic: "mosaic",
  migration: "migr",
  user_action: "user",
  system: "sys",
};

const ALL_CATEGORIES: ActivityCategory[] = [
  "scan", "rebuild", "thumbnail", "enrichment",
  "mosaic", "migration", "user_action", "system",
];

const IndeterminateBar: Component = () => (
  <div class="w-full h-1.5 rounded-full overflow-hidden bg-[var(--color-bg-subtle)]">
    <div
      class="h-full rounded-full"
      style={{
        background: "var(--color-accent)",
        animation: "activityIndeterminate 1.6s ease-in-out infinite",
        width: "40%",
      }}
    />
    <style>{`
      @keyframes activityIndeterminate {
        0%   { transform: translateX(-150%); }
        100% { transform: translateX(350%); }
      }
    `}</style>
  </div>
);

function startedAgo(startedAt: number): string {
  const secs = Math.floor((Date.now() - startedAt) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} ago`;
}

const ActiveJobRow: Component<{ job: ActiveJob }> = (props) => {
  const [agoLabel, setAgoLabel] = createSignal(startedAgo(props.job.startedAt));

  const timer = setInterval(() => {
    setAgoLabel(startedAgo(props.job.startedAt));
  }, 5000);
  onCleanup(() => clearInterval(timer));

  return (
    <div class="space-y-1.5 py-2">
      <div class="flex items-center justify-between gap-2">
        <div class="flex flex-col min-w-0">
          <span class="text-xs font-medium text-theme-text-primary truncate">
            {props.job.label}
          </span>
          <Show when={props.job.subLabel}>
            <span class="text-xs text-theme-text-secondary truncate">
              {props.job.subLabel}
            </span>
          </Show>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <span class="text-xs text-theme-text-secondary">{agoLabel()}</span>
          <Show when={props.job.cancelable && props.job.onCancel}>
            <button
              onClick={() => props.job.onCancel?.()}
              class="px-2 py-1 text-xs border border-theme-border-em text-theme-text-secondary rounded hover:border-theme-error hover:text-theme-error transition-colors"
            >
              Stop
            </button>
          </Show>
        </div>
      </div>
      <Show
        when={props.job.progress !== undefined}
        fallback={<IndeterminateBar />}
      >
        {(_) => {
          const pct = () => Math.round((props.job.progress ?? 0) * 100);
          return (
            <div class="w-full h-1.5 rounded-full overflow-hidden bg-[var(--color-bg-subtle)]">
              <div
                class="h-full rounded-full transition-all"
                style={{
                  background: "var(--color-accent)",
                  width: `${pct()}%`,
                }}
              />
            </div>
          );
        }}
      </Show>
    </div>
  );
};

function isPrimitive(value: unknown): boolean {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function isShallowPrimitiveObject(
  details: Record<string, unknown>,
): boolean {
  const values = Object.values(details);
  if (values.length === 0) return false;
  return values.every(isPrimitive);
}

function detailsRedundantWithMessage(
  details: Record<string, unknown> | null,
  message: string,
): boolean {
  if (!details) return true;
  const entries = Object.entries(details);
  if (entries.length === 0) return true;
  if (entries.length !== 1) return false;
  const [, value] = entries[0];
  if (typeof value !== "number") return false;
  const needle = String(value);
  return message.includes(needle);
}

const RowDetails: Component<{ event: ActivityEvent }> = (props) => {
  const d = props.event.details;
  if (!d) return null;

  if (
    props.event.category === "scan" &&
    Array.isArray((d as any).failed_files)
  ) {
    return (
      <FailedFilesList
        files={(d as any).failed_files}
        truncated={(d as any).truncated ?? false}
      />
    );
  }

  if (
    props.event.category === "enrichment" &&
    Array.isArray((d as any).failed_targets)
  ) {
    return <EnrichmentFailureList targets={(d as any).failed_targets} />;
  }

  if (isShallowPrimitiveObject(d as Record<string, unknown>)) {
    return <KeyValueDetails details={d as Record<string, unknown>} />;
  }

  return <DetailsJsonFallback details={d} />;
};

const TargetLinkedMessage: Component<{ event: ActivityEvent }> = (props) => (
  <span>
    {props.event.message}
    {" "}
    <A
      href={`/targets/${props.event.target_id}`}
      class="text-theme-accent hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      {"\u2197"}
    </A>
  </span>
);

const HistoryRow: Component<{ event: ActivityEvent }> = (props) => {
  const settingsCtx = useSettingsContext();
  const [expanded, setExpanded] = createSignal(false);
  const hasDetails = () => {
    const d = props.event.details;
    if (d === null || d === undefined) return false;
    if (typeof d !== "object") return false;
    const record = d as Record<string, unknown>;
    if (Object.keys(record).length === 0) return false;
    if (detailsRedundantWithMessage(record, props.event.message)) return false;
    return true;
  };

  const hhmm = () => {
    const d = new Date(props.event.timestamp);
    const fmt = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: settingsCtx.timezone() || "UTC",
      hour12: !settingsCtx.use24hTime(),
    });
    return fmt.format(d);
  };

  return (
    <div
      id={`activity-event-${props.event.id}`}
      class="border-t border-theme-border first:border-0"
    >
      <div
        class="flex items-start gap-2 py-1.5 text-xs cursor-default"
        tabIndex={hasDetails() ? 0 : undefined}
        role={hasDetails() ? "button" : undefined}
        aria-expanded={hasDetails() ? expanded() : undefined}
        onKeyDown={(e) => {
          if (hasDetails() && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setExpanded((v) => !v);
          }
        }}
        onClick={() => {
          if (hasDetails()) setExpanded((v) => !v);
        }}
      >
        <span class="text-theme-text-secondary flex-shrink-0 w-[3rem] tabular-nums">
          {hhmm()}
        </span>
        <span
          class={`flex-shrink-0 w-4 text-center ${SEVERITY_CLASS[props.event.severity]}`}
          title={props.event.severity}
        >
          {SEVERITY_ICON[props.event.severity]}
        </span>
        <span class="flex-shrink-0 w-[3.5rem] text-theme-text-secondary truncate">
          {CATEGORY_LABELS[props.event.category]}
        </span>
        <span class="flex-1 text-theme-text-primary min-w-0">
          <Show
            when={props.event.target_id !== null}
            fallback={<span>{props.event.message}</span>}
          >
            <TargetLinkedMessage event={props.event} />
          </Show>
        </span>
        <Show when={hasDetails()}>
          <span
            class={`flex-shrink-0 text-theme-text-secondary transition-transform ${
              expanded() ? "rotate-90" : ""
            }`}
          >
            {"\u203A"}
          </span>
        </Show>
      </div>
      <div class={`grid transition-[grid-template-rows] duration-200 ${expanded() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div class="overflow-hidden">
          <Show when={hasDetails()}>
            <div class="pb-2 pl-[7rem]">
              <RowDetails event={props.event} />
            </div>
          </Show>
        </div>
      </div>
    </div>
  );
};

const FilterPill: Component<{
  label: string;
  active: boolean;
  onClick: () => void;
}> = (props) => (
  <button
    onClick={props.onClick}
    class={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
      props.active
        ? "bg-[var(--color-accent)]/20 text-[var(--color-accent)] border-[var(--color-accent)]/40"
        : "border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-border-em"
    }`}
  >
    {props.label}
  </button>
);

const ActivityFeed: Component = () => {
  const [severityFilter, setSeverityFilter] =
    createSignal<ActivitySeverity | "all">("all");
  const [categoryFilter, setCategoryFilter] =
    createSignal<ActivityCategory | "all">("all");
  const [items, setItems] = createSignal<ActivityEvent[]>([]);
  const [nextCursor, setNextCursor] = createSignal<string | null>(null);
  const [total, setTotal] = createSignal(0);
  const [loading, setLoading] = createSignal(false);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [newCount, setNewCount] = createSignal(0);
  const [latestId, setLatestId] = createSignal<number | null>(null);
  const [isScrolledDown, setIsScrolledDown] = createSignal(false);
  let listRef: HTMLDivElement | undefined;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const buildParams = (extra: Record<string, unknown> = {}) => {
    const p: Record<string, unknown> = { limit: 50, ...extra };
    const sv = severityFilter();
    if (sv !== "all") p.severity = sv;
    const cat = categoryFilter();
    if (cat !== "all") p.category = cat;
    return p;
  };

  const loadInitial = async () => {
    setLoading(true);
    try {
      const res = await api.fetchActivity(buildParams());
      batch(() => {
        setItems(res.items);
        setNextCursor(res.next_cursor);
        setTotal(res.total);
        setNewCount(0);
        if (res.items.length > 0) setLatestId(res.items[0].id);
      });
    } catch { /* non-blocking */ } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    const cursor = nextCursor();
    if (!cursor || loadingMore()) return;
    setLoadingMore(true);
    try {
      const res = await api.fetchActivity(buildParams({ cursor }));
      batch(() => {
        setItems((prev) => [...prev, ...res.items]);
        setNextCursor(res.next_cursor);
      });
    } catch { /* ignore */ } finally {
      setLoadingMore(false);
    }
  };

  const pollNew = async () => {
    const top = latestId();
    if (top === null) { await loadInitial(); return; }
    try {
      const res = await api.fetchActivity(buildParams({ limit: 50 }));
      if (res.items.length === 0) return;
      const newItems = res.items.filter((e) => e.id > top);
      if (newItems.length === 0) return;
      if (isScrolledDown()) {
        setNewCount((n) => n + newItems.length);
      } else {
        batch(() => {
          setItems((prev) => [...newItems, ...prev]);
          setLatestId(newItems[0].id);
          setTotal(res.total);
        });
      }
    } catch { /* ignore */ }
  };

  onMount(() => {
    loadInitial();
    pollTimer = setInterval(pollNew, 10_000);
  });

  onCleanup(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  createEffect(() => {
    severityFilter();
    categoryFilter();
    loadInitial();
  });

  const onScroll = () => {
    if (!listRef) return;
    setIsScrolledDown(listRef.scrollTop > 120);
  };

  const jumpToNew = () => {
    listRef?.scrollTo({ top: 0, behavior: "smooth" });
    setNewCount(0);
    loadInitial();
  };

  const jobs = () => activeJobs();
  const jobCount = () => jobs().length;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] flex flex-col h-full min-h-0">
      <div class="flex items-center justify-between px-4 py-3 flex-shrink-0">
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium text-sm">Activity</h3>
          <Show when={jobCount() > 0}>
            <span class="px-1.5 py-0.5 text-xs rounded-full bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/30 tabular-nums">
              {jobCount()} live
            </span>
          </Show>
        </div>
      </div>

      <Show when={hasActiveJobs()}>
        <div
          role="status"
          aria-live="polite"
          class="px-4 pb-3 border-b border-theme-border space-y-0 divide-y divide-theme-border"
          style={{ background: "var(--color-bg-subtle)" }}
        >
          <p class="text-[10px] font-semibold uppercase tracking-wider text-theme-text-secondary pb-1 pt-0.5">
            Now Running
          </p>
          <For each={jobs()}>
            {(job) => <ActiveJobRow job={job} />}
          </For>
        </div>
      </Show>

      <div class="flex flex-col flex-1 min-h-0">
        <div class="px-4 pt-3 pb-2 space-y-1.5 flex-shrink-0">
          <p class="text-[10px] font-semibold uppercase tracking-wider text-theme-text-secondary">
            History
          </p>
          <div class="flex flex-wrap gap-1">
            {(["all", "info", "warning", "error"] as const).map((sv) => (
              <FilterPill
                label={sv === "all" ? "all" : sv === "warning" ? "warn" : sv}
                active={severityFilter() === sv}
                onClick={() => setSeverityFilter(sv)}
              />
            ))}
          </div>
          <div class="flex flex-wrap gap-1">
            <FilterPill
              label="all"
              active={categoryFilter() === "all"}
              onClick={() => setCategoryFilter("all")}
            />
            <For each={ALL_CATEGORIES}>
              {(cat) => (
                <FilterPill
                  label={CATEGORY_LABELS[cat]}
                  active={categoryFilter() === cat}
                  onClick={() => setCategoryFilter(cat)}
                />
              )}
            </For>
          </div>
        </div>

        <div
          ref={listRef}
          class="flex-1 min-h-0 overflow-y-auto px-4 relative"
          onScroll={onScroll}
        >
          <Show when={newCount() > 0}>
            <div class="sticky top-2 flex justify-center z-10">
              <button
                onClick={jumpToNew}
                class="px-3 py-1 text-xs rounded-full bg-[var(--color-accent)] text-white shadow-md"
              >
                {newCount()} new, click to view
              </button>
            </div>
          </Show>

          <Show when={loading()}>
            <p class="text-xs text-theme-text-secondary py-4 text-center">Loading...</p>
          </Show>

          <Show when={!loading() && items().length === 0}>
            <p class="text-xs text-theme-text-secondary py-4">No activity recorded yet.</p>
          </Show>

          <Show when={!loading()}>
            <div class="space-y-0">
              <For each={items()}>
                {(event) => <HistoryRow event={event} />}
              </For>
            </div>

            <Show when={nextCursor() !== null}>
              <div class="py-3 text-center">
                <button
                  onClick={loadMore}
                  disabled={loadingMore()}
                  class="px-4 py-1.5 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary hover:border-theme-border-em transition-colors disabled:opacity-50"
                >
                  {loadingMore() ? "Loading..." : "Load older"}
                </button>
              </div>
            </Show>
          </Show>
        </div>
      </div>
    </div>
  );
};

export default ActivityFeed;
