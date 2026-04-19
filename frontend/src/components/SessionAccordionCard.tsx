import { Component, Show, For, createSignal, createEffect, createMemo } from "solid-js";
import type { SessionOverview, SessionDetail, FrameRecord, IntegrationInstance } from "../types";
import { api } from "../api/client";
import ReferenceThumbnail from "./ReferenceThumbnail";
import RawHeaderAccordion from "./RawHeaderAccordion";
import FilterBadges from "./FilterBadges";
import SessionMetricsChart from "./SessionMetricsChart";
import { rigColor } from "./RigTogglePills";
import { useSettingsContext } from "./SettingsProvider";
import { isFieldVisible, isColumnVisible } from "../utils/displaySettings";
import InlineEditCell from "./InlineEditCell";
import { formatTime as formatTimeUtil, timezoneLabel } from "../utils/dateTime";
import { ClickableFilePath } from "./ClickableFilePath";

import { formatIntegration } from "../utils/format";
import { showToast } from "./Toast";

const INSIGHT_STYLES: Record<string, string> = {
  good: "text-theme-success",
  warning: "text-theme-warning",
  info: "text-theme-text-secondary",
};

const INSIGHT_ICONS: Record<string, string> = {
  good: "✓",
  warning: "⚠",
  info: "•",
};

interface VisibleColumns {
  hfr: boolean;
  eccentricity: boolean;
  fwhm: boolean;
  detected_stars: boolean;
  guiding_rms: boolean;
}

const SessionAccordionCard: Component<{
  session: SessionOverview;
  isExpanded: boolean;
  onToggle: () => void;
  detail: SessionDetail | null;
  autoScroll?: boolean;
  visibleColumns?: VisibleColumns;
  showCheckbox?: boolean;
  checked?: boolean;
  onCheckChange?: () => void;
  targetId?: string;
  ra?: number | null;
  dec?: number | null;
  targetName?: string;
}> = (props) => {
  let cardRef: HTMLTableRowElement | undefined;
  const settingsCtx = useSettingsContext();
  const { displaySettings } = settingsCtx;
  const visible = (group: Parameters<typeof isFieldVisible>[1], field: string) =>
    isFieldVisible(displaySettings(), group, field);
  const [showSummary, setShowSummary] = createSignal(true);
  const [showInsights, setShowInsights] = createSignal(true);
  const [showFrames, setShowFrames] = createSignal(false);
  const [sortColumn, setSortColumn] = createSignal<keyof FrameRecord>("timestamp");
  const [sortAsc, setSortAsc] = createSignal(true);
  const [csvCopiedRig, setCsvCopiedRig] = createSignal<string | null>(null);

  const [sessionNote, setSessionNote] = createSignal(props.detail?.notes || "");
  const [showNotes, setShowNotes] = createSignal(false);
  const [showDetails, setShowDetails] = createSignal(false);
  const [noteSaving, setNoteSaving] = createSignal(false);
  let noteTimer: ReturnType<typeof setTimeout> | undefined;

  const [enabledRigs, setEnabledRigs] = createSignal<string[]>([]);

  // Initialize enabledRigs when detail loads
  createEffect(() => {
    const d = props.detail;
    if (d && d.rigs.length > 0 && enabledRigs().length === 0) {
      setEnabledRigs(d.rigs.map(r => r.rig_label));
    }
  });

  const toggleRig = (rig: string) => {
    setEnabledRigs((prev) => {
      if (prev.includes(rig)) {
        if (prev.length <= 1) return prev;
        return prev.filter((r) => r !== rig);
      }
      return [...prev, rig];
    });
  };

  const isMultiRig = () => (props.detail?.rigs.length ?? 0) > 1;
  const rigLabels = () => props.detail?.rigs.map(r => r.rig_label) ?? [];

  // Sync when detail loads
  createEffect(() => {
    if (props.detail?.notes !== undefined) {
      setSessionNote(props.detail.notes || "");
    }
  });

  const saveSessionNote = (text: string) => {
    if (!props.targetId) return;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => {
      setNoteSaving(true);
      try {
        await api.updateSessionNotes(props.targetId!, props.session.session_date, text || null);
        showToast("Session notes saved");
      } catch {
        showToast("Failed to save session notes", "error");
      } finally {
        setNoteSaving(false);
      }
    }, 1000);
  };

  const copyAstrobinCsv = (rigLabel?: string) => {
    const d = props.detail;
    if (!d) return;
    const header = "date,filter,number,duration,binning,gain,sensorCooling,fNumber,bortle,meanSqm,meanFwhm,temperature";

    const median = (vals: number[]) => {
      if (vals.length === 0) return null;
      const s = [...vals].sort((a, b) => a - b);
      const mid = Math.floor(s.length / 2);
      return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    };

    const aliasMap = settingsCtx.filterAliasMap();
    const abFilterIds = settingsCtx.settings()?.general.astrobin_filter_ids ?? {};
    const bortle = settingsCtx.settings()?.general.astrobin_bortle ?? "";

    const lookupAbId = (filterName: string) => {
      const canonical = aliasMap[filterName] ?? filterName;
      return abFilterIds[canonical] ?? abFilterIds[filterName] ?? "";
    };

    const buildRows = (filterDetails: typeof d.filter_details, gain: number | null, sensorTemp: number | null, fwhm: number | null, ambientTemp: number | null) => {
      return filterDetails.map((f) => {
        const duration = f.exposure_time ?? "";
        const filterId = lookupAbId(f.filter_name);
        const g = gain !== null ? gain : "";
        const cooling = sensorTemp !== null ? Math.round(sensorTemp) : "";
        const mFwhm = fwhm !== null ? fwhm.toFixed(2) : "";
        const temp = ambientTemp !== null ? ambientTemp.toFixed(2) : "";
        return `${d.session_date},${filterId},${f.frame_count},${duration},,${g},${cooling},,${bortle},,${mFwhm},${temp}`;
      });
    };

    let rows: string[];
    const targetRig = rigLabel ? d.rigs.find(r => r.rig_label === rigLabel) : null;
    if (targetRig) {
      const temps = targetRig.frames.map(f => f.sensor_temp).filter((t): t is number => t !== null);
      const fwhms = targetRig.frames.map(f => f.fwhm).filter((v): v is number => v !== null);
      const ambTemps = targetRig.frames.map(f => f.ambient_temp).filter((v): v is number => v !== null);
      rows = buildRows(targetRig.filter_details, targetRig.gain, median(temps), median(fwhms), median(ambTemps));
    } else {
      rows = buildRows(d.filter_details, d.gain, d.sensor_temp, d.median_fwhm, d.median_ambient_temp);
    }

    const csv = [header, ...rows].join("\n");
    const key = rigLabel ?? "__all__";
    navigator.clipboard.writeText(csv).then(() => {
      setCsvCopiedRig(key);
      setTimeout(() => setCsvCopiedRig(null), 2000);
    });
  };

  const ninaInstances = () =>
    (settingsCtx.settings()?.general.nina_instances ?? []).filter(
      (i: IntegrationInstance) => i.enabled && i.url
    );
  const stellariumInstances = () =>
    (settingsCtx.settings()?.general.stellarium_instances ?? []).filter(
      (i: IntegrationInstance) => i.enabled && i.url
    );
  const hasCoords = () => props.ra != null && props.dec != null;

  const [sendingInstance, setSendingInstance] = createSignal<string | null>(null);

  const sendToNina = async (inst: IntegrationInstance) => {
    if (!hasCoords()) return;
    const key = `nina:${inst.name}`;
    setSendingInstance(key);
    try {
      const res = await api.sendToNina(inst.url, props.ra!, props.dec!);
      if (res.ok) {
        showToast(`Sent to NINA: ${inst.name}`);
      } else {
        showToast(`NINA ${inst.name}: ${res.error}`, "error");
      }
    } catch {
      showToast(`Failed to reach NINA: ${inst.name}`, "error");
    } finally {
      setTimeout(() => setSendingInstance(null), 1500);
    }
  };

  const sendToStellarium = async (inst: IntegrationInstance) => {
    if (!hasCoords()) return;
    const key = `stel:${inst.name}`;
    setSendingInstance(key);
    try {
      const res = await api.sendToStellarium(inst.url, props.ra!, props.dec!, props.targetName ?? null);
      if (res.ok) {
        showToast(`Sent to Stellarium: ${inst.name}`);
      } else {
        showToast(`Stellarium ${inst.name}: ${res.error}`, "error");
      }
    } catch {
      showToast(`Failed to reach Stellarium: ${inst.name}`, "error");
    } finally {
      setTimeout(() => setSendingInstance(null), 1500);
    }
  };

  createEffect(() => {
    if (props.autoScroll && props.isExpanded && cardRef) {
      cardRef.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  const sortedFrames = (inputFrames?: FrameRecord[]) => {
    const frames = inputFrames ?? props.detail?.frames ?? [];
    const col = sortColumn();
    const asc = sortAsc();
    return [...frames].sort((a, b) => {
      const va = a[col];
      const vb = b[col];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
  };

  const toggleSort = (col: keyof FrameRecord) => {
    if (sortColumn() === col) {
      setSortAsc(!sortAsc());
    } else {
      setSortColumn(col);
      setSortAsc(true);
    }
  };

  const isHfrOutlier = (frame: FrameRecord, medianHfr?: number | null): boolean => {
    const med = medianHfr ?? props.detail?.median_hfr;
    if (!med || !frame.median_hfr) return false;
    return frame.median_hfr > med * 1.5;
  };

  const isEccOutlier = (frame: FrameRecord, medianEcc?: number | null): boolean => {
    const med = medianEcc ?? props.detail?.median_eccentricity;
    if (!med || !frame.eccentricity) return false;
    return frame.eccentricity > med * 1.5;
  };

  const isOutlier = (frame: FrameRecord, medianHfr?: number | null, medianEcc?: number | null): boolean => {
    return isHfrOutlier(frame, medianHfr) || isEccOutlier(frame, medianEcc);
  };

  const renderFrameTable = (frames: FrameRecord[], medianHfr?: number | null, medianEcc?: number | null) => {
    const sorted = createMemo(() => sortedFrames(frames));
    const previewFiles = createMemo(() =>
      sorted().map((f) => ({
        imageId: f.image_id,
        filePath: f.file_path,
        thumbnailUrl: f.thumbnail_url,
      })),
    );
    return (
    <table class="w-full text-label">
      <thead class="sticky top-0 bg-theme-base">
        <tr class="text-theme-text-secondary border-b border-theme-border">
          <SortHeader label={`Time (${timezoneLabel(settingsCtx.timezone())})`} column="timestamp" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} />
          <SortHeader label="Filter" column="filter_used" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="center" />
          <SortHeader label="Exp" column="exposure_time" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          <Show when={visible("quality", "hfr")}>
            <SortHeader label="HFR" column="median_hfr" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("quality", "eccentricity")}>
            <SortHeader label="Ecc" column="eccentricity" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("quality", "fwhm")}>
            <SortHeader label="FWHM" column="fwhm" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("quality", "detected_stars")}>
            <SortHeader label="Stars" column="detected_stars" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("guiding", "rms_total")}>
            <SortHeader label="RMS" column="guiding_rms_arcsec" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("guiding", "rms_ra")}>
            <SortHeader label="RMS RA" column="guiding_rms_ra_arcsec" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("guiding", "rms_dec")}>
            <SortHeader label="RMS Dec" column="guiding_rms_dec_arcsec" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("adu", "mean")}>
            <SortHeader label="ADU Mean" column="adu_mean" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("adu", "median")}>
            <SortHeader label="ADU Med" column="adu_median" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("adu", "stdev")}>
            <SortHeader label="ADU σ" column="adu_stdev" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("adu", "min")}>
            <SortHeader label="ADU Min" column="adu_min" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("adu", "max")}>
            <SortHeader label="ADU Max" column="adu_max" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("focuser", "position")}>
            <SortHeader label="Focus" column="focuser_position" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("focuser", "temp")}>
            <SortHeader label="Focus Temp" column="focuser_temp" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "ambient_temp")}>
            <SortHeader label="Amb Temp" column="ambient_temp" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "dew_point")}>
            <SortHeader label="Dew Pt" column="dew_point" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "humidity")}>
            <SortHeader label="Humidity" column="humidity" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "pressure")}>
            <SortHeader label="Pressure" column="pressure" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "wind_speed")}>
            <SortHeader label="Wind" column="wind_speed" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "wind_direction")}>
            <SortHeader label="Wind Dir" column="wind_direction" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "wind_gust")}>
            <SortHeader label="Gust" column="wind_gust" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "cloud_cover")}>
            <SortHeader label="Clouds" column="cloud_cover" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("weather", "sky_quality")}>
            <SortHeader label="SQM" column="sky_quality" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("mount", "airmass")}>
            <SortHeader label="Airmass" column="airmass" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <Show when={visible("mount", "pier_side")}>
            <SortHeader label="Pier" column="pier_side" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="center" />
          </Show>
          <Show when={visible("mount", "rotator_position")}>
            <SortHeader label="Rotator" column="rotator_position" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          </Show>
          <SortHeader label="Temp" column="sensor_temp" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          <SortHeader label="Gain" column="gain" current={sortColumn()} asc={sortAsc()} onSort={toggleSort} align="right" />
          <th class="text-left py-1.5 px-2 font-normal">File</th>
        </tr>
      </thead>
      <tbody>
        <For each={sorted()}>
          {(frame, i) => (
            <tr class={`border-b border-theme-border/30 hover:bg-theme-hover transition-colors duration-100 ${isOutlier(frame, medianHfr, medianEcc) ? "bg-theme-error/20" : ""}`}>
              <td class="py-1 px-2 text-theme-text-primary">{formatTimeUtil(frame.timestamp, settingsCtx.timezone(), settingsCtx.use24hTime())}</td>
              <td class="py-1 px-2 text-theme-text-primary text-center">{frame.filter_used ?? "—"}</td>
              <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.exposure_time ?? "—"}s</td>
              <Show when={visible("quality", "hfr")}>
                <td class={`py-1 px-2 text-right tabular-nums ${isHfrOutlier(frame, medianHfr) ? "text-theme-error" : "text-theme-text-primary"}`}>
                  {frame.median_hfr?.toFixed(2) ?? "\u2014"}
                </td>
              </Show>
              <Show when={visible("quality", "eccentricity")}>
                <td class={`py-1 px-2 text-right tabular-nums ${isEccOutlier(frame, medianEcc) ? "text-theme-error" : "text-theme-text-primary"}`}>{frame.eccentricity?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("quality", "fwhm")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.fwhm?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("quality", "detected_stars")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.detected_stars ?? "\u2014"}</td>
              </Show>
              <Show when={visible("guiding", "rms_total")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.guiding_rms_arcsec !== null ? `${frame.guiding_rms_arcsec?.toFixed(2)}"` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("guiding", "rms_ra")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.guiding_rms_ra_arcsec !== null ? `${frame.guiding_rms_ra_arcsec?.toFixed(2)}"` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("guiding", "rms_dec")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.guiding_rms_dec_arcsec !== null ? `${frame.guiding_rms_dec_arcsec?.toFixed(2)}"` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("adu", "mean")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.adu_mean?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("adu", "median")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.adu_median?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("adu", "stdev")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.adu_stdev?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("adu", "min")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.adu_min ?? "\u2014"}</td>
              </Show>
              <Show when={visible("adu", "max")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.adu_max ?? "\u2014"}</td>
              </Show>
              <Show when={visible("focuser", "position")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.focuser_position ?? "\u2014"}</td>
              </Show>
              <Show when={visible("focuser", "temp")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.focuser_temp !== null ? `${frame.focuser_temp?.toFixed(1)}\u00b0` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("weather", "ambient_temp")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.ambient_temp !== null ? `${frame.ambient_temp?.toFixed(1)}\u00b0` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("weather", "dew_point")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.dew_point !== null ? `${frame.dew_point?.toFixed(1)}\u00b0` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("weather", "humidity")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.humidity !== null ? `${frame.humidity?.toFixed(1)}%` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("weather", "pressure")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.pressure?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("weather", "wind_speed")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.wind_speed?.toFixed(1) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("weather", "wind_direction")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.wind_direction?.toFixed(1) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("weather", "wind_gust")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.wind_gust?.toFixed(1) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("weather", "cloud_cover")}>
                <td class="py-1 px-2 text-theme-text-primary text-right">
                  {frame.cloud_cover !== null ? `${frame.cloud_cover?.toFixed(1)}%` : "\u2014"}
                </td>
              </Show>
              <Show when={visible("weather", "sky_quality")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.sky_quality?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("mount", "airmass")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.airmass?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <Show when={visible("mount", "pier_side")}>
                <td class="py-1 px-2 text-theme-text-primary text-center">{frame.pier_side ?? "\u2014"}</td>
              </Show>
              <Show when={visible("mount", "rotator_position")}>
                <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.rotator_position?.toFixed(2) ?? "\u2014"}</td>
              </Show>
              <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.sensor_temp?.toFixed(0) ?? "—"}°C</td>
              <td class="py-1 px-2 text-theme-text-primary text-right tabular-nums">{frame.gain ?? "—"}</td>
              <td class="py-1 px-2 text-theme-text-secondary text-left">
                <ClickableFilePath
                  imageId={frame.image_id}
                  filePath={frame.file_path}
                  thumbnailUrl={frame.thumbnail_url}
                  display={frame.file_name}
                  files={previewFiles()}
                  index={i()}
                />
              </td>
            </tr>
          )}
        </For>
      </tbody>
    </table>
    );
  };

  return (
    <>
      {/* Collapsed header row */}
      <tr
        ref={cardRef}
        class={`cursor-pointer hover:bg-theme-hover transition-all duration-150 text-xs border-t-2 border-theme-border-em ${
          props.isExpanded ? "bg-theme-elevated font-medium" : ""
        }`}
        onClick={props.onToggle}
      >
        <Show when={props.showCheckbox}>
          <td class="py-3 pl-4 pr-1 w-8" onClick={(e) => e.stopPropagation()}>
            <input
              type="checkbox"
              checked={props.checked}
              onChange={props.onCheckChange}
              class="w-3.5 h-3.5 rounded border-theme-border cursor-pointer"
            />
          </td>
        </Show>
        <td class="py-3 px-4">
          <div class="flex flex-col sm:flex-row sm:items-center gap-0.5 sm:gap-0">
            <span class="font-bold text-theme-text-primary text-sm">{props.session.session_date}</span>
            <span class="text-theme-text-secondary sm:ml-3 text-xs sm:text-sm">
              {props.session.rig_count > 1 ? (
                <span class="inline-flex items-center gap-1">
                  <span class="px-1.5 py-0.5 rounded bg-theme-accent/20 text-theme-accent text-tiny font-semibold">
                    {props.session.rig_count} rigs
                  </span>
                </span>
              ) : (
                <>{props.session.camera ?? ""} · {props.session.telescope ?? ""}</>
              )}
            </span>
          </div>
        </td>
        <td class="py-3 px-2 text-right text-metric-integration tabular-nums whitespace-nowrap">{formatIntegration(props.session.integration_seconds)}</td>
        <td class="py-3 px-2 text-right text-metric-frames tabular-nums whitespace-nowrap">{props.session.frame_count} fr</td>
        <Show when={props.visibleColumns?.hfr ?? true}>
          <td class="py-3 px-2 text-right text-metric-hfr tabular-nums whitespace-nowrap">{props.session.median_hfr?.toFixed(1) ?? "—"}</td>
        </Show>
        <Show when={props.visibleColumns?.eccentricity ?? true}>
          <td class="py-3 px-2 text-right text-metric-eccentricity tabular-nums whitespace-nowrap">{props.session.median_eccentricity?.toFixed(2) ?? "—"}</td>
        </Show>
        <Show when={props.visibleColumns?.fwhm ?? false}>
          <td class="py-3 px-2 text-right text-metric-fwhm tabular-nums whitespace-nowrap">{props.session.median_fwhm?.toFixed(2) ?? "—"}</td>
        </Show>
        <Show when={props.visibleColumns?.detected_stars ?? false}>
          <td class="py-3 px-2 text-right text-metric-stars tabular-nums whitespace-nowrap">{props.session.median_detected_stars?.toFixed(0) ?? "—"}</td>
        </Show>
        <Show when={props.visibleColumns?.guiding_rms ?? false}>
          <td class="py-3 px-2 text-right text-metric-guiding tabular-nums whitespace-nowrap">
            {props.session.median_guiding_rms_arcsec !== null ? `${props.session.median_guiding_rms_arcsec?.toFixed(2)}"` : "—"}
          </td>
        </Show>
        <For each={(settingsCtx.customColumns() ?? []).filter(c => c.applies_to === "session")}>
          {(col) => (
            <td class="py-3 px-2 text-right" onClick={(e) => e.stopPropagation()}>
              <InlineEditCell
                columnType={col.column_type}
                value={props.session.custom_values?.[col.slug]}
                dropdownOptions={col.dropdown_options}
                onSave={(v) => api.setCustomValue({
                  column_id: col.id,
                  target_id: props.targetId!,
                  session_date: props.session.session_date,
                  value: v,
                })}
              />
            </td>
          )}
        </For>
        <td class="py-3 px-2">
          <div class="flex justify-end">
            <FilterBadges distribution={Object.fromEntries(props.session.filters_used.map(f => [f, 0]))} compact nowrap />
          </div>
        </td>
        <td class="py-3 px-2">
          <div class="flex items-center gap-1.5 justify-end">
            <span
              class={`inline-block w-4 h-4 ${props.session.has_notes ? "text-theme-accent" : "text-theme-text-secondary opacity-30"}`}
              title={props.session.has_notes ? "Has notes" : "No notes"}
            >
              <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
              </svg>
            </span>
            <svg
              class={`w-4 h-4 transition-transform duration-200 ${
                props.isExpanded ? "rotate-180 text-theme-accent" : "text-theme-text-tertiary"
              }`}
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
            </svg>
          </div>
        </td>
      </tr>

      {/* Expanded content row */}
      <Show when={props.isExpanded}>
        <tr class="bg-theme-surface">
          <td colspan="12" class="px-4 pt-3 pb-4 border-t border-theme-border">
          <Show when={!props.detail}>
            <div class="py-4 text-theme-text-secondary text-sm">Loading session data...</div>
          </Show>

          <Show when={props.detail}>
            {(detail) => (
              <div class="space-y-3 pt-3">
                {/* Session Notes */}
                <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
                  <button
                    class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
                    classList={{ "text-theme-text-primary": showNotes(), "text-theme-text-secondary": !showNotes() }}
                    onClick={() => setShowNotes((v) => !v)}
                  >
                    <span class="font-semibold border-l-2 border-theme-accent pl-2">
                      Session Notes
                      <Show when={sessionNote()}>
                        <span class="text-theme-text-tertiary font-normal ml-2">has content</span>
                      </Show>
                    </span>
                    <div class="flex items-center gap-2">
                      <Show when={noteSaving()}>
                        <span class="text-theme-text-tertiary font-normal">Saving...</span>
                      </Show>
                      <svg
                        class={`w-3.5 h-3.5 transition-transform duration-200 ${showNotes() ? "rotate-180" : ""}`}
                        viewBox="0 0 20 20"
                        fill="currentColor"
                      >
                        <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                      </svg>
                    </div>
                  </button>
                  <Show when={showNotes()}>
                    <div class="px-3 pb-3">
                      <textarea
                        class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
                        placeholder="Add notes for this session..."
                        value={sessionNote()}
                        onInput={(e) => {
                          const val = e.currentTarget.value;
                          setSessionNote(val);
                          saveSessionNote(val);
                        }}
                      />
                    </div>
                  </Show>
                </div>

                {/* Session Summary (collapsible) */}
                <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
                  <button
                    class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
                    classList={{ "text-theme-text-primary": showSummary(), "text-theme-text-secondary": !showSummary() }}
                    onClick={() => setShowSummary((v) => !v)}
                  >
                    <span class="font-semibold border-l-2 border-theme-accent pl-2">Session Summary</span>
                    <svg
                      class={`w-3.5 h-3.5 transition-transform duration-200 ${showSummary() ? "rotate-180" : ""}`}
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                    </svg>
                  </button>
                <Show when={showSummary()}>
                <div class="px-3 pb-3">
                {/* Headline stats row */}
                <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-label">
                  <span>
                    <span class="text-theme-text-tertiary">Integration:</span>{" "}
                    <span class="font-bold text-metric-integration">{formatIntegration(detail().integration_seconds)}</span>
                  </span>
                  <span>
                    <span class="text-theme-text-tertiary">Frames:</span>{" "}
                    <span class="font-bold text-metric-frames">{detail().frame_count}</span>
                  </span>
                  <span>
                    <span class="text-theme-text-tertiary">Gain / Offset:</span>{" "}
                    <span class="font-bold text-metric-gain">
                      {detail().gain !== null ? detail().gain : "—"} / {detail().offset !== null ? detail().offset : "—"}
                    </span>
                  </span>
                  <span>
                    <span class="text-theme-text-tertiary">Time:</span>{" "}
                    <span class="font-bold text-metric-time">
                      {detail().first_frame_time ? `${formatTimeUtil(detail().first_frame_time!, settingsCtx.timezone(), settingsCtx.use24hTime())} → ${detail().last_frame_time ? formatTimeUtil(detail().last_frame_time!, settingsCtx.timezone(), settingsCtx.use24hTime()) : ""}` : "—"}
                    </span>
                  </span>
                </div>

                {/* Per-rig overview with thumbnails */}
                <Show when={isMultiRig()} fallback={
                  /* Single-rig: compact one-liner + thumbnail */
                  <div class="flex gap-3 mt-3 items-start">
                    <div class="flex-1 space-y-1">
                      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-label">
                        <span><span class="text-theme-text-tertiary">Exp:</span> <span class="font-bold text-metric-gain">{detail().exposure_times.length > 0 ? detail().exposure_times.map(e => e + "s").join(", ") : "—"}</span></span>
                        <span><span class="text-theme-text-tertiary">HFR:</span> <span class="font-bold text-metric-hfr">{detail().median_hfr?.toFixed(2) ?? "—"}</span></span>
                        <span><span class="text-theme-text-tertiary">Ecc:</span> <span class="font-bold text-metric-eccentricity">{detail().median_eccentricity?.toFixed(2) ?? "—"}</span></span>
                        <span><span class="text-theme-text-tertiary">FWHM:</span> <span class="font-bold text-metric-fwhm">{detail().median_fwhm?.toFixed(2) ?? "—"}</span></span>
                        <span><span class="text-theme-text-tertiary">RMS:</span> <span class="font-bold text-metric-guiding">{detail().median_guiding_rms !== null ? `${detail().median_guiding_rms?.toFixed(2)}"` : "—"}</span></span>
                      </div>
                      <div class="flex flex-wrap gap-1.5">
                        <For each={detail().filter_details}>
                          {(f) => (
                            <span class="text-tiny px-1.5 py-0.5 rounded bg-theme-hover text-theme-text-secondary">
                              <b>{f.filter_name}</b> {f.frame_count} · {f.exposure_time ?? "—"}s
                            </span>
                          )}
                        </For>
                      </div>
                      <div class="flex flex-wrap gap-1.5">
                        <button
                          class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                          onClick={() => copyAstrobinCsv()}
                        >
                          {csvCopiedRig() === "__all__" ? "Copied!" : "Astrobin CSV"}
                        </button>
                        <Show when={hasCoords()}>
                          <For each={ninaInstances()}>
                            {(inst) => (
                              <button
                                class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                                onClick={() => sendToNina(inst)}
                                disabled={sendingInstance() === `nina:${inst.name}`}
                              >
                                {sendingInstance() === `nina:${inst.name}` ? "Sent!" : `${inst.name}`}
                              </button>
                            )}
                          </For>
                          <For each={stellariumInstances()}>
                            {(inst) => (
                              <button
                                class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                                onClick={() => sendToStellarium(inst)}
                                disabled={sendingInstance() === `stel:${inst.name}`}
                              >
                                {sendingInstance() === `stel:${inst.name}` ? "Sent!" : `${inst.name}`}
                              </button>
                            )}
                          </For>
                        </Show>
                      </div>
                    </div>
                    <div class="w-[140px] h-[100px] flex-shrink-0 ml-auto rounded overflow-hidden">
                      <ReferenceThumbnail url={detail().thumbnail_url} fill />
                    </div>
                  </div>
                }>
                  {/* Multi-rig: per-rig rows with key metrics + thumbnail */}
                  <For each={detail().rigs}>
                    {(rig, index) => (
                      <div class="flex gap-3 mt-3 items-start">
                        <div class="flex-1">
                          <div class="flex items-center gap-2 mb-1">
                            <span class="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ "background-color": rigColor(index()) }} />
                            <span class="text-xs font-semibold text-theme-text-primary">{rig.rig_label}</span>
                            <span class="text-tiny text-theme-text-tertiary">{rig.frame_count} fr · {formatIntegration(rig.integration_seconds)}</span>
                            <button
                              class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                              onClick={() => copyAstrobinCsv(rig.rig_label)}
                            >
                              {csvCopiedRig() === rig.rig_label ? "Copied!" : "Astrobin CSV"}
                            </button>
                          </div>
                          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-label ml-4">
                            <span><span class="text-theme-text-tertiary">HFR:</span> <span class="font-bold text-metric-hfr">{rig.median_hfr?.toFixed(2) ?? "—"}</span></span>
                            <span><span class="text-theme-text-tertiary">Ecc:</span> <span class="font-bold text-metric-eccentricity">{rig.median_eccentricity?.toFixed(2) ?? "—"}</span></span>
                            <span><span class="text-theme-text-tertiary">FWHM:</span> <span class="font-bold text-metric-fwhm">{rig.median_fwhm?.toFixed(2) ?? "—"}</span></span>
                            <span><span class="text-theme-text-tertiary">RMS:</span> <span class="font-bold text-metric-guiding">{rig.median_guiding_rms !== null ? `${rig.median_guiding_rms?.toFixed(2)}"` : "—"}</span></span>
                          </div>
                          <div class="flex flex-wrap gap-1.5 mt-1 ml-4">
                            <For each={rig.filter_details}>
                              {(f) => (
                                <span class="text-tiny px-1.5 py-0.5 rounded bg-theme-hover text-theme-text-secondary">
                                  <b>{f.filter_name}</b> {f.frame_count} · {f.exposure_time ?? "—"}s
                                </span>
                              )}
                            </For>
                          </div>
                          {/* Rig-level custom columns */}
                          <Show when={(settingsCtx.customColumns() ?? []).filter(c => c.applies_to === "rig").length > 0}>
                            <div class="flex flex-wrap gap-4 mt-1 ml-4">
                              <For each={(settingsCtx.customColumns() ?? []).filter(c => c.applies_to === "rig")}>
                                {(col) => {
                                  const val = () => detail().custom_values?.find(
                                    (cv) => cv.column_slug === col.slug && cv.rig_label === rig.rig_label
                                  );
                                  return (
                                    <div class="flex items-center gap-2 text-xs">
                                      <span class="text-[var(--text-secondary)]">{col.name}:</span>
                                      <InlineEditCell
                                        columnType={col.column_type}
                                        value={val()?.value}
                                        dropdownOptions={col.dropdown_options}
                                        onSave={(v) => api.setCustomValue({
                                          column_id: col.id,
                                          target_id: props.targetId!,
                                          session_date: detail().session_date,
                                          rig_label: rig.rig_label,
                                          value: v,
                                        })}
                                      />
                                    </div>
                                  );
                                }}
                              </For>
                            </div>
                          </Show>
                        </div>
                        <div class="w-[140px] h-[100px] flex-shrink-0 ml-auto rounded overflow-hidden">
                          <ReferenceThumbnail url={rig.thumbnail_url ?? null} fill />
                        </div>
                      </div>
                    )}
                  </For>
                  <Show when={hasCoords() && (ninaInstances().length > 0 || stellariumInstances().length > 0)}>
                    <div class="flex flex-wrap gap-1.5 mt-3">
                      <For each={ninaInstances()}>
                        {(inst) => (
                          <button
                            class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                            onClick={() => sendToNina(inst)}
                            disabled={sendingInstance() === `nina:${inst.name}`}
                          >
                            {sendingInstance() === `nina:${inst.name}` ? "Sent!" : `${inst.name}`}
                          </button>
                        )}
                      </For>
                      <For each={stellariumInstances()}>
                        {(inst) => (
                          <button
                            class="text-tiny px-1.5 py-0.5 border border-theme-border rounded text-theme-text-tertiary hover:text-theme-text-primary hover:border-theme-accent transition-colors cursor-pointer"
                            onClick={() => sendToStellarium(inst)}
                            disabled={sendingInstance() === `stel:${inst.name}`}
                          >
                            {sendingInstance() === `stel:${inst.name}` ? "Sent!" : `${inst.name}`}
                          </button>
                        )}
                      </For>
                    </div>
                  </Show>
                </Show>

                {/* Expandable detail table */}
                <button
                  class="text-label text-theme-accent hover:text-theme-text-primary transition-colors cursor-pointer mt-2"
                  onClick={() => setShowDetails((v) => !v)}
                >
                  {showDetails() ? "▾ Hide Details" : "▸ Show Details"}
                </button>
                <Show when={showDetails()}>
                  <div class="mt-3 overflow-x-auto">
                    <table class="w-full text-xs" style={{ "border-collapse": "collapse" }}>
                      <thead>
                        <tr class="text-tiny text-theme-text-tertiary uppercase tracking-wider border-b border-theme-border">
                          <Show when={isMultiRig()}><th class="text-left px-2 pb-1.5 pt-2.5">Rig</th></Show>
                          <th class="text-left px-2 pb-1.5 pt-2.5">Filter</th>
                          <th class="text-right px-2 pb-1.5 pt-2.5">Frames</th>
                          <th class="text-right px-2 pb-1.5 pt-2.5">Integration</th>
                          <th class="text-right px-2 pb-1.5 pt-2.5">HFR</th>
                          <th class="text-right px-2 pb-1.5 pt-2.5">Ecc</th>
                          <th class="text-right px-2 pb-1.5 pt-2.5">Exp</th>
                        </tr>
                      </thead>
                      <tbody>
                        <Show when={isMultiRig()} fallback={
                          <For each={detail().filter_details}>
                            {(f) => (
                              <tr class="border-b border-theme-border/50 hover:bg-theme-hover transition-colors duration-100">
                                <td class="py-1.5 px-2 text-theme-text-primary">{f.filter_name}</td>
                                <td class="py-1.5 px-2 text-right text-theme-text-primary">{f.frame_count}</td>
                                <td class="py-1.5 px-2 text-right text-theme-text-secondary">{formatIntegration(f.integration_seconds)}</td>
                                <td class="py-1.5 px-2 text-right text-metric-hfr">{f.median_hfr?.toFixed(2) ?? "—"}</td>
                                <td class="py-1.5 px-2 text-right text-metric-eccentricity">{f.median_eccentricity?.toFixed(2) ?? "—"}</td>
                                <td class="py-1.5 px-2 text-right text-theme-text-secondary">{f.exposure_time ?? "—"}s</td>
                              </tr>
                            )}
                          </For>
                        }>
                          <For each={detail().rigs}>
                            {(rig, index) => (
                              <For each={rig.filter_details}>
                                {(f, fi) => (
                                  <tr class={`border-b border-theme-border/50 hover:bg-theme-hover transition-colors duration-100 ${fi() === 0 && index() > 0 ? "border-t-2 border-t-theme-border" : ""}`}>
                                    {fi() === 0 ? (
                                      <td class="py-1.5 px-2 text-theme-text-secondary align-top" rowSpan={rig.filter_details.length}>
                                        <span class="flex items-center gap-1.5">
                                          <span class="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ "background-color": rigColor(index()) }} />
                                          <span class="text-tiny">{rig.telescope ?? ""}</span>
                                        </span>
                                      </td>
                                    ) : null}
                                    <td class="py-1.5 px-2 text-theme-text-primary">{f.filter_name}</td>
                                    <td class="py-1.5 px-2 text-right text-theme-text-primary">{f.frame_count}</td>
                                    <td class="py-1.5 px-2 text-right text-theme-text-secondary">{formatIntegration(f.integration_seconds)}</td>
                                    <td class="py-1.5 px-2 text-right text-metric-hfr">{f.median_hfr?.toFixed(2) ?? "—"}</td>
                                    <td class="py-1.5 px-2 text-right text-metric-eccentricity">{f.median_eccentricity?.toFixed(2) ?? "—"}</td>
                                    <td class="py-1.5 px-2 text-right text-theme-text-secondary">{f.exposure_time ?? "—"}s</td>
                                  </tr>
                                )}
                              </For>
                            )}
                          </For>
                        </Show>
                      </tbody>
                    </table>
                  </div>
                </Show>
                </div>
                </Show>
                </div>

                {/* Session Insights */}
                <Show when={detail().insights.length > 0}>
                  <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
                    <button
                      class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
                      classList={{ "text-theme-text-primary": showInsights(), "text-theme-text-secondary": !showInsights() }}
                      onClick={() => setShowInsights((v) => !v)}
                    >
                      <span class="font-semibold border-l-2 border-theme-accent pl-2">
                        Session Insights <span class="text-theme-text-tertiary font-normal">({detail().insights.length})</span>
                      </span>
                      <svg
                        class={`w-3.5 h-3.5 transition-transform duration-200 ${showInsights() ? "rotate-180" : ""}`}
                        viewBox="0 0 20 20"
                        fill="currentColor"
                      >
                        <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                      </svg>
                    </button>
                    <Show when={showInsights()}>
                      <div class="px-3 pb-3 space-y-1">
                        <For each={detail().insights}>
                          {(insight) => (
                            <div class={`text-xs ${INSIGHT_STYLES[insight.level]}`}>
                              {INSIGHT_ICONS[insight.level]} {insight.message}
                            </div>
                          )}
                        </For>
                      </div>
                    </Show>
                  </div>
                </Show>

                {/* Session Metrics Chart */}
                <SessionMetricsChart detail={detail()} enabledRigs={enabledRigs()} onToggleRig={toggleRig} />

                {/* Row 4: Per-Frame Table (collapsed) */}
                <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
                  <button
                    class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
                    classList={{ "text-theme-text-primary": showFrames(), "text-theme-text-secondary": !showFrames() }}
                    onClick={() => setShowFrames(!showFrames())}
                  >
                    <span class="font-semibold border-l-2 border-theme-accent pl-2">
                      Per-Frame Data <span class="text-theme-text-tertiary font-normal">({detail().frames.length} frames{isMultiRig() ? ` · ${enabledRigs().length} rigs` : ""})</span>
                    </span>
                    <svg
                      class={`w-3.5 h-3.5 transition-transform duration-200 ${showFrames() ? "rotate-180" : ""}`}
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                    </svg>
                  </button>
                  <Show when={showFrames()}>
                    <div class="px-3 pb-3">
                    <Show when={isMultiRig()} fallback={
                      <div class="overflow-x-auto max-h-[600px] overflow-y-auto">
                        {renderFrameTable(props.detail!.frames, props.detail!.median_hfr, props.detail!.median_eccentricity)}
                      </div>
                    }>
                      <For each={props.detail!.rigs}>
                        {(rig, index) => (
                          <Show when={enabledRigs().includes(rig.rig_label)}>
                            <div class="mt-2 first:mt-0">
                              <div class="flex items-center gap-2 mb-1">
                                <span class="w-2 h-2 rounded-full inline-block"
                                  style={{ "background-color": rigColor(index()) }} />
                                <span class="text-xs font-semibold text-theme-text-primary">{rig.rig_label}</span>
                                <span class="text-tiny text-theme-text-tertiary">{rig.frame_count} frames</span>
                              </div>
                              <div class="overflow-x-auto max-h-[600px] overflow-y-auto">
                                {renderFrameTable(rig.frames, rig.median_hfr, rig.median_eccentricity)}
                              </div>
                            </div>
                          </Show>
                        )}
                      </For>
                    </Show>
                    </div>
                  </Show>
                </div>

                {/* Row 5: FITS Headers */}
                <RawHeaderAccordion headers={detail().raw_reference_header} />

              </div>
            )}
          </Show>
          </td>
        </tr>
      </Show>
    </>
  );
};

// --- Helper components ---

const SortHeader: Component<{
  label: string;
  column: keyof FrameRecord;
  current: keyof FrameRecord;
  asc: boolean;
  onSort: (col: keyof FrameRecord) => void;
  align?: "left" | "right" | "center";
}> = (props) => (
  <th
    class={`${props.align === "right" ? "text-right" : props.align === "center" ? "text-center" : "text-left"} py-1.5 px-2 font-normal cursor-pointer hover:text-theme-text-primary transition-colors`}
    onClick={() => props.onSort(props.column)}
  >
    {props.label}
    {props.current === props.column ? (props.asc ? " ↑" : " ↓") : ""}
  </th>
);

export default SessionAccordionCard;
