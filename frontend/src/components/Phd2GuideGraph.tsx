import {
  For,
  Show,
  Suspense,
  createSignal,
  createEffect,
  createMemo,
  onCleanup,
  type Component,
  type JSX,
} from "solid-js";
import { Chart } from "chart.js";
import "../utils/chartRegistry";
import { useQuery, keepPreviousData } from "@tanstack/solid-query";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { queryKeys } from "../api/queryKeys";
import { useSettingsContext } from "./SettingsProvider";
import { formatTime } from "../utils/dateTime";
import { formatArcsec } from "../utils/format";
import { chartFontSize, getMetricColor } from "../utils/chartConfig";
import {
  clockRange,
  clockTime,
  clockTimeWithSeconds,
  formatSecondsShort,
  type ClockOptions,
} from "../utils/phd2Format";
import HelpPopover from "./HelpPopover";
import {
  clampGuideView,
  downsampleGuideFrames,
  guideYRange,
  isFullGuideView,
  panGuideView,
  settleWindows,
  sliceFramesByTime,
  symmetricYBound,
  zoomGuideView,
  MIN_GUIDE_VIEW_SPAN,
  MIN_GUIDE_Y_SPAN,
  type GuideView,
  type SettleWindow,
} from "../utils/phd2Guide";
import type {
  Phd2SessionSummary,
  Phd2SessionListResponse,
  Phd2FramesResponse,
  Phd2Frame,
  Phd2Event,
} from "../api/types";

// chartjs-plugin-annotation is not a dependency and none is being added, so
// dither lines and settle shading are drawn by the inline plugin below --
// same approach as TargetMetricsChart.tsx's sessionBoundary plugin. Zoom and
// pan are hand-wired onto the canvas for the same reason: chartjs-plugin-zoom
// would be a new dependency.
const RA_COLOR_VAR = "--color-metric-guiding";
const DEC_COLOR_VAR = "--color-metric-fwhm";
const DROP_COLOR_VAR = "--color-metric-worst";
const DITHER_COLOR_VAR = "--color-metric-eccentricity";

const MAX_PLOT_POINTS = 2000;
/** One wheel notch. Small enough that a flick of the wheel is not a jump cut. */
const ZOOM_STEP = 0.82;
/** Height of the plot area before anyone drags the corner grip. */
const DEFAULT_GRAPH_HEIGHT = 220;
/** Below this the axis labels and the legend crowd out the trace itself. */
const MIN_GRAPH_HEIGHT = 140;

/** Which rig a guiding session belongs to.
 *
 * `equipment_profile` is the raw PHD2 log header name; `telescope` is what the
 * profile map resolves it to, and it is the canonical rig everywhere else in
 * the app. Two profile names can resolve to one physical scope, for instance
 * after a profile rename mid-season, so keying rig identity on the header name
 * would offer the same rig twice and hide half its sessions behind either
 * entry. The fallback matters: an unmapped profile has a null telescope, and
 * dropping it would take its sessions off the panel entirely.
 */
export function guideRigLabel(session: Phd2SessionSummary): string {
  return session.telescope ?? session.equipment_profile;
}

/** Dropdown label for one guiding session: start time, duration, optional rig. */
export function sessionOptionLabel(
  session: Phd2SessionSummary,
  startLabel: string,
  showProfile: boolean,
): string {
  const parts = [startLabel, formatSecondsShort(session.duration_s)];
  if (showProfile) parts.push(guideRigLabel(session));
  if (session.gated) parts.push("short");
  return parts.join(" · ");
}

/** Every rig that appears on this night, once each, in a stable order. Two
 *  PHD2 instances can run on one night against two rigs, and the session list
 *  is then an interleaving of both; this is what the rig filter offers and,
 *  when it holds a single entry, why the filter stays hidden. */
export function guideProfileOptions(sessions: Phd2SessionSummary[]): string[] {
  return [...new Set(sessions.map(guideRigLabel))].sort((a, b) =>
    a.localeCompare(b),
  );
}

/** The sessions the panel should treat as the night. A null rig means the
 *  whole night; a rig no longer present on the night yields nothing, which the
 *  caller resolves by clearing the filter rather than by silently showing the
 *  other rig. */
export function filterSessionsByProfile(
  sessions: Phd2SessionSummary[],
  profile: string | null,
): Phd2SessionSummary[] {
  if (!profile) return sessions;
  return sessions.filter((s) => guideRigLabel(s) === profile);
}

/** True when frames arrived but the session carries no pixel scale.
 *
 * The API converts pixels to arcsec with the session's own scale, so a null
 * scale nulls every ra and dec while the frame count stays large. Without this
 * test the populated branch renders an empty grid under a caption promising
 * arcseconds, with nothing to say the data is unconvertible.
 */
export function isScaleMissing(data: Phd2FramesResponse | undefined): boolean {
  return !!data && data.frames.length > 0 && data.pixel_scale_arcsec == null;
}

/** One tooltip line: the series name and its arcsecond value.
 *
 * Arcseconds go through formatArcsec so the graph prints the same two decimals
 * and the same true double-prime (U+2033) as the guiding panel and the session
 * card. An inline template here drifted from that once already.
 */
export function guideTooltipLabel(datasetLabel: string, value: number): string {
  if (datasetLabel === "Star lost") return "Star lost";
  return `${datasetLabel}: ${formatArcsec(value)}`;
}

/** One x-axis tick: the wall-clock time of night at that elapsed offset.
 *
 * The x domain stays in elapsed seconds, so every zoom and pan calculation is
 * unchanged; only the printed label is converted. Without a session start the
 * conversion has no origin, so the label falls back to the elapsed duration
 * rather than printing a wrong time.
 */
export function guideTimeTick(
  startedAt: string | null | undefined,
  seconds: number,
  opts: ClockOptions = {},
): string {
  if (!startedAt) return formatSecondsShort(seconds);
  return clockTime(startedAt, seconds, opts);
}

/** Tooltip title: same clock time as the axis, to the second. */
export function guideTooltipTitle(
  startedAt: string | null | undefined,
  seconds: number,
  opts: ClockOptions = {},
): string {
  if (!startedAt) return formatSecondsShort(seconds);
  return clockTimeWithSeconds(startedAt, seconds, opts);
}

/** Caption for the plotted slice: how much of the session is on screen. */
export function guideRangeCaption(
  view: GuideView | null,
  full: GuideView,
  startedAt?: string | null,
  opts: ClockOptions = {},
): string {
  if (!view) return "Error in arcseconds against the clock time of night.";
  const span = startedAt
    ? clockRange(startedAt, view.min, view.max, opts)
    : `${formatSecondsShort(view.min)} to ${formatSecondsShort(view.max)}`;
  return `Error in arcseconds, ${span} of ${formatSecondsShort(full.max)}.`;
}

/** Series the legend can switch off. RA, Dec and Star lost are chart datasets,
 *  in this order; Dither and Settling are drawn by the inline plugin. */
export type GuideSeriesKey = "ra" | "dec" | "dropped" | "dither" | "settle";

/** Dataset index of each toggleable dataset, matching buildDatasets order. */
const DATASET_SERIES: GuideSeriesKey[] = ["ra", "dec", "dropped"];

/** Legend entries, in display order. The swatch is a function so the nodes are
 *  built where they are rendered rather than at module load. */
const LEGEND_ITEMS: { key: GuideSeriesKey; label: string; swatch: () => JSX.Element }[] = [
  {
    key: "ra",
    label: "RA",
    swatch: () => <span class="inline-block w-3 h-0.5" style={{ "background-color": `var(${RA_COLOR_VAR})` }} />,
  },
  {
    key: "dec",
    label: "Dec",
    swatch: () => <span class="inline-block w-3 h-0.5" style={{ "background-color": `var(${DEC_COLOR_VAR})` }} />,
  },
  {
    key: "dropped",
    label: "Star lost",
    swatch: () => <span class="inline-block w-1.5 h-1.5 rounded-full" style={{ "background-color": `var(${DROP_COLOR_VAR})` }} />,
  },
  {
    key: "dither",
    label: "Dither",
    swatch: () => <span class="inline-block w-3 border-t border-dashed" style={{ "border-color": `var(${DITHER_COLOR_VAR})` }} />,
  },
  {
    key: "settle",
    label: "Settling",
    swatch: () => <span class="inline-block w-3 h-2 bg-white/10" />,
  },
];

/** Help text for the section, kept beside the component it documents. */
const GuideGraphHelp: Component = () => (
  <>
    <p class="text-sm text-theme-text-secondary">
      The graph plots PHD2 guiding error in arcseconds for each axis across the selected guiding
      session, against the local clock time of night. RA and Dec are drawn as separate traces, so a
      drift on one axis is distinguishable from seeing that moves both.
    </p>
    <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
      <li><strong class="text-theme-text-primary">Dither</strong>: a dashed vertical line at each dither command.</li>
      <li><strong class="text-theme-text-primary">Settling</strong>: a shaded band covering each settle window. A band in the drop colour is a settle that failed.</li>
      <li><strong class="text-theme-text-primary">Star lost</strong>: a point on the zero line at every frame where PHD2 lost the guide star.</li>
    </ul>
    <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
      <li>Scroll to zoom the time axis.</li>
      <li>Shift+scroll to zoom the arcsecond axis.</li>
      <li>Drag to pan while zoomed, double-click to reset both axes.</li>
      <li>Drag the corner grip to resize the plot.</li>
      <li>Click a legend entry to hide or show that series.</li>
      <li>Times on the axis and in the tooltip are the local clock time of night, not elapsed time.</li>
    </ul>
  </>
);

/**
 * Everything that reads the PHD2 queries lives here, and this component is
 * mounted under a <Suspense> boundary of its own.
 *
 * @tanstack/solid-query is built on createResource: reading `data` for a key
 * with nothing cached re-enters a pending resource and suspends the nearest
 * Suspense boundary. The app has exactly one, at the router root
 * (index.tsx:32), whose fallback is a full-screen "Loading...". With the
 * queries and their effects in the outer component, expanding this section
 * for the first time blanked the entire page and reset the scroll position,
 * which read as a page refresh. Keeping every query read inside a child of a
 * local boundary confines the fallback to this panel. Same failure mode as
 * DashboardSearchFocus.test.tsx documents for the sidebar search.
 */
const Phd2GuideGraphBody: Component<{
  sessionDate: string;
  telescope: string | null;
  height: number;
  onResize: (height: number) => void;
}> = (props) => {
  const settingsCtx = useSettingsContext();
  const [selectedId, setSelectedId] = createSignal<string | null>(null);
  // Null means the whole night. Only meaningful when the night mixes rigs.
  const [profileFilter, setProfileFilter] = createSignal<string | null>(null);
  // null means the whole session; a window means the user zoomed in.
  const [view, setView] = createSignal<GuideView | null>(null);
  const [yView, setYView] = createSignal<GuideView | null>(null);
  // Series the user switched off from the legend.
  const [hiddenSeries, setHiddenSeries] = createSignal<Set<GuideSeriesKey>>(new Set());
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | null = null;
  /** The exact canvas the live chart and its handlers are bound to. Solid does
   *  not clear a ref on unmount, so canvasRef alone cannot tell a live node
   *  from a detached one. */
  let boundCanvas: HTMLCanvasElement | null = null;
  let pendingRAF: number | null = null;
  /** True once a legend toggle has pushed dataset visibility into the chart.
   *  Visibility is only written when something is hidden or when the last
   *  hidden series has just been restored, so an all-visible chart never
   *  touches the API at all. */
  let visibilityApplied = false;

  const sessionsQuery = useQuery(() => ({
    queryKey: queryKeys.phd2Sessions(props.sessionDate, props.telescope),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient
        .GET("/api/phd2/sessions", {
          params: {
            query: {
              session_date: props.sessionDate,
              telescope: props.telescope ?? undefined,
            },
          },
          signal,
        })
        .then(unwrap) as unknown as Promise<Phd2SessionListResponse>,
    staleTime: 5 * 60_000,
  }));

  const sessions = (): Phd2SessionSummary[] => sessionsQuery.data?.sessions ?? [];

  const profileOptions = createMemo(() => guideProfileOptions(sessions()));

  const visibleSessions = createMemo(() =>
    filterSessionsByProfile(sessions(), profileFilter()),
  );

  // Moving to another night can retire the rig that was filtered on. Clearing
  // the filter is the only correct recovery: leaving it set would show an
  // empty panel on a night that has data.
  createEffect(() => {
    const chosen = profileFilter();
    if (chosen !== null && !profileOptions().includes(chosen)) setProfileFilter(null);
  });

  // Default to the first session long enough to be graded; a night of only
  // short sessions still gets a plot, just no gradeable RMS behind it. Reads
  // the filtered list, so choosing a rig also moves the selection onto it.
  createEffect(() => {
    const list = visibleSessions();
    if (list.length === 0) { setSelectedId(null); return; }
    const current = selectedId();
    if (current && list.some((s) => s.id === current)) return;
    setSelectedId((list.find((s) => !s.gated) ?? list[0]).id);
  });

  const framesQuery = useQuery(() => ({
    queryKey: queryKeys.phd2Frames(selectedId() ?? ""),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      apiClient
        .GET("/api/phd2/sessions/{id}/frames", {
          params: { path: { id: selectedId()! } },
          signal,
        })
        .then(unwrap) as unknown as Promise<Phd2FramesResponse>,
    enabled: !!selectedId(),
    staleTime: 5 * 60_000,
    // Switching sessions in the dropdown must not blank the panel: with the
    // previous response still in `data` the getter never re-enters a pending
    // resource, so the local Suspense boundary stays resolved.
    placeholderData: keepPreviousData,
  }));

  const startLabel = (session: Phd2SessionSummary) =>
    formatTime(session.started_at, settingsCtx.timezone(), settingsCtx.use24hTime());

  // Reads the visible list, not the night: once the user has filtered down to
  // one rig, repeating its name on every option is noise.
  const showProfile = () => new Set(visibleSessions().map(guideRigLabel)).size > 1;

  /** Elapsed-time extent of the whole session, the outer limit for any view. */
  const fullRange = createMemo<GuideView>(() => {
    const frames = framesQuery.data?.frames;
    if (!frames || frames.length === 0) return { min: 0, max: 0 };
    return { min: frames[0].t, max: frames[frames.length - 1].t };
  });

  /** Start of the selected guiding session, the origin every clock label is
   *  measured from. */
  const startedAtIso = (): string | null => framesQuery.data?.started_at ?? null;

  /** The axis, the tooltip and the caption read the same two display settings
   *  as the session dropdown beside them (`startLabel` below), so one panel
   *  never mixes a 12-hour selector with a 24-hour axis, or two zones. */
  const clockOptions = (): ClockOptions => ({
    hour12: !settingsCtx.use24hTime(),
    timeZone: settingsCtx.timezone(),
  });

  const isHidden = (key: GuideSeriesKey) => hiddenSeries().has(key);

  const toggleSeries = (key: GuideSeriesKey) =>
    setHiddenSeries((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // A new session means the previous windows are meaningless.
  createEffect(() => {
    selectedId();
    setView(null);
    setYView(null);
  });

  /**
   * Downsampling runs over the visible window, not the whole session, so
   * zooming in genuinely resolves a spike instead of magnifying the bucket
   * average that survived the first pass.
   */
  const plotted = createMemo<{ frames: Phd2Frame[]; total: number; events: Phd2Event[]; span: number }>(() => {
    const data = framesQuery.data;
    if (!data) return { frames: [], total: 0, events: [], span: 0 };
    const span = data.frames.length > 0 ? data.frames[data.frames.length - 1].t : 0;
    const v = view();
    const source = v ? sliceFramesByTime(data.frames, v.min, v.max) : data.frames;
    return {
      frames: downsampleGuideFrames(source, MAX_PLOT_POINTS),
      total: source.length,
      events: data.events,
      span,
    };
  });

  /** Vertical scale comes from the whole session, not from the plotted slice,
   *  so panning does not make the axis jump; a spike stays visibly a spike
   *  relative to the rest of it. */
  const yBound = createMemo(() => symmetricYBound(framesQuery.data?.frames ?? []));
  const yFullRange = createMemo<GuideView>(() => guideYRange(yBound()));

  // Mutable state read by the annotation plugin, refreshed before each build.
  let currentWindows: SettleWindow[] = [];
  let currentDithers: number[] = [];

  const guideEventPlugin = {
    id: "phd2GuideEvents",
    beforeDatasetsDraw(chart: Chart) {
      const xScale = chart.scales["x"];
      const yScale = chart.scales["y"];
      if (!xScale || !yScale || currentWindows.length === 0) return;
      const ctx = chart.ctx;
      const failedTint = `${getMetricColor(DROP_COLOR_VAR)}26`;
      ctx.save();
      // Zoomed in, most windows fall outside the axis; without a clip they
      // would paint over the tick labels and the surrounding card.
      ctx.beginPath();
      ctx.rect(xScale.left, yScale.top, xScale.right - xScale.left, yScale.bottom - yScale.top);
      ctx.clip();
      for (const w of currentWindows) {
        const x0 = xScale.getPixelForValue(w.start);
        const x1 = xScale.getPixelForValue(w.end);
        const left = Math.min(x0, x1);
        const width = Math.max(2, Math.abs(x1 - x0));
        ctx.fillStyle = w.failed ? failedTint : "rgba(255,255,255,0.06)";
        ctx.fillRect(left, yScale.top, width, yScale.bottom - yScale.top);
      }
      ctx.restore();
    },
    afterDatasetsDraw(chart: Chart) {
      const xScale = chart.scales["x"];
      const yScale = chart.scales["y"];
      if (!xScale || !yScale || currentDithers.length === 0) return;
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.rect(xScale.left, yScale.top, xScale.right - xScale.left, yScale.bottom - yScale.top);
      ctx.clip();
      ctx.strokeStyle = getMetricColor(DITHER_COLOR_VAR);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      for (const t of currentDithers) {
        const x = xScale.getPixelForValue(t);
        ctx.beginPath();
        ctx.moveTo(x, yScale.top);
        ctx.lineTo(x, yScale.bottom);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.restore();
    },
  };

  const buildDatasets = (frames: Phd2Frame[]): any[] => {
    const raColor = getMetricColor(RA_COLOR_VAR);
    const decColor = getMetricColor(DEC_COLOR_VAR);
    const dropColor = getMetricColor(DROP_COLOR_VAR);
    // `any[]`: chart.js's ChartDataset union does not admit the mixed
    // line/scatter shape below, and SessionMetricsChart.tsx types its dataset
    // array the same way.
    return [
      {
        label: "RA",
        data: frames.map((f) => ({ x: f.t, y: f.ra })),
        borderColor: raColor,
        backgroundColor: `${raColor}33`,
        borderWidth: 1,
        pointRadius: 0,
        pointHitRadius: 6,
        tension: 0,
        spanGaps: false,
      },
      {
        label: "Dec",
        data: frames.map((f) => ({ x: f.t, y: f.dec })),
        borderColor: decColor,
        backgroundColor: `${decColor}33`,
        borderWidth: 1,
        pointRadius: 0,
        pointHitRadius: 6,
        tension: 0,
        spanGaps: false,
      },
      {
        label: "Star lost",
        data: frames.filter((f) => f.dropped).map((f) => ({ x: f.t, y: 0 })),
        borderColor: dropColor,
        backgroundColor: dropColor,
        showLine: false,
        pointRadius: 2.5,
        pointHitRadius: 6,
      },
    ];
  };

  /** Pointer position in the units of one axis, or null before the chart is
   *  built. Both axes are read the same way, so they share this. */
  const valueAtPointer = (axis: "x" | "y", client: number): number | null => {
    if (!chartInstance || !boundCanvas) return null;
    const scale = chartInstance.scales[axis];
    if (!scale) return null;
    const rect = boundCanvas.getBoundingClientRect();
    const px = client - (axis === "x" ? rect.left : rect.top);
    return scale.getValueForPixel(px) ?? null;
  };

  const currentView = (): GuideView => view() ?? fullRange();
  const currentYView = (): GuideView => yView() ?? yFullRange();

  const onWheel = (e: WheelEvent) => {
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    // Shift is the modifier every other zoomable chart uses for the other
    // axis, and it leaves the plain wheel doing the common thing.
    if (e.shiftKey) {
      const full = yFullRange();
      if (!(full.max > full.min)) return;
      e.preventDefault();
      const cursor = valueAtPointer("y", e.clientY);
      if (cursor === null) return;
      const next = zoomGuideView(currentYView(), full, cursor, factor, MIN_GUIDE_Y_SPAN);
      // Only a window back at the data's own width drops the override. Wider
      // than that is a zoomed-out reading of a calm night and has to be kept.
      setYView(isFullGuideView(next, full) ? null : next);
      return;
    }
    const full = fullRange();
    if (!(full.max > full.min)) return;
    e.preventDefault();
    const cursor = valueAtPointer("x", e.clientX);
    if (cursor === null) return;
    const next = zoomGuideView(currentView(), full, cursor, factor, MIN_GUIDE_VIEW_SPAN);
    setView(next.max - next.min >= full.max - full.min ? null : next);
  };

  // Drag state is a plain variable, not a signal: it anchors on the windows the
  // drag started from, so the pan cannot chase its own updates.
  let dragAnchor: { x: number; y: number; view: GuideView; yView: GuideView | null } | null = null;

  /** Axis units per pixel of plot area, constant while a pan runs. */
  const unitsPerPixel = (axis: "x" | "y"): number | null => {
    if (!chartInstance) return null;
    const scale = chartInstance.scales[axis] as
      | { min: number; max: number; left: number; right: number; top: number; bottom: number }
      | undefined;
    if (!scale) return null;
    const extent = axis === "x" ? scale.right - scale.left : scale.bottom - scale.top;
    if (!(extent > 0)) return null;
    return (scale.max - scale.min) / extent;
  };

  const onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0) return;
    const v = view();
    const yv = yView();
    // Nothing to pan while both axes show everything there is.
    if (!v && !yv) return;
    dragAnchor = { x: e.clientX, y: e.clientY, view: v ?? fullRange(), yView: yv };
    // Capture keeps a drag alive when the pointer leaves the canvas. It throws
    // when the pointer id is no longer active, which the pan does not care
    // about, so it must not take the handler down with it.
    try { boundCanvas?.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!dragAnchor) return;
    const perPixelX = unitsPerPixel("x");
    if (perPixelX !== null && view()) {
      // Drag right, the window moves earlier: the data follows the pointer.
      const shift = -(e.clientX - dragAnchor.x) * perPixelX;
      setView(panGuideView(dragAnchor.view, fullRange(), shift));
    }
    const anchorY = dragAnchor.yView;
    if (!anchorY) return; // Vertical is at full extent, so there is no slack.
    const perPixelY = unitsPerPixel("y");
    if (perPixelY === null) return;
    // Pixels run down, arcseconds run up, so a downward drag raises the window.
    const shiftY = (e.clientY - dragAnchor.y) * perPixelY;
    setYView(panGuideView(anchorY, yFullRange(), shiftY, MIN_GUIDE_Y_SPAN));
  };

  const endDrag = (e: PointerEvent) => {
    if (!dragAnchor) return;
    dragAnchor = null;
    if (boundCanvas?.hasPointerCapture(e.pointerId)) boundCanvas.releasePointerCapture(e.pointerId);
  };

  const onDoubleClick = () => { setView(null); setYView(null); };

  const attachHandlers = (canvas: HTMLCanvasElement) => {
    // passive:false so preventDefault stops the page scrolling under the wheel.
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
    canvas.addEventListener("dblclick", onDoubleClick);
  };

  const detachHandlers = (canvas: HTMLCanvasElement) => {
    canvas.removeEventListener("wheel", onWheel);
    canvas.removeEventListener("pointerdown", onPointerDown);
    canvas.removeEventListener("pointermove", onPointerMove);
    canvas.removeEventListener("pointerup", endDrag);
    canvas.removeEventListener("pointercancel", endDrag);
    canvas.removeEventListener("dblclick", onDoubleClick);
  };

  const destroyChart = () => {
    // Detach from the node the handlers were actually put on, not from
    // whatever canvasRef points at now: by the time a chart is torn down the
    // ref may already name a different canvas.
    if (boundCanvas) { detachHandlers(boundCanvas); boundCanvas = null; }
    visibilityApplied = false;
    if (!chartInstance) return;
    chartInstance.destroy();
    chartInstance = null;
  };

  const syncChart = () => {
    if (!canvasRef) return;
    const { frames, events, span } = plotted();

    if (frames.length === 0) { destroyChart(); return; }

    // The canvas lives behind the pixel-scale gate, so picking a session whose
    // log header has no scale unmounts it while the frame count stays high (a
    // null scale nulls every ra and dec but the frames are still there).
    // Picking a scaled session again mounts a fresh canvas, and the old chart
    // would go on drawing into the detached one, leaving the panel blank until
    // it was collapsed and reopened. Rebuild whenever the node changes.
    if (boundCanvas && boundCanvas !== canvasRef) destroyChart();

    // A legend entry switched off removes the overlay outright rather than
    // drawing it dimmed: the plugin reads these two lists and nothing else.
    const hidden = hiddenSeries();
    currentWindows = hidden.has("settle") ? [] : settleWindows(events, span);
    currentDithers = hidden.has("dither")
      ? []
      : events.filter((e) => e.type === "dither").map((e) => e.t);

    const window = clampGuideView(currentView(), fullRange());
    const yWindow = clampGuideView(currentYView(), yFullRange(), MIN_GUIDE_Y_SPAN);
    const datasets = buildDatasets(frames);

    /** Push legend state into the chart. Skipped entirely while everything is
     *  visible and nothing has ever been hidden. */
    const applyVisibility = () => {
      if (!chartInstance) return false;
      if (hidden.size === 0 && !visibilityApplied) return false;
      DATASET_SERIES.forEach((key, i) => chartInstance!.setDatasetVisibility(i, !hidden.has(key)));
      visibilityApplied = hidden.size > 0;
      return true;
    };

    if (chartInstance) {
      chartInstance.data.datasets = datasets;
      const scales = chartInstance.options.scales as
        | { x?: { min?: number; max?: number }; y?: { min?: number; max?: number } }
        | undefined;
      if (scales?.y) { scales.y.min = yWindow.min; scales.y.max = yWindow.max; }
      if (scales?.x) { scales.x.min = window.min; scales.x.max = window.max; }
      applyVisibility();
      chartInstance.update("none");
      return;
    }

    chartInstance = new Chart(canvasRef, {
      type: "line",
      data: { datasets },
      plugins: [guideEventPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(0,0,0,0.8)",
            titleFont: { size: chartFontSize.tooltipTitle() },
            bodyFont: { size: chartFontSize.tooltipBody() },
            padding: 8,
            callbacks: {
              title: (items) =>
                items.length > 0
                  ? guideTooltipTitle(startedAtIso(), Number(items[0].parsed.x), clockOptions())
                  : "",
              label: (item) =>
                guideTooltipLabel(String(item.dataset.label ?? ""), Number(item.parsed.y)),
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            min: window.min,
            max: window.max,
            // Domain stays in elapsed seconds so the zoom and pan arithmetic is
            // untouched; only the label is converted to wall-clock time.
            title: {
              display: true,
              text: "Time of night",
              color: "#64748b",
              font: { size: chartFontSize.tick() },
              padding: 0,
            },
            ticks: {
              color: "#64748b",
              font: { size: chartFontSize.tick() },
              maxTicksLimit: 10,
              callback: (value) => guideTimeTick(startedAtIso(), Number(value), clockOptions()),
            },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
          y: {
            type: "linear",
            min: yWindow.min,
            max: yWindow.max,
            ticks: {
              color: "#64748b",
              font: { size: chartFontSize.tick() },
              callback: (value) => Number(value).toFixed(1),
            },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
        },
      },
    });
    boundCanvas = canvasRef;
    attachHandlers(canvasRef);
    // A rebuild (session switch, canvas swap) has to re-apply whatever the
    // legend had switched off.
    if (applyVisibility()) chartInstance?.update("none");
  };

  createEffect(() => {
    // Track the plotted slice, both current windows, and the legend state.
    plotted();
    view();
    yView();
    hiddenSeries();
    // The tick and tooltip callbacks are installed once, at construction, and
    // read the settings when they run. Tracking them here is what redraws the
    // axis after the display setting changes under an open panel.
    settingsCtx.use24hTime();
    settingsCtx.timezone();
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    pendingRAF = requestAnimationFrame(() => {
      pendingRAF = null;
      // The canvas sits behind several <Show> gates, so on the first pass it
      // may not exist yet; retry on the next macrotask.
      if (!canvasRef) { setTimeout(() => syncChart(), 0); return; }
      syncChart();
    });
  });

  /**
   * Drag-to-resize, mirroring the mosaic arranger's grip
   * (`components/mosaics/KonvaMosaicArranger.tsx:375`): corner grip, document
   * level mousemove and mouseup, height only, floor clamp, no persistence.
   * The chart is resized in place rather than rebuilt, so the canvas node the
   * handlers are bound to never changes.
   */
  const onResizeHandleDown = (e: MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = props.height;
    const onMove = (ev: MouseEvent) => {
      props.onResize(Math.max(MIN_GRAPH_HEIGHT, startHeight + ev.clientY - startY));
      chartInstance?.resize();
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      chartInstance?.resize();
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  onCleanup(() => {
    if (pendingRAF !== null) cancelAnimationFrame(pendingRAF);
    destroyChart();
  });

  return (
    <div class="p-3 space-y-2">
      <Show when={sessions().length > 0} fallback={
        <div class="text-xs text-theme-text-secondary">No PHD2 data for this session</div>
      }>
        <div class="flex flex-wrap items-center gap-3">
          <Show when={profileOptions().length > 1}>
            <select
              aria-label="Guiding rig"
              class="px-2.5 py-1 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
              value={profileFilter() ?? ""}
              onChange={(e) => setProfileFilter(e.currentTarget.value || null)}
            >
              <option value="">All rigs</option>
              <For each={profileOptions()}>
                {(profile) => <option value={profile}>{profile}</option>}
              </For>
            </select>
          </Show>
          <Show when={visibleSessions().length > 1}>
            <select
              aria-label="Guiding session"
              class="px-2.5 py-1 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
              value={selectedId() ?? ""}
              onChange={(e) => setSelectedId(e.currentTarget.value)}
            >
              <For each={visibleSessions()}>
                {(s) => <option value={s.id}>{sessionOptionLabel(s, startLabel(s), showProfile())}</option>}
              </For>
            </select>
          </Show>
          {/* Custom legend: chart.js's own is disabled because the dither and
              settle overlays are drawn by a plugin and have no dataset to
              stand for them. Each entry carries the same toggle semantics as
              the built-in legend, so a click hides the series and strikes the
              entry through, and a second click restores it. */}
          <div class="flex flex-wrap items-center gap-1 text-tiny text-theme-text-tertiary">
            <For each={LEGEND_ITEMS}>
              {(item) => (
                <button
                  type="button"
                  class="flex items-center gap-1 px-1 py-0.5 rounded-[var(--radius-sm)] cursor-pointer hover:bg-theme-hover hover:text-theme-text-primary transition-colors"
                  classList={{ "line-through opacity-50": isHidden(item.key) }}
                  aria-pressed={!isHidden(item.key)}
                  title={isHidden(item.key) ? `Show ${item.label}` : `Hide ${item.label}`}
                  onClick={() => toggleSeries(item.key)}
                >
                  {item.swatch()}
                  {item.label}
                </button>
              )}
            </For>
          </div>
          <span class="text-tiny text-theme-text-tertiary">
            Scroll to zoom, Shift+scroll for vertical, drag to pan, double-click to reset
          </span>
        </div>

        <Show when={!isScaleMissing(framesQuery.data)} fallback={
          <div class="text-xs text-theme-text-secondary">
            No pixel scale in this session's log header, so guiding error cannot be shown in arcseconds
          </div>
        }>
          <Show when={plotted().frames.length > 0} fallback={
            <div class="text-xs text-theme-text-secondary">No guide frames for this session</div>
          }>
            <div class="select-none" style={{ height: `${props.height}px` }}>
              <canvas ref={canvasRef} />
            </div>
            <div class="text-tiny text-theme-text-tertiary pr-6">
              {guideRangeCaption(view(), fullRange(), startedAtIso(), clockOptions())}
            </div>
            {/* Anchored to the section panel, which is the nearest positioned
                ancestor, not to the plot. Over the plot it covered the last
                axis label and ate the wheel and drag gestures in that corner. */}
            <div
              class="absolute bottom-1 right-1 w-5 h-5 cursor-nwse-resize opacity-40 hover:opacity-80 transition-opacity"
              style={{ "z-index": "10" }}
              onMouseDown={onResizeHandleDown}
            >
              <svg viewBox="0 0 20 20" class="w-full h-full text-theme-text-secondary">
                <line x1="18" y1="4" x2="4" y2="18" stroke="currentColor" stroke-width="1.5" />
                <line x1="18" y1="9" x2="9" y2="18" stroke="currentColor" stroke-width="1.5" />
                <line x1="18" y1="14" x2="14" y2="18" stroke="currentColor" stroke-width="1.5" />
              </svg>
            </div>
          </Show>
        </Show>
      </Show>
    </div>
  );
};

const Phd2GuideGraph: Component<{ sessionDate: string; telescope: string | null }> = (props) => {
  const [expanded, setExpanded] = createSignal(false);
  // Held here, not in the body, so a height the user dragged out survives
  // collapsing and reopening the section. Like the mosaic arranger it is not
  // persisted any further than that.
  const [graphHeight, setGraphHeight] = createSignal(DEFAULT_GRAPH_HEIGHT);

  // The panel is `relative` so the body's resize grip anchors to this corner
  // rather than to the plot it used to sit on top of.
  return (
    <div class="relative bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
      {/* Header geometry is the sibling sections' in SessionAccordionCard
          (Session Metrics, Per-Frame Data, FITS Headers): same full-width row,
          same padding and text size, same hover, title left behind the accent
          rule, chevron hard against the right edge.
          Those siblings are a single <button>. This section also carries a help
          glyph, and a button cannot contain another button, so the row itself is
          the click target and the title is the focusable control inside it. The
          click handler sits on the row, not on the title, so a click on either
          toggles exactly once. Keyboard users activate the title button, whose
          click bubbles to the same handler.
          The glyph appears only while the section is open: collapsed, the row
          reads exactly like its siblings. */}
      <div
        class="flex items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
        classList={{ "text-theme-text-primary": expanded(), "text-theme-text-secondary": !expanded() }}
        onClick={() => setExpanded((v) => !v)}
      >
        <button
          type="button"
          class="font-semibold border-l-2 border-theme-accent pl-2 text-left cursor-pointer"
          aria-expanded={expanded()}
        >
          Guide Graph (PHD2)
        </button>
        <Show when={expanded()}>
          {/* Same placement as every other section help: immediately after the
              title, in the same row, `gap-2` worth of space. */}
          <div class="ml-2 flex items-center">
            <HelpPopover title="Guide Graph (PHD2)" label="About the guide graph">
              <GuideGraphHelp />
            </HelpPopover>
          </div>
        </Show>
        <svg
          class={`ml-auto shrink-0 w-3.5 h-3.5 transition-transform duration-200 ${expanded() ? "rotate-180" : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
        </svg>
      </div>

      <Show when={expanded()}>
        <Suspense fallback={
          <div class="p-3 text-xs text-theme-text-secondary">Loading guiding data...</div>
        }>
          <Phd2GuideGraphBody
            sessionDate={props.sessionDate}
            telescope={props.telescope}
            height={graphHeight()}
            onResize={setGraphHeight}
          />
        </Suspense>
      </Show>
    </div>
  );
};

export default Phd2GuideGraph;
