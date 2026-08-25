import { Component, createSignal, createEffect, onCleanup, onMount, For, Show } from "solid-js";
import { useScan } from "../store/scan";
import { useSettingsContext } from "./SettingsProvider";
import { useAuth } from "./AuthProvider";
import { useStats } from "../store/stats";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { scanFilters as scanFiltersApi } from "../api/scanFilters";
import type { DbSummary } from "../api/types";
import type { ScanFiltersResponse } from "../api/scanFilters";
import DatabaseOverview from "./DatabaseOverview";
import CaptureActivity from "./CaptureActivity";
import ScanControls from "./ScanControls";
import ConfirmDialog from "./ConfirmDialog";
import ActivityFeed from "./ActivityFeed";
import MaintenanceActions from "./MaintenanceActions";
import ScanFiltersPanel from "./ScanFiltersPanel";
import ScanFiltersOnboarding from "./ScanFiltersOnboarding";
import { showToast } from "./Toast";
import HelpPopover from "./HelpPopover";
import { rebuildStatus, fetchRebuildStatus } from "../store/rebuild";
import { isValidTimeZone, supportedTimeZones, timezoneFriendlyName } from "../utils/dateTime";

type FrameFilter = "all" | "light_only";

const INTERVALS = [
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 360, label: "6 hours" },
  { value: 480, label: "8 hours" },
  { value: 720, label: "12 hours" },
  { value: 1440, label: "24 hours" },
];

const ScanManager: Component = () => {
  const { scanStatus, isActive, stopping, startScan, startRegeneration, stopScan, stopPolling } = useScan();
  const { settings, saveGeneral, openSetupWizard } = useSettingsContext();
  const { isAdmin } = useAuth();
  const { stats } = useStats();
  const [frameFilter, setFrameFilter] = createSignal<FrameFilter>("all");
  // One-time force orphan cleanup. Not persisted; resets each render/session.
  const [forceOrphanCleanup, setForceOrphanCleanup] = createSignal(false);
  const [forceCleanupConfirmOpen, setForceCleanupConfirmOpen] = createSignal(false);
  const [dbSummary, setDbSummary] = createSignal<DbSummary | null>(null);
  const rebuildState = rebuildStatus;
  const [autoScanEnabled, setAutoScanEnabled] = createSignal(true);
  const [autoScanInterval, setAutoScanInterval] = createSignal(240);
  const [observerName, setObserverName] = createSignal<string | null>(null);
  const [observerLatitude, setObserverLatitude] = createSignal<number | null>(null);
  const [observerLongitude, setObserverLongitude] = createSignal<number | null>(null);
  const [latError, setLatError] = createSignal<string | null>(null);
  const [lngError, setLngError] = createSignal<string | null>(null);
  const [observerTimezone, setObserverTimezone] = createSignal<string>("");
  const [tzError, setTzError] = createSignal<string | null>(null);
  const [phd2ScanEnabled, setPhd2ScanEnabled] = createSignal(true);
  const [scanFiltersData, setScanFiltersData] = createSignal<ScanFiltersResponse | null>(null);

  // --- Scan filters (shared between ScanFiltersPanel & ScanFiltersOnboarding) ---
  const loadScanFilters = async () => {
    try { setScanFiltersData(await scanFiltersApi.get()); } catch { /* ignore */ }
  };
  loadScanFilters();

  const onScanFiltersConfigured = () => loadScanFilters();
  onMount(() => window.addEventListener("scan-filters-configured", onScanFiltersConfigured));
  onCleanup(() => window.removeEventListener("scan-filters-configured", onScanFiltersConfigured));

  // --- DB Summary ---
  const refreshDbSummary = async () => {
    try { setDbSummary(await apiClient.GET("/api/scan/db-summary").then(unwrap)); } catch { /* ignore */ }
  };

  // Track previous composite state (scan + rebuild) to only fetch db summary
  // on real transitions. Starting with null ensures the first effect run
  // triggers the initial fetch.
  let prevCompositeState: string | null = null;
  createEffect(() => {
    const scanState = scanStatus().state;
    const rebuildSt = rebuildState().state;
    const current = `${scanState}:${rebuildSt}`;
    if (current !== prevCompositeState) {
      const wasPrev = prevCompositeState;
      prevCompositeState = current;
      if (wasPrev === null || scanState === "complete" || scanState === "idle") {
        refreshDbSummary();
      }
    }
  });

  // Refresh when merges change (dismiss/merge/revert on targets tab)
  const onMergesChanged = () => refreshDbSummary();
  onMount(() => window.addEventListener("merges-changed", onMergesChanged));
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
      setObserverTimezone(s.general.observer_timezone ?? "");
      setPhd2ScanEnabled(s.general.phd2_scan_enabled ?? true);
      // Clear validation errors when settings are refreshed from the server
      setLatError(null);
      setLngError(null);
      setTzError(null);
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

  // Same optimistic-signal + rollback shape as handleAutoScanToggle: flip
  // locally, persist, and restore the previous value if the save fails.
  const handlePhd2ScanToggle = async () => {
    const newVal = !phd2ScanEnabled();
    setPhd2ScanEnabled(newVal);
    const current = settings()?.general;
    if (current) {
      try {
        await saveGeneral({ ...current, phd2_scan_enabled: newVal });
        showToast(newVal ? "PHD2 guide log scanning enabled" : "PHD2 guide log scanning disabled");
      } catch {
        setPhd2ScanEnabled(!newVal);
        showToast("Failed to save setting", "error");
      }
    }
  };

  // Read once per mount rather than per render: the answer cannot change
  // while the page is open, and a null means this runtime cannot enumerate
  // zones, so the field degrades to free text instead of an empty dropdown.
  const timezoneList = supportedTimeZones();

  // The zone chosen on the Display tab, read from where that tab stores it
  // rather than copying its shortlist. Offered as a convenience entry whose
  // VALUE is the real IANA name, so picking it stores a zone the backend can
  // load rather than a sentinel that would need interpreting later.
  const displayTimezone = () => settings()?.general.timezone ?? "";
  const displayTimezoneOption = () => {
    const tz = displayTimezone();
    if (!tz) return null;
    const friendly = timezoneFriendlyName(tz);
    return {
      value: tz,
      label: friendly === tz ? `Same as display timezone (${tz})` : `Same as display timezone (${friendly} - ${tz})`,
    };
  };

  // A stored zone this runtime does not list (an older value, or a name only
  // Python's zoneinfo knows) still has to be visible. Without its own option
  // the select would fall back to showing the placeholder, which reads as
  // "not configured" while the server holds a value and applies it.
  const unlistedTimezone = () => {
    const current = observerTimezone();
    if (!current || current === displayTimezone()) return null;
    return timezoneList && timezoneList.includes(current) ? null : current;
  };

  const saveObserverTimezone = async (value: string) => {
    const current = settings()?.general;
    if (!current) return;
    const previous = observerTimezone();
    setObserverTimezone(value);
    setTzError(null);
    try {
      // Empty string is the stored form of "not configured". The backend
      // declares observer_timezone as a non-nullable str, so sending null for
      // a cleared field would fail validation with a 422, and its correlation
      // guard reads the empty string as a zone nobody picked and declines to
      // date guide-log rows rather than guessing.
      await saveGeneral({ ...current, observer_timezone: value });
    } catch (err) {
      // The browser's Intl database accepts names Python's zoneinfo rejects,
      // so the backend gets the last word. Show what it said instead of
      // leaving the control displaying a value the server never took.
      setObserverTimezone(previous);
      const message = err instanceof Error && err.message ? err.message : "Failed to save observer timezone";
      setTzError(message);
      showToast(message, "error");
    }
  };

  // Free-text fallback only: the dropdown cannot produce an unparseable name,
  // but a typed one must clear its own client-side error before it is sent.
  const saveObserverTimezoneText = () => {
    if (tzError()) return;
    void saveObserverTimezone(observerTimezone().trim());
  };

  // --- Scan trigger ---
  const runScan = () =>
    startScan({
      includeCalibration: frameFilter() === "all",
      forceOrphanCleanup: forceOrphanCleanup(),
    });

  const handleStartScan = () => {
    if (forceOrphanCleanup()) {
      setForceCleanupConfirmOpen(true);
      return;
    }
    runScan();
  };

  // Pick up an in-flight rebuild when Settings opens.
  fetchRebuildStatus();

  onCleanup(() => {
    stopPolling();
  });

  return (
    <div class="space-y-4">
      <DatabaseOverview summary={dbSummary()} storage={stats()?.storage} />

      <Show when={stats()}>
        {(data) => <CaptureActivity history={data().ingest_history} />}
      </Show>

      <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-4 items-stretch">
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
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-medium text-theme-text-primary">Library Scanning</h3>
              <HelpPopover title="Library Scanning">
                <p class="text-sm text-theme-text-secondary">
                  A scan walks the configured library path, reads FITS headers, and imports target names, filters, timestamps, and equipment metadata into the catalog.
                </p>
                <p class="text-sm text-theme-text-secondary">
                  The action bar at the bottom runs a one-time scan. Pick <strong class="text-theme-text-primary">Light frames only</strong> to skip calibration frames (darks, flats, bias), or <strong class="text-theme-text-primary">All frames</strong> to catalog every FITS file found.
                </p>
                <p class="text-sm text-theme-text-secondary">
                  Example: after a night of capture, run a scan to pull the new files from your NAS directory into the catalog.
                </p>
              </HelpPopover>
              <Show when={isAdmin()}>
                <button
                  class="ml-auto text-xs underline text-theme-text-secondary hover:text-theme-text-primary"
                  onClick={() => openSetupWizard()}
                >
                  Run setup again
                </button>
              </Show>
            </div>

            <Show when={isAdmin()}>
              <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
                <div class="flex items-center gap-2">
                  <h4 class="text-sm font-medium text-theme-text-primary">Auto-scan</h4>
                  <HelpPopover title="Auto-scan">
                    <p class="text-sm text-theme-text-secondary">
                      Runs a scan automatically on a fixed interval so new files dropped into the library are picked up without manual action.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Example: set the interval to 1 hour to ingest frames that your capture software writes during an active session, or 12 hours if you only sync files once per day.
                    </p>
                  </HelpPopover>
                </div>
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

            <Show when={isAdmin()}>
              <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
                <div class="flex items-center gap-2">
                  <h4 class="text-sm font-medium text-theme-text-primary">Guide Logs</h4>
                  <HelpPopover title="Guide Logs">
                    <p class="text-sm text-theme-text-secondary">
                      Collects PHD2 guide logs found anywhere under the library path during the same walk that reads FITS files, and stores per-session guiding statistics alongside your frames.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Only files named PHD2_GuideLog_*.txt are read; PHD2 debug logs are ignored. Turn this off if your library holds guide logs you do not want catalogued.
                    </p>
                  </HelpPopover>
                </div>
                <div class="flex items-center justify-between">
                  <label class="text-sm text-theme-text-secondary">Scan PHD2 guide logs</label>
                  <button
                    onClick={handlePhd2ScanToggle}
                    class={`relative w-10 h-5 rounded-full transition-colors ${
                      phd2ScanEnabled() ? "bg-theme-accent" : "bg-theme-text-tertiary"
                    }`}
                  >
                    <span
                      class={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                        phd2ScanEnabled() ? "translate-x-5" : ""
                      }`}
                    />
                  </button>
                </div>
              </section>
            </Show>

            <section id="observer-location" class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4 scroll-mt-4">
              <div class="flex items-center gap-2">
                <h4 class="text-sm font-medium text-theme-text-primary">Observer Location</h4>
                <HelpPopover title="Observer Location">
                  <p class="text-sm text-theme-text-secondary">
                    Latitude, longitude, and a site name for your imaging location. Used as a fallback when FITS headers lack site coordinates, and to compute the local noon boundary used by imaging-night session grouping.
                  </p>
                  <p class="text-sm text-theme-text-secondary">
                    Example: with a longitude of -74, frames captured between local noon one day and local noon the next are grouped as one imaging night, so a session that crosses midnight stays together.
                  </p>
                  <p class="text-sm text-theme-text-secondary">
                    The timezone is the clock the computer running PHD2 was set to. PHD2 writes guide log timestamps as local wall-clock with no zone marker, so this is what lines those sessions up with your frames.
                  </p>
                  <p class="text-sm text-theme-text-secondary">
                    It is not the server's clock, and it is not the display timezone on the Display tab, which only changes how already-recorded times are shown. The server runs on UTC inside its container no matter which timezone the machine hosting it uses, so there is no sensible value to fall back to. While this is unset, guide logs are still catalogued but their guiding numbers are not applied to individual frames.
                  </p>
                </HelpPopover>
              </div>
              <div class="space-y-3">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
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
                  <label class="text-xs text-theme-text-secondary" for="observer-timezone">Timezone</label>
                  <Show
                    when={timezoneList}
                    fallback={
                      <input
                        id="observer-timezone"
                        type="text"
                        placeholder="America/New_York"
                        class={`w-full px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 outline-none ${
                          tzError()
                            ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                            : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                        }`}
                        value={observerTimezone()}
                        onInput={(e) => {
                          const raw = e.currentTarget.value;
                          setObserverTimezone(raw);
                          setTzError(!raw.trim() || isValidTimeZone(raw.trim()) ? null : "Not a recognized IANA time zone");
                        }}
                        onBlur={saveObserverTimezoneText}
                      />
                    }
                  >
                    {(zones) => (
                      <select
                        id="observer-timezone"
                        class={`w-full px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 outline-none ${
                          tzError()
                            ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                            : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                        }`}
                        value={observerTimezone()}
                        onChange={(e) => saveObserverTimezone(e.currentTarget.value)}
                      >
                        {/* Deliberately first and deliberately empty: saving this
                            field forces a re-parse of every guide log, so the
                            control must never arrive pre-set to a zone the user
                            did not choose. */}
                        <option value="">Select a timezone</option>
                        <Show when={displayTimezoneOption()}>
                          {(opt) => <option value={opt().value}>{opt().label}</option>}
                        </Show>
                        <Show when={unlistedTimezone()}>
                          {(zone) => <option value={zone()}>{zone()}</option>}
                        </Show>
                        <For each={zones()}>{(zone) => <option value={zone}>{zone}</option>}</For>
                      </select>
                    )}
                  </Show>
                  <Show when={tzError()}>
                    <p class="text-xs text-red-500">{tzError()}</p>
                  </Show>
                </div>
                <div class="space-y-1">
                  <label class="text-xs text-theme-text-secondary">Latitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    min="-90"
                    max="90"
                    class={`w-full px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary tabular-nums focus:ring-1 outline-none ${
                      latError()
                        ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                        : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                    }`}
                    value={observerLatitude() ?? ""}
                    onInput={(e) => {
                      const raw = e.currentTarget.value;
                      if (!raw) { setObserverLatitude(null); setLatError(null); return; }
                      const v = parseFloat(raw);
                      setObserverLatitude(v);
                      setLatError(v < -90 || v > 90 ? "Must be between -90 and 90" : null);
                    }}
                    onBlur={async () => {
                      if (latError()) return;
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
                  <Show when={latError()}>
                    <p class="text-xs text-red-500">{latError()}</p>
                  </Show>
                </div>
                <div class="space-y-1">
                  <label class="text-xs text-theme-text-secondary">Longitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    min="-180"
                    max="180"
                    class={`w-full px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary tabular-nums focus:ring-1 outline-none ${
                      lngError()
                        ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                        : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                    }`}
                    value={observerLongitude() ?? ""}
                    onInput={(e) => {
                      const raw = e.currentTarget.value;
                      if (!raw) { setObserverLongitude(null); setLngError(null); return; }
                      const v = parseFloat(raw);
                      setObserverLongitude(v);
                      setLngError(v < -180 || v > 180 ? "Must be between -180 and 180" : null);
                    }}
                    onBlur={async () => {
                      if (lngError()) return;
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
                  <Show when={lngError()}>
                    <p class="text-xs text-red-500">{lngError()}</p>
                  </Show>
                </div>
              </div>
              </div>
            </section>

            <ScanFiltersPanel initialData={scanFiltersData()} />

            <div class="flex flex-wrap items-center gap-4 justify-end pt-2 border-t border-theme-border">
              <ScanControls
                isActive={isActive()}
                stopping={stopping()}
                rebuildRunning={rebuildState().state === "running"}
                frameFilter={frameFilter()}
                forceOrphanCleanup={forceOrphanCleanup()}
                onFrameFilterChange={setFrameFilter}
                onForceOrphanCleanupChange={setForceOrphanCleanup}
                onStartScan={handleStartScan}
                onStopScan={stopScan}
              />
            </div>
          </div>

          <Show when={isAdmin()}>
            <MaintenanceActions />
          </Show>
        </div>

        {/* Right column: activity feed matches left column height */}
        <div id="activity-feed" class="relative min-w-0 min-h-[24rem] lg:min-h-0 scroll-mt-4">
          <div class="lg:absolute lg:inset-0 lg:flex lg:flex-col">
            <ActivityFeed />
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={forceCleanupConfirmOpen()}
        title="Force orphan cleanup?"
        message="This scan removes catalogued records for every file currently missing from disk, with no safety limit. If a storage share is unmounted or unreachable, this will erase a large portion of your catalog. Only continue if you deliberately deleted these files."
        confirmLabel="Force cleanup"
        cancelLabel="Cancel"
        onConfirm={() => {
          setForceCleanupConfirmOpen(false);
          runScan();
          // One-time intent: revert to a normal scan after a confirmed run.
          setForceOrphanCleanup(false);
        }}
        onCancel={() => setForceCleanupConfirmOpen(false)}
      />
    </div>
  );
};

export default ScanManager;
