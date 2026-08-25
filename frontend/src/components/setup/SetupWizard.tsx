import { Component, For, Show, createEffect, createSignal, type JSX } from "solid-js";
import Dialog from "../Dialog";
import Button from "../ui/Button";
import FolderBrowserModal from "../FolderBrowserModal";
import HelpPopover from "../HelpPopover";
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

const CheckRow: Component<{
  label: string;
  ok: boolean | null;
  value: string;
  hint?: string;
  help?: JSX.Element;
}> = (props) => (
  <div class="flex items-start justify-between gap-4 py-2 border-b border-theme-border last:border-b-0">
    <div class="min-w-0">
      <div class="flex items-center gap-1.5">
        <span class="text-sm text-theme-text-primary">{props.label}</span>
        {props.help}
      </div>
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

/** Removable chips for the selected include folders. Rendered on step 1 and
 *  step 3 against the same signal, so a pick made on either shows on both. */
const FolderChips: Component<{
  paths: string[];
  root: string;
  onRemove: (index: number) => void;
}> = (props) => (
  <Show
    when={props.paths.length > 0}
    fallback={
      <p class="text-xs text-theme-text-secondary">
        None selected. Everything under {props.root} will be scanned.
      </p>
    }
  >
    <ul class="flex flex-wrap gap-2">
      <For each={props.paths}>
        {(p, i) => (
          <li class="flex items-center gap-1.5 px-2 py-1 rounded-full bg-theme-elevated border border-theme-border text-xs text-theme-text-primary">
            <code class="break-all">{p}</code>
            <button
              type="button"
              aria-label={`Remove ${p}`}
              class="text-theme-text-secondary hover:text-theme-text-primary shrink-0"
              onClick={() => props.onRemove(i())}
            >
              &times;
            </button>
          </li>
        )}
      </For>
    </ul>
  </Show>
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

  // Step 3 (the folder picker is also reachable from step 1)
  const [includePaths, setIncludePaths] = createSignal<string[]>([]);
  // Every preset starts checked: processing-output folders are the common case
  // and cataloguing them distorts frame counts, so opt out rather than opt in.
  const [excludeNames, setExcludeNames] = createSignal<string[]>([...EXCLUDE_PRESETS]);
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

  const removeInclude = (index: number) =>
    setIncludePaths(includePaths().filter((_, n) => n !== index));

  const saveFilters = async (include: string[], excludeNames: string[]) => {
    await scanFilters.put({
      include_paths: include,
      exclude_paths: [],
      name_rules: excludeNames.map(presetRule),
    });
    window.dispatchEvent(new CustomEvent("scan-filters-configured"));
  };

  /** The mounted library root, for copy that names what "everything" means.
   *  Falls back to a generic phrase only when the env probe is unavailable. */
  const rootLabel = () => setupState()?.fits_root ?? "the library";

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
                    help={
                      <HelpPopover
                        title="FITS library path"
                        label="About the FITS library path"
                      >
                        <p>
                          The folder mounted into the container as your FITS
                          library. Every file the scanner reads lives under this
                          path.
                        </p>
                        <p>
                          The host folder comes from GALACTILOG_FITS_HOST_PATH in
                          the .env file and is mounted inside the container at
                          GALACTILOG_FITS_DATA_PATH. It cannot be changed from
                          this dialog: edit .env and restart the stack to point
                          at a different folder.
                        </p>
                        <p>
                          Subfolders under the root can be selected below to
                          limit what a scan walks.
                        </p>
                      </HelpPopover>
                    }
                  />

                  <div class="py-3 space-y-2 border-b border-theme-border">
                    <div class="flex items-center gap-1.5">
                      <span class="text-sm text-theme-text-primary">
                        Folders to scan
                      </span>
                      <HelpPopover
                        title="Folders to scan"
                        label="About folders to scan"
                      >
                        <p>
                          Limits the scan to the folders you pick, so nothing
                          outside them is walked. The library root itself is
                          fixed by the container mount; only subfolders under it
                          can be selected.
                        </p>
                        <p>
                          Picking nothing scans everything under {rootLabel()}.
                          Example: select your Lights folder to leave a sibling
                          folder of processed images untouched.
                        </p>
                        <p>
                          Nothing is saved here. The picks carry over to the Scan
                          filters step, which writes them.
                        </p>
                      </HelpPopover>
                      <Button
                        class="ml-auto"
                        variant="secondary"
                        size="sm"
                        disabled={!s().fits_root_exists}
                        onClick={() => setBrowsing(true)}
                      >
                        Choose folders to scan
                      </Button>
                    </div>
                    <p class="text-xs text-theme-text-secondary">
                      The library root is set by the container mount and cannot
                      be changed here; only subfolders under it are selectable.
                      Pick nothing to scan everything under {rootLabel()}.
                    </p>
                    <FolderChips
                      paths={includePaths()}
                      root={rootLabel()}
                      onRemove={removeInclude}
                    />
                  </div>

                  <CheckRow
                    label="Library contains files"
                    value={s().fits_root_has_entries ? "Yes" : "No files found"}
                    ok={s().fits_root_has_entries}
                    hint={
                      s().fits_root_has_entries
                        ? undefined
                        : "The mount is empty. Check that GALACTILOG_FITS_HOST_PATH points at your capture folder."
                    }
                    help={
                      <HelpPopover
                        title="Library contains files"
                        label="About the library contents check"
                      >
                        <p>
                          Checks that the mounted library is not empty. A scan of
                          an empty mount finds nothing and imports nothing.
                        </p>
                        <p>
                          If no files are found, GALACTILOG_FITS_HOST_PATH points
                          at the wrong host folder, or the folder is not readable
                          by the container.
                        </p>
                      </HelpPopover>
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
                    help={
                      <HelpPopover title="HTTPS" label="About HTTPS">
                        <p>
                          Whether this instance serves over HTTPS, set by
                          GALACTILOG_HTTPS in the .env file.
                        </p>
                        <p>
                          With HTTPS enabled, the session cookie is marked
                          secure. A browser refuses to store a secure cookie
                          delivered over plain http://, so a login appears to
                          succeed and then returns to the login page on the next
                          request. Reach the instance over https://, or leave
                          HTTPS disabled while you use it over plain HTTP on a
                          local network.
                        </p>
                      </HelpPopover>
                    }
                  />
                  <CheckRow
                    label="Version"
                    value={s().version}
                    ok={null}
                    help={
                      <HelpPopover title="Version" label="About the version">
                        <p>
                          The GalactiLog build currently running. Quote it when
                          reporting a problem, and compare it against the image
                          tag you pulled after an upgrade.
                        </p>
                      </HelpPopover>
                    }
                  />
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
                <span class="text-xs text-theme-text-secondary inline-flex items-center gap-1.5">
                  Latitude
                  <HelpPopover title="Latitude" label="About latitude">
                    <p>
                      Your site latitude in decimal degrees, positive north of
                      the equator and negative south of it.
                    </p>
                    <p>
                      Used as a fallback when FITS headers carry no site
                      coordinates, and to compute darkness hours and target
                      altitude. Example: 42.3601 for Boston.
                    </p>
                  </HelpPopover>
                </span>
                <input
                  class={inputClass}
                  value={latitude()}
                  placeholder="42.3601"
                  onInput={(e) => setLatitude(e.currentTarget.value)}
                />
              </label>
              <label class="space-y-1">
                <span class="text-xs text-theme-text-secondary inline-flex items-center gap-1.5">
                  Longitude
                  <HelpPopover title="Longitude" label="About longitude">
                    <p>
                      Your site longitude in decimal degrees, positive east of
                      Greenwich and negative west of it.
                    </p>
                    <p>
                      Used as a fallback when FITS headers carry no site
                      coordinates, and to compute the local noon boundary used by
                      imaging-night grouping. Example: with a longitude of -74,
                      frames captured between local noon one day and local noon
                      the next are grouped as one imaging night, so a session
                      that crosses midnight stays together.
                    </p>
                  </HelpPopover>
                </span>
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
              <span class="text-xs text-theme-text-secondary inline-flex items-center gap-1.5">
                Capture computer timezone
                <HelpPopover
                  title="Capture computer timezone"
                  label="About the capture computer timezone"
                >
                  <p>
                    The clock the computer running PHD2 was set to. PHD2 writes
                    guide log timestamps as local wall-clock with no zone marker,
                    so this is what lines those sessions up with your frames.
                  </p>
                  <p>
                    It is not the server's clock, and it is not the display
                    timezone on the Display tab, which only changes how
                    already-recorded times are shown. The server runs on UTC
                    inside its container no matter which timezone the host uses,
                    so there is no sensible value to fall back to.
                  </p>
                  <p>
                    While this is unset, guide logs are still catalogued but
                    their guiding numbers are not applied to individual frames.
                  </p>
                </HelpPopover>
              </span>
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
            <div class="flex items-center gap-1.5">
              <label class="flex items-center gap-2 text-sm text-theme-text-primary">
                <input
                  type="checkbox"
                  checked={imagingNight()}
                  onChange={(e) => setImagingNight(e.currentTarget.checked)}
                />
                Group frames by imaging night
              </label>
              <HelpPopover
                title="Group frames by imaging night"
                label="About imaging night grouping"
              >
                <p>
                  An imaging session runs from dusk to dawn, so frames captured
                  after midnight belong to the previous evening's night. With
                  this on, those frames stay in one session instead of splitting
                  across two calendar dates.
                </p>
                <p>
                  The boundary is local noon, computed from your longitude:
                  frames captured between local noon one day and local noon the
                  next count as one night.
                </p>
                <p>
                  Without a longitude the boundary falls back to UTC midnight,
                  which splits most nights in two.
                </p>
              </HelpPopover>
            </div>
          </Show>

          {/* Step 3: scan filters */}
          <Show when={step() === 2}>
            <p class="text-sm text-theme-text-secondary">
              Limit the scan to the folders holding your sub-frames. Select
              nothing to scan everything under {rootLabel()}.
            </p>
            <div class="space-y-2">
              <div class="flex items-center gap-1.5">
                <span class="text-xs text-theme-text-secondary">Folders to scan</span>
                <HelpPopover title="Folders to scan" label="About folders to scan">
                  <p>
                    Limits the scan to the folders you pick, so nothing outside
                    them is walked. Selecting nothing scans everything under{" "}
                    {rootLabel()}.
                  </p>
                  <p>
                    Example: pick your Lights folder to skip a sibling folder of
                    processed images. Folders picked on the Environment step
                    appear here already.
                  </p>
                </HelpPopover>
                <Button
                  class="ml-auto"
                  variant="secondary"
                  size="sm"
                  onClick={() => setBrowsing(true)}
                >
                  Browse
                </Button>
              </div>
              <FolderChips
                paths={includePaths()}
                root={rootLabel()}
                onRemove={removeInclude}
              />
            </div>

            <div class="space-y-2">
              <div class="flex items-center gap-1.5">
                <span class="text-xs text-theme-text-secondary">Folders to skip</span>
                <HelpPopover title="Folders to skip" label="About folders to skip">
                  <p>
                    Folder names skipped wherever they appear in the tree, at any
                    depth, rather than only directly under the library root.
                  </p>
                  <p>
                    These names usually hold processing output rather than
                    sub-frames. Cataloguing them fills the library with stacked,
                    calibrated, and intermediate files that distort frame counts
                    and integration totals.
                  </p>
                  <p>
                    All five start checked. Uncheck one if you keep sub-frames in
                    a folder by that name.
                  </p>
                </HelpPopover>
              </div>
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
              <p class="text-xs text-theme-text-secondary">
                These rules can be changed later under Settings &gt; Library &gt;
                Scan filters. Regex and filename rules are available there as
                well.
              </p>
            </div>

            <div class="flex items-center gap-4">
              <Button variant="secondary" size="sm" disabled={busy()} onClick={scanEverything}>
                Scan everything
              </Button>
            </div>
          </Show>

          {/* Step 4: ingest options */}
          <Show when={step() === 3}>
            <div class="flex items-center gap-1.5">
              <label class="flex items-center gap-2 text-sm text-theme-text-primary">
                <input
                  type="checkbox"
                  checked={includeCalibration()}
                  onChange={(e) => setIncludeCalibration(e.currentTarget.checked)}
                />
                Catalog calibration frames (darks, flats, bias)
              </label>
              <HelpPopover
                title="Calibration frames"
                label="About cataloguing calibration frames"
              >
                <p>
                  Catalogs darks, flats, and bias frames alongside light frames.
                  Turn it off to catalog light frames only, which is faster and
                  keeps the library limited to the frames that go into an image.
                </p>
                <p>
                  This sets the default. A one-time scan can still be run for
                  light frames only from the Scan page.
                </p>
              </HelpPopover>
            </div>
            <div class="flex items-center gap-1.5">
              <label class="flex items-center gap-2 text-sm text-theme-text-primary">
                <input
                  type="checkbox"
                  checked={phd2Enabled()}
                  onChange={(e) => setPhd2Enabled(e.currentTarget.checked)}
                />
                Read PHD2 guide logs found in the library
              </label>
              <HelpPopover title="Guide Logs" label="About PHD2 guide log scanning">
                <p>
                  Collects PHD2 guide logs found anywhere under the library path
                  during the same walk that reads FITS files, and stores
                  per-session guiding statistics alongside your frames.
                </p>
                <p>
                  Only files named PHD2_GuideLog_*.txt are read; PHD2 debug logs
                  are ignored. Turn this off if your library holds guide logs you
                  do not want catalogued.
                </p>
              </HelpPopover>
            </div>
            <div class="flex items-center gap-1.5">
              <label class="flex items-center gap-2 text-sm text-theme-text-primary">
                <input
                  type="checkbox"
                  checked={autoScan()}
                  onChange={(e) => setAutoScan(e.currentTarget.checked)}
                />
                Scan automatically on a schedule
              </label>
              <HelpPopover title="Auto-scan" label="About auto-scan">
                <p>
                  Runs a scan automatically on a fixed interval so new files
                  dropped into the library are picked up without manual action.
                </p>
                <p>
                  Example: set the interval to 1 hour to ingest frames that your
                  capture software writes during an active session, or 12 hours
                  if you only sync files once per day.
                </p>
              </HelpPopover>
            </div>
            <Show when={autoScan()}>
              <label class="space-y-1 block">
                <span class="text-xs text-theme-text-secondary inline-flex items-center gap-1.5">
                  Scan interval
                  <HelpPopover title="Scan interval" label="About the scan interval">
                    <p>
                      How long to wait between automatic scans. Each scan walks
                      the library again and reads only files that are new or
                      changed since the last run.
                    </p>
                    <p>
                      Shorter intervals pick up frames sooner at the cost of more
                      disk activity. A large library on a network share is
                      happier with a longer interval.
                    </p>
                  </HelpPopover>
                </span>
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
            <div class="flex items-center gap-1.5">
              <span class="text-sm text-theme-text-primary">First scan</span>
              <HelpPopover title="First scan" label="About the first scan">
                <p>
                  A scan walks the configured library path, reads FITS headers,
                  and imports target names, filters, timestamps, and equipment
                  metadata into the catalog.
                </p>
                <p>
                  The first scan reads every file it finds, so it takes far
                  longer than later scans, which only pick up new or changed
                  files. It keeps running in the background if you close this
                  dialog.
                </p>
                <p>
                  Everything configured in this wizard is already saved, so
                  starting the scan later from the Scan page loses nothing.
                </p>
              </HelpPopover>
            </div>
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

          {/* Shared by step 1 and step 3: both write the same include list. */}
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
