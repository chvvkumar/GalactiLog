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
import HelpPopover from "../HelpPopover";

const LEVELS: AppLogLevel[] = ["debug", "info", "warning", "error", "critical"];
const CAPTURE_LEVELS: AppLogLevel[] = ["debug", "info", "warning", "error"];
const SOURCES: ("all" | AppLogSource)[] = ["all", "api", "worker", "beat"];

// Shared style for the action buttons in the settings strip (Save, Clear, Download).
const ACTION_BTN_CLASS =
  "px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm disabled:opacity-50 hover:bg-theme-accent/25 transition-colors";

// Severity ranking, low to high. Drives the minimum-severity view filter.
const LEVEL_ORDER: Record<AppLogLevel, number> = {
  debug: 10,
  info: 20,
  warning: 30,
  error: 40,
  critical: 50,
};

// localStorage keys so the view filter persists across reloads.
const LS_MIN_LEVEL = "galactilog.applog.minLevel";
const LS_SOURCE = "galactilog.applog.source";

// Severity text color, shared by the level column and the level selector so the
// two stay consistent.
const levelTextClass = (level: AppLogLevel): string => {
  switch (level) {
    case "critical":
      return "text-theme-error font-semibold";
    case "error":
      return "text-theme-error";
    case "warning":
      return "text-theme-warning";
    case "info":
      return "text-theme-info";
    default:
      return "text-theme-text-secondary";
  }
};

// Filled style for an active (included) level pill, tinted by severity.
const levelActiveClass = (level: AppLogLevel): string => {
  switch (level) {
    case "error":
    case "critical":
      return "bg-theme-error/20 border-theme-error/50 text-theme-error";
    case "warning":
      return "bg-theme-warning/20 border-theme-warning/50 text-theme-warning";
    case "info":
      return "bg-theme-info/20 border-theme-info/50 text-theme-info";
    default:
      return "bg-theme-text-primary/10 border-theme-border-em text-theme-text-primary";
  }
};

const LevelPill: Component<{
  level: AppLogLevel;
  active: boolean;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
}> = (props) => (
  <button
    type="button"
    onClick={props.onClick}
    disabled={props.disabled}
    title={props.title}
    class={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
      props.disabled
        ? "border-theme-border text-theme-text-tertiary opacity-40 cursor-not-allowed"
        : props.active
          ? levelActiveClass(props.level)
          : `border-theme-border opacity-60 hover:opacity-100 ${levelTextClass(props.level)}`
    }`}
  >
    {props.level}
  </button>
);

const LevelBadge: Component<{ level: AppLogLevel }> = (props) => (
  <span class={`flex-shrink-0 w-[4rem] uppercase ${levelTextClass(props.level)}`}>
    {props.level}
  </span>
);

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

  // Log viewer state. Minimum-severity threshold + source persist across reload.
  const [minLevel, setMinLevel] = createSignal<AppLogLevel>(
    (() => {
      try {
        const v = localStorage.getItem(LS_MIN_LEVEL);
        return v && v in LEVEL_ORDER ? (v as AppLogLevel) : "debug";
      } catch {
        return "debug";
      }
    })(),
  );
  const [source, setSource] = createSignal<"all" | AppLogSource>(
    (() => {
      try {
        const v = localStorage.getItem(LS_SOURCE);
        return v === "api" || v === "worker" || v === "beat" ? v : "all";
      } catch {
        return "all";
      }
    })(),
  );
  const [searchInput, setSearchInput] = createSignal("");
  const [search, setSearch] = createSignal("");
  const [logs, setLogs] = createSignal<AppLogItem[]>([]);
  const [nextCursor, setNextCursor] = createSignal<string | null>(null);
  const [total, setTotal] = createSignal(0);
  const [loadingLogs, setLoadingLogs] = createSignal(false);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [expanded, setExpanded] = createSignal<Set<number>>(new Set());
  const [liveTail, setLiveTail] = createSignal(true);

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

  // The capture level bounds what is recorded; the view filter can only narrow to
  // that level or above, since nothing below it exists. Effective minimum is the
  // higher of the view filter and the capture level.
  const captureOrder = () => LEVEL_ORDER[captureLevel()];
  const effectiveMinOrder = () =>
    Math.max(LEVEL_ORDER[minLevel()], captureOrder());

  const buildParams = (extra: Partial<LogQueryParams> = {}): LogQueryParams => {
    const p: LogQueryParams = { limit: 50, ...extra };
    // Minimum-severity filter: include the selected level and everything above
    // it. Omit the param entirely when showing everything (debug and above).
    const threshold = effectiveMinOrder();
    const included = LEVELS.filter((l) => LEVEL_ORDER[l] >= threshold);
    if (included.length < LEVELS.length) p.level = included;
    if (source() !== "all") p.source = source() as AppLogSource;
    if (search().trim()) p.q = search().trim();
    return p;
  };

  // Reactive so the href tracks the current level/source/search filters
  const downloadUrl = () => api.logsDownloadUrl(buildParams());

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
        setTotal(res.total);
      });
    } catch {
      /* ignore */
    } finally {
      setLoadingMore(false);
    }
  };

  // Reload when filters change. captureLevel() participates because it raises the
  // effective minimum severity and changes which levels exist.
  createEffect(() => {
    minLevel();
    captureLevel();
    source();
    search();
    loadInitial();
  });

  // Persist the view filter so it survives a page reload.
  createEffect(() => {
    try {
      localStorage.setItem(LS_MIN_LEVEL, minLevel());
      localStorage.setItem(LS_SOURCE, source());
    } catch {
      /* ignore */
    }
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
              // res.total here is filtered by `since` (only the new rows), so
              // add them to the running total instead of overwriting it.
              setTotal((t) => t + res.items.length);
            });
          }
        } catch {
          /* ignore */
        }
      }, 5000);
      onCleanup(() => {
        if (timer) {
          clearInterval(timer);
          timer = undefined;
        }
      });
    }
  });

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
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium">Application Log</h3>
          <HelpPopover title="Application Log">
            <p>Captures the backend's own log records (from the web, worker, and scheduler processes) into the database so they survive restarts and can be filtered, searched, and downloaded here.</p>
            <p><strong>Capture level</strong> sets the minimum severity that gets recorded. Leave it at <em>warning</em> for normal use; switch to <em>info</em> or <em>debug</em> to collect detailed logs while troubleshooting, then turn it back down. It takes effect within a few seconds, no restart needed.</p>
            <p><strong>Activity retention</strong> is how long activity events (scans, merges, enrichment) are kept. <strong>Log retention</strong> and <strong>Log max rows</strong> bound the application log: the nightly pruner deletes records older than the retention or beyond the row cap, whichever comes first.</p>
            <p><strong>Clear activity log</strong> and <strong>Clear application logs</strong> permanently delete those tables. <strong>Download</strong> exports the currently filtered log view as a plain-text file for sharing in a bug report.</p>
          </HelpPopover>
        </div>

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
                class={ACTION_BTN_CLASS}
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
                    class={ACTION_BTN_CLASS}
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
                    class={ACTION_BTN_CLASS}
                  >
                    Clear application logs
                  </button>
                </Show>

                <a href={downloadUrl()} class={ACTION_BTN_CLASS}>
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
            <div class="flex items-center gap-2">
              <span class="text-xs text-theme-text-secondary tabular-nums">
                {total()} {total() === 1 ? "entry" : "entries"}
              </span>
              <HelpPopover title="Log viewer">
                <p>Shows recorded log entries, newest first, with a color-coded severity column: debug (gray), info (blue), warning (amber), error and critical (red).</p>
                <p>The <strong>level pills</strong> filter by minimum severity: pick a level to show it and everything more severe (for example, <em>warning</em> shows warning, error, and critical). The selected level and those above it are highlighted, and the choice persists across reloads.</p>
                <p>Use the <strong>source</strong> dropdown to limit to the web (api), worker, or scheduler (beat) process, and the <strong>search</strong> box to match message text. Rows with a traceback expand when clicked.</p>
                <p><strong>Live tail</strong> polls for new entries every few seconds and prepends them. This filters what is displayed, not what is recorded; the capture level above controls recording.</p>
              </HelpPopover>
            </div>
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
                {(lvl) => {
                  const isDisabled = () => LEVEL_ORDER[lvl] < captureOrder();
                  return (
                    <LevelPill
                      level={lvl}
                      active={LEVEL_ORDER[lvl] >= effectiveMinOrder()}
                      disabled={isDisabled()}
                      title={
                        isDisabled()
                          ? `No ${lvl} logs are recorded while the Capture level is "${captureLevel()}". Lower the Capture level (top of this card) to record and view ${lvl} entries.`
                          : "Filter: show this level and above"
                      }
                      onClick={() => setMinLevel(lvl)}
                    />
                  );
                }}
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
