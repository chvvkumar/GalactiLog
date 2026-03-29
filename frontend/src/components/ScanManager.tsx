import { Component, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { useScan } from "../store/scan";
import { useSettingsContext } from "./SettingsProvider";
import { api } from "../api/client";
import type { RebuildStatus } from "../types";
import DatabaseOverview from "./DatabaseOverview";
import ScanControls from "./ScanControls";
import ActivityFeed from "./ActivityFeed";
import MaintenanceActions from "./MaintenanceActions";
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
  const [frameFilter, setFrameFilter] = createSignal<FrameFilter>("all");
  const [dbSummary, setDbSummary] = createSignal<import("../types").DbSummary | null>(null);
  const [rebuildState, setRebuildState] = createSignal<RebuildStatus>({
    state: "idle", mode: "", message: "", started_at: null, completed_at: null, details: {},
  });
  const [autoScanEnabled, setAutoScanEnabled] = createSignal(true);
  const [autoScanInterval, setAutoScanInterval] = createSignal(240);
  let rebuildPollTimer: ReturnType<typeof setInterval> | null = null;

  // --- DB Summary ---
  const refreshDbSummary = async () => {
    try { setDbSummary(await api.getDbSummary()); } catch { /* ignore */ }
  };
  refreshDbSummary();

  createEffect(() => {
    const s = scanStatus().state;
    if (s === "complete" || s === "idle") refreshDbSummary();
  });

  // --- Frame filter sync ---
  createEffect(() => {
    const s = settings();
    if (s) {
      setFrameFilter(s.general.include_calibration ? "all" : "light_only");
      setAutoScanEnabled(s.general.auto_scan_enabled);
      setAutoScanInterval(s.general.auto_scan_interval);
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
    if (rebuildPollTimer) return;
    fetchRebuildStatus();
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
      {/* Auto-scan settings */}
      <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-4">
        <h3 class="text-sm font-medium text-theme-text-primary">Auto-scan</h3>
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
      </div>

      <DatabaseOverview summary={dbSummary()} />

      <ScanControls
        isActive={isActive()}
        stopping={stopping()}
        frameFilter={frameFilter()}
        onFrameFilterChange={setFrameFilter}
        onStartScan={() => startScan({ includeCalibration: frameFilter() === "all" })}
        onStopScan={stopScan}
      />

      <ActivityFeed
        scanStatus={scanStatus()}
        rebuildStatus={rebuildState()}
        stopping={stopping()}
        scanError={scanError()}
        onResetAndRescan={handleResetAndRescan}
        onDismissStalled={resetScan}
      />

      <MaintenanceActions
        disabled={isActive()}
        rebuildRunning={rebuildState().state === "running"}
        rebuildMode={rebuildState().mode}
        onRegenThumbnails={startRegeneration}
        onStartedAction={startRebuildPolling}
      />
    </div>
  );
};

export default ScanManager;
