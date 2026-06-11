import {
  Component,
  For,
  Show,
  batch,
  createEffect,
  createSignal,
  onCleanup,
  onMount,
} from "solid-js";
import {
  api,
  type AppLogItem,
  type AppLogLevel,
  type AppLogSource,
  type LogQueryParams,
} from "../../api/client";
import { useAuth } from "../AuthProvider";
import { showToast } from "../Toast";

const LEVELS: AppLogLevel[] = ["debug", "info", "warning", "error", "critical"];
const CAPTURE_LEVELS: AppLogLevel[] = ["debug", "info", "warning", "error"];
const SOURCES: ("all" | AppLogSource)[] = ["all", "api", "worker", "beat"];

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

const LevelBadge: Component<{ level: AppLogLevel }> = (props) => {
  const cls = () => {
    switch (props.level) {
      case "error":
      case "critical":
        return "text-theme-error";
      case "warning":
        return "text-theme-warning";
      default:
        return "text-theme-text-secondary";
    }
  };
  return (
    <span class={`flex-shrink-0 w-[4rem] uppercase ${cls()}`}>{props.level}</span>
  );
};

const ActivityLogTab: Component = () => {
  const { isAdmin } = useAuth();

  // Settings strip state
  const [retentionDays, setRetentionDays] = createSignal(90);
  const [captureLevel, setCaptureLevel] = createSignal<AppLogLevel>("warning");
  const [logRetentionDays, setLogRetentionDays] = createSignal(14);
  const [logMaxRows, setLogMaxRows] = createSignal(50000);
  const [savingSettings, setSavingSettings] = createSignal(false);
  const [settingsLoaded, setSettingsLoaded] = createSignal(false);

  // Clear confirmations
  const [clearingActivity, setClearingActivity] = createSignal(false);
  const [showClearActivityConfirm, setShowClearActivityConfirm] =
    createSignal(false);
  const [clearingLogs, setClearingLogs] = createSignal(false);
  const [showClearLogsConfirm, setShowClearLogsConfirm] = createSignal(false);

  // Log viewer state
  const [levels, setLevels] = createSignal<AppLogLevel[]>([]);
  const [source, setSource] = createSignal<"all" | AppLogSource>("all");
  const [searchInput, setSearchInput] = createSignal("");
  const [search, setSearch] = createSignal("");
  const [logs, setLogs] = createSignal<AppLogItem[]>([]);
  const [nextCursor, setNextCursor] = createSignal<string | null>(null);
  const [total, setTotal] = createSignal(0);
  const [loadingLogs, setLoadingLogs] = createSignal(false);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [expanded, setExpanded] = createSignal<Set<number>>(new Set());
  const [liveTail, setLiveTail] = createSignal(false);

  onMount(async () => {
    try {
      const s = await api.getActivitySettings();
      batch(() => {
        setRetentionDays(s.activity_retention_days);
        setCaptureLevel(s.app_log_capture_level);
        setLogRetentionDays(s.app_log_retention_days);
        setLogMaxRows(s.app_log_max_rows);
      });
    } catch {
      /* ignore */
    } finally {
      setSettingsLoaded(true);
    }
  });

  // Debounce the search input into `search` (~300ms)
  createEffect(() => {
    const value = searchInput();
    const handle = setTimeout(() => setSearch(value), 300);
    onCleanup(() => clearTimeout(handle));
  });

  const buildParams = (extra: Partial<LogQueryParams> = {}): LogQueryParams => {
    const p: LogQueryParams = { limit: 50, ...extra };
    if (levels().length) p.level = levels();
    if (source() !== "all") p.source = source() as AppLogSource;
    if (search().trim()) p.q = search().trim();
    return p;
  };

  const loadInitial = async () => {
    setLoadingLogs(true);
    try {
      const res = await api.fetchLogs(buildParams());
      batch(() => {
        setLogs(res.items);
        setNextCursor(res.next_cursor);
        setTotal(res.total);
      });
    } catch {
      /* non-blocking */
    } finally {
      setLoadingLogs(false);
    }
  };

  const loadMore = async () => {
    const cur = nextCursor();
    if (!cur || loadingMore()) return;
    setLoadingMore(true);
    try {
      const res = await api.fetchLogs(buildParams({ cursor: cur }));
      batch(() => {
        setLogs((prev) => [...prev, ...res.items]);
        setNextCursor(res.next_cursor);
      });
    } catch {
      /* ignore */
    } finally {
      setLoadingMore(false);
    }
  };

  // Reload when filters change
  createEffect(() => {
    levels();
    source();
    search();
    loadInitial();
  });

  // Live tail: poll for rows newer than the newest loaded
  let timer: ReturnType<typeof setInterval> | undefined;
  createEffect(() => {
    if (timer) {
      clearInterval(timer);
      timer = undefined;
    }
    if (liveTail()) {
      timer = setInterval(async () => {
        const newest = logs()[0]?.timestamp;
        if (!newest) {
          await loadInitial();
          return;
        }
        try {
          const res = await api.fetchLogs(buildParams({ since: newest, limit: 100 }));
          if (res.items.length) {
            batch(() => {
              setLogs((prev) => [...res.items, ...prev]);
              setTotal(res.total);
            });
          }
        } catch {
          /* ignore */
        }
      }, 5000);
    }
  });
  onCleanup(() => {
    if (timer) clearInterval(timer);
  });

  const toggleLevel = (level: AppLogLevel) => {
    setLevels((prev) =>
      prev.includes(level)
        ? prev.filter((l) => l !== level)
        : [...prev, level],
    );
  };

  const toggleExpanded = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCaptureLevelChange = async (level: AppLogLevel) => {
    if (!isAdmin()) return;
    const previous = captureLevel();
    setCaptureLevel(level);
    try {
      const res = await api.setActivitySettings({ app_log_capture_level: level });
      setCaptureLevel(res.app_log_capture_level);
      showToast(`Capture level set to ${level}`, "success", 3000);
    } catch {
      setCaptureLevel(previous);
      showToast("Failed to update capture level", "error", 0);
    }
  };

  const handleSaveSettings = async () => {
    if (savingSettings() || !isAdmin()) return;
    setSavingSettings(true);
    try {
      const res = await api.setActivitySettings({
        retention_days: retentionDays(),
        app_log_retention_days: logRetentionDays(),
        app_log_max_rows: logMaxRows(),
      });
      batch(() => {
        setRetentionDays(res.activity_retention_days);
        setLogRetentionDays(res.app_log_retention_days);
        setLogMaxRows(res.app_log_max_rows);
      });
      showToast("Retention settings saved", "success", 3000);
    } catch {
      showToast("Failed to save retention settings", "error", 0);
    } finally {
      setSavingSettings(false);
    }
  };

  const handleClearActivity = async () => {
    if (clearingActivity()) return;
    setShowClearActivityConfirm(false);
    setClearingActivity(true);
    try {
      await api.clearActivityLog();
      showToast("Activity log cleared", "success", 3000);
    } catch {
      showToast("Failed to clear activity log", "error", 0);
    } finally {
      setClearingActivity(false);
    }
  };

  const handleClearLogs = async () => {
    if (clearingLogs()) return;
    setShowClearLogsConfirm(false);
    setClearingLogs(true);
    try {
      await api.clearLogs();
      batch(() => {
        setLogs([]);
        setNextCursor(null);
        setTotal(0);
      });
      showToast("Application logs cleared", "success", 3000);
    } catch {
      showToast("Failed to clear application logs", "error", 0);
    } finally {
      setClearingLogs(false);
    }
  };

  return (
    <div class="space-y-4">
      {/* Settings strip */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-4">
        <h3 class="text-theme-text-primary font-medium">Application Log</h3>

        <Show when={settingsLoaded()} fallback={
          <p class="text-xs text-theme-text-secondary">Loading...</p>
        }>
          <div class="space-y-3">
            <div class="flex flex-wrap items-end gap-4">
              <div class="space-y-1">
                <label class="block text-xs text-theme-text-secondary">
                  Capture level
                </label>
                <select
                  value={captureLevel()}
                  disabled={!isAdmin()}
                  onChange={(e) =>
                    handleCaptureLevelChange(e.currentTarget.value as AppLogLevel)
                  }
                  class="px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent disabled:opacity-50"
                >
                  <For each={CAPTURE_LEVELS}>
                    {(lvl) => <option value={lvl}>{lvl}</option>}
                  </For>
                </select>
              </div>

              <div class="space-y-1">
                <label class="block text-xs text-theme-text-secondary">
                  Activity retention (days)
                </label>
                <input
                  type="number"
                  min={1}
                  max={3650}
                  value={retentionDays()}
                  disabled={!isAdmin()}
                  onInput={(e) => {
                    const v = parseInt(e.currentTarget.value, 10);
                    if (!isNaN(v) && v >= 1 && v <= 3650) setRetentionDays(v);
                  }}
                  class="w-24 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent tabular-nums disabled:opacity-50"
                />
              </div>

              <div class="space-y-1">
                <label class="block text-xs text-theme-text-secondary">
                  Log retention (days)
                </label>
                <input
                  type="number"
                  min={1}
                  max={3650}
                  value={logRetentionDays()}
                  disabled={!isAdmin()}
                  onInput={(e) => {
                    const v = parseInt(e.currentTarget.value, 10);
                    if (!isNaN(v) && v >= 1 && v <= 3650) setLogRetentionDays(v);
                  }}
                  class="w-24 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent tabular-nums disabled:opacity-50"
                />
              </div>

              <div class="space-y-1">
                <label class="block text-xs text-theme-text-secondary">
                  Log max rows
                </label>
                <input
                  type="number"
                  min={1000}
                  step={1000}
                  value={logMaxRows()}
                  disabled={!isAdmin()}
                  onInput={(e) => {
                    const v = parseInt(e.currentTarget.value, 10);
                    if (!isNaN(v) && v >= 1000) setLogMaxRows(v);
                  }}
                  class="w-28 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent tabular-nums disabled:opacity-50"
                />
              </div>

              <button
                onClick={handleSaveSettings}
                disabled={savingSettings() || !isAdmin()}
                class="px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
              >
                {savingSettings() ? "Saving..." : "Save"}
              </button>
            </div>

            <p class="text-xs text-theme-text-secondary">
              The nightly pruner deletes activity events older than the activity
              retention, and application logs older than the log retention or beyond
              the max-row cap. Capture level controls the minimum severity recorded.
            </p>

            <Show when={isAdmin()}>
              <div class="flex flex-wrap items-center gap-2 border-t border-theme-border pt-3">
                {/* Clear activity log */}
                <Show
                  when={!showClearActivityConfirm()}
                  fallback={
                    <div class="flex items-center gap-1.5">
                      <span class="text-xs text-theme-error">Clear activity log?</span>
                      <button
                        onClick={handleClearActivity}
                        class="px-2 py-1 text-xs bg-theme-error text-theme-text-primary rounded hover:opacity-90 transition-colors"
                      >
                        Yes
                      </button>
                      <button
                        onClick={() => setShowClearActivityConfirm(false)}
                        class="px-2 py-1 text-xs border border-theme-border-em text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  }
                >
                  <button
                    onClick={() => setShowClearActivityConfirm(true)}
                    disabled={clearingActivity()}
                    class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 transition-colors"
                  >
                    Clear activity log
                  </button>
                </Show>

                {/* Clear application logs */}
                <Show
                  when={!showClearLogsConfirm()}
                  fallback={
                    <div class="flex items-center gap-1.5">
                      <span class="text-xs text-theme-error">Clear application logs?</span>
                      <button
                        onClick={handleClearLogs}
                        class="px-2 py-1 text-xs bg-theme-error text-theme-text-primary rounded hover:opacity-90 transition-colors"
                      >
                        Yes
                      </button>
                      <button
                        onClick={() => setShowClearLogsConfirm(false)}
                        class="px-2 py-1 text-xs border border-theme-border-em text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  }
                >
                  <button
                    onClick={() => setShowClearLogsConfirm(true)}
                    disabled={clearingLogs()}
                    class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 transition-colors"
                  >
                    Clear application logs
                  </button>
                </Show>

                <a
                  href={api.logsDownloadUrl(buildParams())}
                  class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm hover:text-theme-text-primary hover:border-theme-accent transition-colors"
                >
                  Download
                </a>
              </div>
            </Show>
          </div>
        </Show>
      </div>

      {/* Log viewer */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)]">
        <div class="px-4 py-3 space-y-3 border-b border-theme-border">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs text-theme-text-secondary tabular-nums">
              {total()} {total() === 1 ? "entry" : "entries"}
            </span>
            <label class="flex items-center gap-2 text-xs text-theme-text-secondary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={liveTail()}
                onChange={(e) => setLiveTail(e.currentTarget.checked)}
                class="accent-[var(--color-accent)]"
              />
              Live tail
            </label>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <div class="flex flex-wrap gap-1">
              <For each={LEVELS}>
                {(lvl) => (
                  <FilterPill
                    label={lvl}
                    active={levels().includes(lvl)}
                    onClick={() => toggleLevel(lvl)}
                  />
                )}
              </For>
            </div>

            <select
              value={source()}
              onChange={(e) =>
                setSource(e.currentTarget.value as "all" | AppLogSource)
              }
              class="px-2 py-1 text-xs bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent"
            >
              <For each={SOURCES}>
                {(src) => <option value={src}>{src}</option>}
              </For>
            </select>

            <input
              type="text"
              value={searchInput()}
              onInput={(e) => setSearchInput(e.currentTarget.value)}
              placeholder="Search messages..."
              class="flex-1 min-w-[12rem] px-2 py-1 text-xs bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent"
            />
          </div>
        </div>

        <div class="max-h-[32rem] overflow-y-auto">
          <Show when={loadingLogs() && logs().length === 0}>
            <p class="text-xs text-theme-text-secondary py-6 text-center">
              Loading...
            </p>
          </Show>

          <Show when={!loadingLogs() && logs().length === 0}>
            <p class="text-xs text-theme-text-secondary py-6 text-center">
              No log entries match the current filters.
            </p>
          </Show>

          <For each={logs()}>
            {(row) => (
              <div
                class={`px-3 py-1.5 border-b border-theme-border text-xs font-mono ${
                  row.traceback ? "cursor-pointer hover:bg-theme-base/40" : ""
                }`}
                onClick={() => row.traceback && toggleExpanded(row.id)}
              >
                <div class="flex gap-2 items-baseline">
                  <span class="text-theme-text-secondary tabular-nums whitespace-nowrap flex-shrink-0">
                    {new Date(row.timestamp).toLocaleString()}
                  </span>
                  <LevelBadge level={row.level} />
                  <span class="text-theme-text-secondary flex-shrink-0 w-[3.5rem]">
                    {row.source}
                  </span>
                  <span class="text-theme-text-secondary truncate max-w-[12rem] flex-shrink-0">
                    {row.logger}
                  </span>
                  <span class="text-theme-text-primary flex-1 break-all">
                    {row.message}
                  </span>
                  <Show when={row.traceback}>
                    <span class="text-theme-accent flex-shrink-0">
                      {expanded().has(row.id) ? "−" : "+"}
                    </span>
                  </Show>
                </div>
                <Show when={row.traceback && expanded().has(row.id)}>
                  <pre class="mt-1 p-2 bg-theme-base rounded text-[11px] overflow-x-auto whitespace-pre">
                    {row.traceback}
                  </pre>
                </Show>
              </div>
            )}
          </For>

          <Show when={nextCursor()}>
            <button
              onClick={loadMore}
              disabled={loadingMore()}
              class="w-full py-2 text-xs text-theme-accent hover:underline disabled:opacity-50"
            >
              {loadingMore() ? "Loading..." : "Load more"}
            </button>
          </Show>
        </div>
      </div>
    </div>
  );
};

export default ActivityLogTab;
