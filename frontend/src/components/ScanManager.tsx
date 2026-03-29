import { Component, createSignal, createEffect, onCleanup } from "solid-js";
import { useScan } from "../store/scan";
import { useSettingsContext } from "./SettingsProvider";
import { api } from "../api/client";
import type { RebuildStatus } from "../types";
import DatabaseOverview from "./DatabaseOverview";
import ScanControls from "./ScanControls";
import ActivityFeed from "./ActivityFeed";
import MaintenanceActions from "./MaintenanceActions";

type FrameFilter = "all" | "light_only";

const ScanManager: Component = () => {
  const { scanStatus, scanError, isActive, stopping, startScan, startRegeneration, resetScan, stopScan, stopPolling } = useScan();
  const { settings } = useSettingsContext();
  const [frameFilter, setFrameFilter] = createSignal<FrameFilter>("all");
  const [dbSummary, setDbSummary] = createSignal<import("../types").DbSummary | null>(null);
  const [rebuildState, setRebuildState] = createSignal<RebuildStatus>({
    state: "idle", mode: "", message: "", started_at: null, completed_at: null, details: {},
  });
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
    }
  });

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
