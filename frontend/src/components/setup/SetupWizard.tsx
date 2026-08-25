import { Component, For, Show, createEffect, createSignal } from "solid-js";
import Dialog from "../Dialog";
import Button from "../ui/Button";
import FolderBrowserModal from "../FolderBrowserModal";
import { showToast } from "../Toast";
import { useSettingsContext } from "../SettingsProvider";
import { useScan } from "../../store/scan";
import { setupApi } from "../../api/setup";
import { scanFilters, type NameRule } from "../../api/scanFilters";
import { supportedTimeZones } from "../../utils/dateTime";
import type { GeneralSettings } from "../../api/types";

const STEPS = [
  "Environment",
  "Location",
  "Scan filters",
  "Ingest options",
  "First scan",
];

/** Folder names commonly holding processing output rather than sub-frames. */
const EXCLUDE_PRESETS = ["masters", "WBPP", "calibrated", "WORK_AREA", "PixInsight"];

const INTERVALS = [
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 360, label: "6 hours" },
  { value: 480, label: "8 hours" },
  { value: 720, label: "12 hours" },
  { value: 1440, label: "24 hours" },
];

const inputClass =
  "w-full px-2.5 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent";

/** Preset excludes are folder-name rules so they prune at any depth, not just
 *  a `<fits_root>/<name>` directory (path excludes match by prefix only). */
const presetRule = (name: string): NameRule => ({
  id: `setup-exclude-${name}`,
  action: "exclude",
  type: "substring",
  pattern: name,
  target: "folder",
  enabled: true,
});

const CheckRow: Component<{ label: string; ok: boolean | null; value: string; hint?: string }> = (
  props,
) => (
  <div class="flex items-start justify-between gap-4 py-2 border-b border-theme-border last:border-b-0">
    <div class="min-w-0">
      <div class="text-sm text-theme-text-primary">{props.label}</div>
      <div class="text-xs text-theme-text-secondary break-all">{props.value}</div>
      <Show when={props.hint}>
        <div class="text-xs text-theme-warning mt-1">{props.hint}</div>
      </Show>
    </div>
    <Show when={props.ok !== null}>
      <span
        class={`text-xs font-medium shrink-0 ${
          props.ok ? "text-theme-success" : "text-theme-error"
        }`}
      >
        {props.ok ? "OK" : "Problem"}
      </span>
    </Show>
  </div>
);

const SetupWizard: Component = () => {
  const {
    settings,
    saveGeneral,
    setupState,
    setSetupComplete,
    closeSetupWizard,
  } = useSettingsContext();
  const { scanStatus, isActive, startScan } = useScan();

  const [step, setStep] = createSignal(0);
  const [busy, setBusy] = createSignal(false);

  // Step 2
  const [latitude, setLatitude] = createSignal("");
  const [longitude, setLongitude] = createSignal("");
  const [timezone, setTimezone] = createSignal("");
  const [imagingNight, setImagingNight] = createSignal(true);
  const [lonWarning, setLonWarning] = createSignal(false);

  // Step 3
  const [includePaths, setIncludePaths] = createSignal<string[]>([]);
  const [excludeNames, setExcludeNames] = createSignal<string[]>([]);
  const [browsing, setBrowsing] = createSignal(false);

  // Step 4
  const [includeCalibration, setIncludeCalibration] = createSignal(true);
  const [phd2Enabled, setPhd2Enabled] = createSignal(true);
  const [autoScan, setAutoScan] = createSignal(false);
  const [autoScanInterval, setAutoScanInterval] = createSignal(360);

  const [scanStarted, setScanStarted] = createSignal(false);

  // Seed the editable fields once, from whichever settings load wins.
  let seeded = false;
  createEffect(() => {
    const g = settings()?.general;
    if (!g || seeded) return;
    seeded = true;
    setLatitude(g.observer_latitude == null ? "" : String(g.observer_latitude));
    setLongitude(g.observer_longitude == null ? "" : String(g.observer_longitude));
    setTimezone(
      g.observer_timezone ||
        (() => {
          try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
          } catch {
            return "";
          }
        })(),
    );
    setImagingNight(g.use_imaging_night ?? true);
    setIncludeCalibration(g.include_calibration);
    setPhd2Enabled(g.phd2_scan_enabled ?? true);
    setAutoScan(g.auto_scan_enabled);
    setAutoScanInterval(g.auto_scan_interval);
  });

  const patchGeneral = async (patch: Partial<GeneralSettings>) => {
    const g = settings()?.general;
    if (!g) throw new Error("Settings not loaded");
    await saveGeneral({ ...g, ...patch });
  };

  const finish = async () => {
    setBusy(true);
    try {
      await setupApi.markComplete();
    } catch {
      // The wizard must close even if the stamp fails; it is a convenience
      // flag, not a gate on anything the user just configured.
      showToast("Could not record setup completion", "error");
    } finally {
      setBusy(false);
      setSetupComplete(true);
      closeSetupWizard();
    }
  };

  const geoAvailable =
    typeof navigator !== "undefined" && !!navigator.geolocation;

  const useMyLocation = () => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLatitude(pos.coords.latitude.toFixed(4));
        setLongitude(pos.coords.longitude.toFixed(4));
        setLonWarning(false);
      },
      () => showToast("Could not read your location", "error"),
    );
  };

  const num = (s: string): number | null => {
    const t = s.trim();
    if (!t) return null;
    const v = Number(t);
    return Number.isFinite(v) ? v : null;
  };

  const saveFilters = async (include: string[], excludeNames: string[]) => {
    await scanFilters.put({
      include_paths: include,
      exclude_paths: [],
      name_rules: excludeNames.map(presetRule),
    });
    window.dispatchEvent(new CustomEvent("scan-filters-configured"));
  };

  const envBlocked = () => {
    const s = setupState();
    return !!s && !s.fits_root_exists;
  };

  const nextDisabled = () => busy() || (step() === 0 && envBlocked());

  // Advances one step, running that step's persistence first. A failed save
  // keeps the user on the step with a toast rather than losing their input.
  const next = async () => {
    setBusy(true);
    try {
      if (step() === 1) {
        // A blank longitude costs the user imaging-night grouping, so the
        // first Next only surfaces the warning; a second Next accepts it.
        if (longitude().trim() === "") {
          if (!lonWarning()) {
            setLonWarning(true);
            return;
          }
        } else {
          setLonWarning(false);
        }
        await patchGeneral({
          observer_latitude: num(latitude()),
          observer_longitude: num(longitude()),
          observer_timezone: timezone().trim(),
          use_imaging_night: imagingNight(),
        });
      } else if (step() === 2) {
        await saveFilters(includePaths(), excludeNames());
      } else if (step() === 3) {
        await patchGeneral({
          include_calibration: includeCalibration(),
          phd2_scan_enabled: phd2Enabled(),
          auto_scan_enabled: autoScan(),
          auto_scan_interval: autoScanInterval(),
        });
      }
      setStep(step() + 1);
    } catch {
      showToast("Could not save this step", "error");
    } finally {
      setBusy(false);
    }
  };

  const scanEverything = async () => {
    setIncludePaths([]);
    setExcludeNames([]);
    setBusy(true);
    try {
      await saveFilters([], []);
      setStep(3);
    } catch {
      showToast("Could not save this step", "error");
    } finally {
      setBusy(false);
    }
  };

  const timezoneList = supportedTimeZones();

  return (
    <Dialog open={true} onClose={() => {}} aria-labelledby="setup-wizard-title">
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border">
          <h2 id="setup-wizard-title" class="text-sm font-medium text-theme-text-primary">
            First-run setup
          </h2>
          <p class="text-xs text-theme-text-secondary mt-1">
            Step {step() + 1} of {STEPS.length}: {STEPS[step()]}
          </p>
        </div>

        <div class="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Step 1: environment check */}
          <Show when={step() === 0}>
            <Show
              when={setupState()}
              fallback={
                <p class="text-sm text-theme-text-secondary">
                  Environment details are unavailable. Continue and configure the
                  rest by hand.
                </p>
              }
            >
              {(s) => (
                <div>
                  <CheckRow
                    label="FITS library path"
                    value={s().fits_root}
                    ok={s().fits_root_exists}
                    hint={
                      s().fits_root_exists
                        ? undefined
                        : "The path is not a directory inside the container. Set GALACTILOG_FITS_HOST_PATH and restart."
                    }
                  />
                  <CheckRow
                    label="Library contains entries"
                    value={s().fits_root_has_entries ? "Yes" : "No files found"}
                    ok={s().fits_root_has_entries}
                    hint={
                      s().fits_root_has_entries
                        ? undefined
                        : "The mount is empty. Check that GALACTILOG_FITS_HOST_PATH points at your capture folder."
                    }
                  />
                  <CheckRow
                    label="HTTPS"
                    value={s().https_enabled ? "Enabled" : "Disabled"}
                    ok={null}
                    hint={
                      s().https_enabled
                        ? undefined
                        : "Set GALACTILOG_HTTPS=true if this instance is reachable outside your network."
                    }
                  />
                  <CheckRow label="Version" value={s().version} ok={null} />
                </div>
              )}
            </Show>
          </Show>

          {/* Step 2: location */}
          <Show when={step() === 1}>
            <p class="text-sm text-theme-text-secondary">
              Coordinates group frames into imaging nights and drive darkness
              calculations.
            </p>
            <div class="grid grid-cols-2 gap-3">
              <label class="space-y-1">
                <span class="text-xs text-theme-text-secondary">Latitude</span>
                <input
                  class={inputClass}
                  value={latitude()}
                  placeholder="42.3601"
                  onInput={(e) => setLatitude(e.currentTarget.value)}
                />
              </label>
              <label class="space-y-1">
                <span class="text-xs text-theme-text-secondary">Longitude</span>
                <input
                  class={inputClass}
                  value={longitude()}
                  placeholder="-71.0589"
                  onInput={(e) => setLongitude(e.currentTarget.value)}
                />
              </label>
            </div>
            <Show when={geoAvailable}>
              <Button variant="secondary" size="sm" onClick={useMyLocation}>
                Use my location
              </Button>
            </Show>
            <Show when={lonWarning()}>
              <p class="text-xs text-theme-warning">
                Imaging-night grouping falls back to UTC until longitude is set
              </p>
            </Show>
            <label class="space-y-1 block">
              <span class="text-xs text-theme-text-secondary">Capture computer timezone</span>
              <Show
                when={timezoneList}
                fallback={
                  <input
                    class={inputClass}
                    value={timezone()}
                    onInput={(e) => setTimezone(e.currentTarget.value)}
                  />
                }
              >
                {(zones) => (
                  <select
                    class={inputClass}
                    value={timezone()}
                    onChange={(e) => setTimezone(e.currentTarget.value)}
                  >
                    <option value="">Select a timezone</option>
                    <For each={zones()}>{(z) => <option value={z}>{z}</option>}</For>
                  </select>
                )}
              </Show>
            </label>
            <label class="flex items-center gap-2 text-sm text-theme-text-primary">
              <input
                type="checkbox"
                checked={imagingNight()}
                onChange={(e) => setImagingNight(e.currentTarget.checked)}
              />
              Group frames by imaging night
            </label>
          </Show>

          {/* Step 3: scan filters */}
          <Show when={step() === 2}>
            <p class="text-sm text-theme-text-secondary">
              Limit the scan to the folders holding your sub-frames. Select
              nothing to scan the whole library.
            </p>
            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs text-theme-text-secondary">Include folders</span>
                <Button variant="secondary" size="sm" onClick={() => setBrowsing(true)}>
                  Browse
                </Button>
              </div>
              <Show
                when={includePaths().length > 0}
                fallback={
                  <p class="text-xs text-theme-text-secondary">
                    None selected. The entire library will be scanned.
                  </p>
                }
              >
                <ul class="space-y-1">
                  <For each={includePaths()}>
                    {(p, i) => (
                      <li class="flex items-center justify-between gap-2 text-xs text-theme-text-primary">
                        <code class="break-all">{p}</code>
                        <button
                          class="underline hover:no-underline shrink-0"
                          onClick={() =>
                            setIncludePaths(includePaths().filter((_, n) => n !== i()))
                          }
                        >
                          Remove
                        </button>
                      </li>
                    )}
                  </For>
                </ul>
              </Show>
            </div>

            <div class="space-y-2">
              <span class="text-xs text-theme-text-secondary">
                Skip common output folders, wherever they sit in the tree
              </span>
              <For each={EXCLUDE_PRESETS}>
                {(name) => (
                  <label class="flex items-center gap-2 text-sm text-theme-text-primary">
                    <input
                      type="checkbox"
                      checked={excludeNames().includes(name)}
                      onChange={(e) =>
                        setExcludeNames(
                          e.currentTarget.checked
                            ? [...excludeNames(), name]
                            : excludeNames().filter((n) => n !== name),
                        )
                      }
                    />
                    {name}
                  </label>
                )}
              </For>
            </div>

            <div class="flex items-center gap-4">
              <Button variant="secondary" size="sm" disabled={busy()} onClick={scanEverything}>
                Scan everything
              </Button>
              <a
                class="text-xs underline text-theme-accent"
                href="/settings?tab=scan"
                target="_blank"
                rel="noreferrer"
              >
                Advanced rules
              </a>
            </div>

            <FolderBrowserModal
              open={browsing()}
              fitsRoot={setupState()?.fits_root ?? ""}
              title="Select folders to scan"
              existing={includePaths()}
              onCancel={() => setBrowsing(false)}
              onConfirm={(paths) => {
                setIncludePaths([...includePaths(), ...paths]);
                setBrowsing(false);
              }}
            />
          </Show>

          {/* Step 4: ingest options */}
          <Show when={step() === 3}>
            <label class="flex items-center gap-2 text-sm text-theme-text-primary">
              <input
                type="checkbox"
                checked={includeCalibration()}
                onChange={(e) => setIncludeCalibration(e.currentTarget.checked)}
              />
              Catalog calibration frames (darks, flats, bias)
            </label>
            <label class="flex items-center gap-2 text-sm text-theme-text-primary">
              <input
                type="checkbox"
                checked={phd2Enabled()}
                onChange={(e) => setPhd2Enabled(e.currentTarget.checked)}
              />
              Read PHD2 guide logs found in the library
            </label>
            <label class="flex items-center gap-2 text-sm text-theme-text-primary">
              <input
                type="checkbox"
                checked={autoScan()}
                onChange={(e) => setAutoScan(e.currentTarget.checked)}
              />
              Scan automatically on a schedule
            </label>
            <Show when={autoScan()}>
              <label class="space-y-1 block">
                <span class="text-xs text-theme-text-secondary">Scan interval</span>
                <select
                  class={inputClass}
                  value={autoScanInterval()}
                  onChange={(e) => setAutoScanInterval(parseInt(e.currentTarget.value, 10))}
                >
                  <For each={INTERVALS}>
                    {(o) => <option value={o.value}>{o.label}</option>}
                  </For>
                </select>
              </label>
            </Show>
          </Show>

          {/* Step 5: first scan */}
          <Show when={step() === 4}>
            <p class="text-sm text-theme-text-secondary">
              Run the first scan now, or finish and start it later from Settings.
            </p>
            <Button
              variant="primary"
              disabled={isActive()}
              onClick={() => {
                setScanStarted(true);
                void startScan({ includeCalibration: includeCalibration() });
              }}
            >
              Start scan
            </Button>
            <Show when={scanStarted() || isActive()}>
              <p class="text-sm text-theme-text-primary">
                State: {scanStatus().state}
              </p>
              <p class="text-xs text-theme-text-secondary">
                {scanStatus().completed} of {scanStatus().total} files processed,{" "}
                {scanStatus().failed} failed
              </p>
            </Show>
          </Show>
        </div>

        <div class="p-4 border-t border-theme-border flex items-center justify-between">
          <button
            class="text-xs underline text-theme-text-secondary disabled:opacity-50"
            disabled={busy()}
            onClick={finish}
          >
            Skip setup
          </button>
          <div class="flex gap-2">
            <Button
              variant="secondary"
              disabled={step() === 0 || busy()}
              onClick={() => setStep(step() - 1)}
            >
              Back
            </Button>
            <Show
              when={step() < STEPS.length - 1}
              fallback={
                <Button variant="primary" disabled={busy()} onClick={finish}>
                  Finish
                </Button>
              }
            >
              <Button variant="primary" disabled={nextDisabled()} onClick={next}>
                Next
              </Button>
            </Show>
          </div>
        </div>
      </div>
    </Dialog>
  );
};

export default SetupWizard;
