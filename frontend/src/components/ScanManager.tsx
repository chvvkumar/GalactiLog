import { Component, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { useScan } from "../store/scan";
import { useSettingsContext } from "./SettingsProvider";
import { useAuth } from "./AuthProvider";
import { useStats } from "../store/stats";
import { api } from "../api/client";
import { scanFilters as scanFiltersApi } from "../api/scanFilters";
import type { RebuildStatus } from "../types";
import type { ScanFiltersResponse } from "../api/scanFilters";
import DatabaseOverview from "./DatabaseOverview";
import CaptureActivity from "./CaptureActivity";
import ScanControls from "./ScanControls";
import ActivityFeed from "./ActivityFeed";
import MaintenanceActions from "./MaintenanceActions";
import ScanFiltersPanel from "./ScanFiltersPanel";
import ScanFiltersOnboarding from "./ScanFiltersOnboarding";
import { showToast } from "./Toast";

type FrameFilter = "all" | "light_only";

const INTERVALS = [
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 480, label: "8 hours" },
  { value: 720, label: "12 hours" },
  { value: 1440, label: "24 hours" },
];

const ScanManager: Component = () => {
  const { scanStatus, scanError, isActive, stopping, startScan, startRegeneration, resetScan, stopScan, stopPolling } = useScan();
  const { settings, saveGeneral } = useSettingsContext();
  const { isAdmin } = useAuth();
  const { stats } = useStats();
  const [frameFilter, setFrameFilter] = createSignal<FrameFilter>("all");
  const [dbSummary, setDbSummary] = createSignal<import("../types").DbSummary | null>(null);
  const [rebuildState, setRebuildState] = createSignal<RebuildStatus>({
    state: "idle", mode: "", message: "", started_at: null, completed_at: null, details: {},
  });
  const [autoScanEnabled, setAutoScanEnabled] = createSignal(true);
  const [autoScanInterval, setAutoScanInterval] = createSignal(240);
  const [observerName, setObserverName] = createSignal<string | null>(null);
  const [observerLatitude, setObserverLatitude] = createSignal<number | null>(null);
  const [observerLongitude, setObserverLongitude] = createSignal<number | null>(null);
  const [scanFiltersData, setScanFiltersData] = createSignal<ScanFiltersResponse | null>(null);
  let rebuildPollTimer: ReturnType<typeof setInterval> | null = null;

  // --- Scan filters (shared between ScanFiltersPanel & ScanFiltersOnboarding) ---
  const loadScanFilters = async () => {
    try { setScanFiltersData(await scanFiltersApi.get()); } catch { /* ignore */ }
  };
  loadScanFilters();

  const onScanFiltersConfigured = () => loadScanFilters();
  window.addEventListener("scan-filters-configured", onScanFiltersConfigured);
  onCleanup(() => window.removeEventListener("scan-filters-configured", onScanFiltersConfigured));

  // --- DB Summary ---
  const refreshDbSummary = async () => {
    try { setDbSummary(await api.getDbSummary()); } catch { /* ignore */ }
  };

  // Track previous scan state to only refresh on transitions, not on every
  // signal update.  The initial value of null ensures the first effect run
  // triggers a fetch (transition from null → idle).
  let prevScanState: string | null = null;
  createEffect(() => {
    const s = scanStatus().state;
    if (s !== prevScanState) {
      const wasPrev = prevScanState;
      prevScanState = s;
      if (wasPrev === null || s === "complete" || s === "idle") refreshDbSummary();
    }
  });

  // Refresh when merges change (dismiss/merge/revert on targets tab)
  const onMergesChanged = () => refreshDbSummary();
  window.addEventListener("merges-changed", onMergesChanged);
  onCleanup(() => window.removeEventListener("merges-changed", onMergesChanged));

  // --- Frame filter sync ---
  createEffect(() => {
    const s = settings();
    if (s) {
      setFrameFilter(s.general.include_calibration ? "all" : "light_only");
      setAutoScanEnabled(s.general.auto_scan_enabled);
      setAutoScanInterval(s.general.auto_scan_interval);
      setObserverName(s.general.observer_name ?? null);
      setObserverLatitude(s.general.observer_latitude ?? null);
      setObserverLongitude(s.general.observer_longitude ?? null);
    }
  });

  const handleAutoScanToggle = async () => {
    const newVal = !autoScanEnabled();
    setAutoScanEnabled(newVal);
    const current = settings()?.general;
    if (current) {
      try {
        await saveGeneral({ ...current, auto_scan_enabled: newVal });
        showToast(newVal ? "Auto-scan enabled" : "Auto-scan disabled");
      } catch {
        setAutoScanEnabled(!newVal);
        showToast("Failed to save setting", "error");
      }
    }
  };

  const handleIntervalChange = async (value: number) => {
    const prev = autoScanInterval();
    setAutoScanInterval(value);
    const current = settings()?.general;
    if (current) {
      try {
        await saveGeneral({ ...current, auto_scan_interval: value });
        showToast("Scan interval updated");
      } catch {
        setAutoScanInterval(prev);
        showToast("Failed to save setting", "error");
      }
    }
  };

  // --- Rebuild polling ---
  const fetchRebuildStatus = async () => {
    try {
      const status = await api.getRebuildStatus();
      const prev = rebuildState().state;
      setRebuildState(status);
      if (status.state !== "running") {
        if (rebuildPollTimer) { clearInterval(rebuildPollTimer); rebuildPollTimer = null; }
        if (prev === "running" && status.state === "complete") refreshDbSummary();
      }
    } catch { /* ignore */ }
  };

  fetchRebuildStatus();

  const startRebuildPolling = () => {
    // Clear any previous timer so we can restart
    if (rebuildPollTimer) { clearInterval(rebuildPollTimer); rebuildPollTimer = null; }
    // Set optimistic running state so UI shows feedback immediately
    // (the Celery task may not have updated Redis yet)
    setRebuildState((prev) => ({
      ...prev,
      state: "running",
      message: "Starting...",
      started_at: Date.now() / 1000,
      completed_at: null,
    }));
    // Give the Celery task a moment to pick up before first poll
    setTimeout(fetchRebuildStatus, 1000);
    rebuildPollTimer = setInterval(fetchRebuildStatus, 2000);
  };

  onCleanup(() => {
    stopPolling();
    if (rebuildPollTimer) clearInterval(rebuildPollTimer);
  });

  // --- Stalled scan handling ---
  const handleResetAndRescan = async () => {
    await resetScan();
    startScan({ includeCalibration: frameFilter() === "all" });
  };

  return (
    <div class="space-y-4">
      <DatabaseOverview summary={dbSummary()} storage={stats()?.storage} />

      <Show when={stats()}>
        {(data) => <CaptureActivity history={data().ingest_history} />}
      </Show>

      <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4 items-start">
        {/* Left column: controls */}
        <div class="space-y-4 min-w-0">
          <ScanFiltersOnboarding
            configured={scanFiltersData()?.configured ?? true}
            onReview={() => {
              const el = document.getElementById("scan-filters-panel");
              if (el instanceof HTMLDetailsElement) el.open = true;
              el?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
          />
          <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
            <h3 class="text-sm font-medium text-theme-text-primary">Library Scanning</h3>

            <Show when={isAdmin()}>
              <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
                <h4 class="text-sm font-medium text-theme-text-primary">Auto-scan</h4>
                <div class="flex items-center justify-between">
                  <label class="text-sm text-theme-text-secondary">Enable automatic scanning</label>
                  <button
                    onClick={handleAutoScanToggle}
                    class={`relative w-10 h-5 rounded-full transition-colors ${
                      autoScanEnabled() ? "bg-theme-accent" : "bg-theme-text-tertiary"
                    }`}
                  >
                    <span
                      class={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                        autoScanEnabled() ? "translate-x-5" : ""
                      }`}
                    />
                  </button>
                </div>
                <Show when={autoScanEnabled()}>
                  <div class="flex items-center justify-between">
                    <label class="text-sm text-theme-text-secondary">Scan interval</label>
                    <select
                      value={autoScanInterval()}
                      onChange={(e) => handleIntervalChange(parseInt(e.currentTarget.value))}
                      class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
                    >
                      {INTERVALS.map((opt) => (
                        <option value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                </Show>
              </section>
            </Show>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h4 class="text-sm font-medium text-theme-text-primary">Observer Location</h4>
              <div class="grid grid-cols-3 gap-3">
                <div class="space-y-1">
                  <label class="text-xs text-theme-text-secondary">Name</label>
                  <input
                    type="text"
                    class="w-full px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
                    value={observerName() ?? ""}
                    onInput={(e) => setObserverName(e.currentTarget.value || null)}
                    onBlur={async () => {
                      const current = settings()?.general;
                      if (current) {
                        try {
                          await saveGeneral({ ...current, observer_name: observerName() });
                        } catch {
                          showToast("Failed to save observer location", "error");
                        }
                      }
                    }}
                  />
                </div>
                <div class="space-y-1">
                  <label class="text-xs text-theme-text-secondary">Latitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    class="w-full px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary tabular-nums focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
                    value={observerLatitude() ?? ""}
                    onInput={(e) => setObserverLatitude(e.currentTarget.value ? parseFloat(e.currentTarget.value) : null)}
                    onBlur={async () => {
                      const current = settings()?.general;
                      if (current) {
                        try {
                          await saveGeneral({ ...current, observer_latitude: observerLatitude() });
                        } catch {
                          showToast("Failed to save observer location", "error");
                        }
                      }
                    }}
                  />
                </div>
                <div class="space-y-1">
                  <label class="text-xs text-theme-text-secondary">Longitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    class="w-full px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary tabular-nums focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
                    value={observerLongitude() ?? ""}
                    onInput={(e) => setObserverLongitude(e.currentTarget.value ? parseFloat(e.currentTarget.value) : null)}
                    onBlur={async () => {
                      const current = settings()?.general;
                      if (current) {
                        try {
                          await saveGeneral({ ...current, observer_longitude: observerLongitude() });
                        } catch {
                          showToast("Failed to save observer location", "error");
                        }
                      }
                    }}
                  />
                </div>
              </div>
            </section>

            <ScanFiltersPanel initialData={scanFiltersData()} />

            <div class="flex flex-wrap items-center gap-4 justify-end pt-2 border-t border-theme-border">
              <ScanControls
                isActive={isActive()}
                stopping={stopping()}
                frameFilter={frameFilter()}
                onFrameFilterChange={setFrameFilter}
                onStartScan={() => startScan({ includeCalibration: frameFilter() === "all" })}
                onStopScan={stopScan}
              />
            </div>
          </div>

          <Show when={isAdmin()}>
            <MaintenanceActions
              disabled={isActive()}
              rebuildRunning={rebuildState().state === "running"}
              rebuildMode={rebuildState().mode}
              onRegenThumbnails={startRegeneration}
              onStartedAction={startRebuildPolling}
            />
          </Show>
        </div>

        {/* Right column: sticky activity feed */}
        <div class="lg:sticky lg:top-4 lg:self-start min-w-0">
          <div class="lg:max-h-[calc(100vh-2rem)] lg:overflow-hidden lg:flex lg:flex-col">
            <ActivityFeed
              scanStatus={scanStatus()}
              rebuildStatus={rebuildState()}
              stopping={stopping()}
              scanError={scanError()}
              onResetAndRescan={handleResetAndRescan}
              onDismissStalled={resetScan}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default ScanManager;
