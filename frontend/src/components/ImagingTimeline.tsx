import { Component, For, Show, createMemo, createSignal, onMount, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { TimelineDetailEntry } from "../types";

// Zoom range: 1-20. Thresholds for granularity transitions.
const ZOOM_MONTHLY_MAX = 4;
const ZOOM_WEEKLY_MAX = 10;
const MIN_ZOOM = 1;
const MAX_ZOOM = 20;

const BAR_BASE_WIDTH = 28;
const BAR_GAP = 2;
const BAR_AREA_HEIGHT = 220;

type Preset = "all" | "1y" | "q" | "m" | "w";
type DailyMode = "imaged" | "all";
type Granularity = "monthly" | "weekly" | "daily";

interface Props {
  monthly: TimelineDetailEntry[];
  weekly: TimelineDetailEntry[];
  daily: TimelineDetailEntry[];
}

/** Map a preset to a zoom level */
function presetToZoom(preset: Preset): number {
  switch (preset) {
    case "all": return 1;
    case "1y": return 2;
    case "q": return 5;
    case "m": return 11;
    case "w": return 16;
  }
}

function granularityForZoom(z: number): Granularity {
  if (z <= ZOOM_MONTHLY_MAX) return "monthly";
  if (z <= ZOOM_WEEKLY_MAX) return "weekly";
  return "daily";
}

/** Format a period string for x-axis labels */
function formatLabel(period: string, gran: Granularity): string {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  if (gran === "monthly") {
    const [y, m] = period.split("-");
    return `${months[parseInt(m, 10) - 1]} ${y}`;
  }
  if (gran === "weekly") {
    // "2025-W03" → "W3 '25"
    const parts = period.split("-W");
    return `W${parseInt(parts[1])} '${parts[0].slice(2)}`;
  }
  // daily: "2025-12-03" → "Dec 3"
  const [, m, d] = period.split("-");
  return `${months[parseInt(m, 10) - 1]} ${parseInt(d, 10)}`;
}

/** Compute date_from and date_to for click navigation */
function periodToDateRange(period: string, gran: Granularity): { from: string; to: string } {
  if (gran === "monthly") {
    const [y, m] = period.split("-").map(Number);
    const lastDay = new Date(y, m, 0).getDate();
    return { from: period + "-01", to: `${period}-${String(lastDay).padStart(2, "0")}` };
  }
  if (gran === "weekly") {
    const parts = period.split("-W");
    const year = parseInt(parts[0]);
    const week = parseInt(parts[1]);
    const jan4 = new Date(year, 0, 4);
    const startOfWeek1 = new Date(jan4);
    startOfWeek1.setDate(jan4.getDate() - jan4.getDay() + 1);
    const monday = new Date(startOfWeek1);
    monday.setDate(startOfWeek1.getDate() + (week - 1) * 7);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    return { from: fmt(monday), to: fmt(sunday) };
  }
  return { from: period, to: period };
}

/** Generate all dates between first and last entry */
function allDatesBetween(data: TimelineDetailEntry[]): string[] {
  if (data.length === 0) return [];
  const start = new Date(data[0].period);
  const end = new Date(data[data.length - 1].period);
  const dates: string[] = [];
  const cur = new Date(start);
  while (cur <= end) {
    dates.push(cur.toISOString().slice(0, 10));
    cur.setDate(cur.getDate() + 1);
  }
  return dates;
}

const ImagingTimeline: Component<Props> = (props) => {
  const navigate = useNavigate();
  const [zoom, setZoom] = createSignal(1);
  const [activePreset, setActivePreset] = createSignal<Preset | null>("all");
  const [dailyMode, setDailyMode] = createSignal<DailyMode>("imaged");

  // Drag-to-pan state
  const [isDragging, setIsDragging] = createSignal(false);
  let dragStartX = 0;
  let dragScrollStart = 0;
  let didDrag = false;

  let containerRef!: HTMLDivElement;

  const granularity = createMemo(() => granularityForZoom(zoom()));

  /** Active dataset based on zoom level */
  const activeData = createMemo((): TimelineDetailEntry[] => {
    const gran = granularity();
    if (gran === "monthly") return props.monthly;
    if (gran === "weekly") return props.weekly;

    if (dailyMode() === "all") {
      const allDates = allDatesBetween(props.daily);
      const dataMap = new Map(props.daily.map(e => [e.period, e]));
      return allDates.map(d => dataMap.get(d) ?? { period: d, integration_seconds: 0, efficiency_pct: null });
    }
    return props.daily;
  });

  const maxVal = createMemo(() => Math.max(...activeData().map(e => e.integration_seconds), 1));

  const barWidth = createMemo(() => BAR_BASE_WIDTH * (zoom() / MIN_ZOOM));

  const innerWidth = createMemo(() => activeData().length * (barWidth() + BAR_GAP));

  const labelInterval = createMemo(() => {
    const w = barWidth();
    if (w >= 50) return 1;
    if (w >= 35) return 2;
    if (w >= 25) return 3;
    return 4;
  });

  const showEfficiency = createMemo(() => barWidth() >= 36);

  const formatHours = (secs: number): string => {
    const h = secs / 3600;
    return h < 10 ? `${h.toFixed(1)}h` : `${Math.round(h)}h`;
  };

  // --- Preset navigation ---
  const applyPreset = (preset: Preset) => {
    setActivePreset(preset);
    const z = presetToZoom(preset);
    setZoom(z);
    requestAnimationFrame(() => {
      if (containerRef) {
        containerRef.scrollLeft = containerRef.scrollWidth;
      }
    });
  };

  // --- Scroll-to-zoom ---
  const handleWheel = (e: WheelEvent) => {
    e.preventDefault();
    const rect = containerRef.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const scrollBefore = containerRef.scrollLeft;
    const posInContent = scrollBefore + mouseX;
    const oldZoom = zoom();

    const delta = e.deltaY > 0 ? -0.3 : 0.3;
    const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom + delta * oldZoom));
    setZoom(newZoom);
    setActivePreset(null);

    requestAnimationFrame(() => {
      const scale = newZoom / oldZoom;
      containerRef.scrollLeft = posInContent * scale - mouseX;
    });
  };

  // --- Drag to pan ---
  const handleMouseDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    setIsDragging(true);
    didDrag = false;
    dragStartX = e.clientX;
    dragScrollStart = containerRef.scrollLeft;
    e.preventDefault();
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging()) return;
    const dx = e.clientX - dragStartX;
    if (Math.abs(dx) > 3) didDrag = true;
    containerRef.scrollLeft = dragScrollStart - dx;
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  // --- Touch: pinch-to-zoom + single-finger pan ---
  let lastTouchDist = 0;
  let lastTouchX = 0;

  const getTouchDist = (touches: TouchList): number => {
    if (touches.length < 2) return 0;
    const dx = touches[1].clientX - touches[0].clientX;
    const dy = touches[1].clientY - touches[0].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  };

  const handleTouchStart = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      lastTouchDist = getTouchDist(e.touches);
    } else if (e.touches.length === 1) {
      lastTouchX = e.touches[0].clientX;
    }
  };

  const handleTouchMove = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dist = getTouchDist(e.touches);
      if (lastTouchDist > 0) {
        const scale = dist / lastTouchDist;
        const oldZoom = zoom();
        const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom * scale));
        setZoom(newZoom);
        setActivePreset(null);
      }
      lastTouchDist = dist;
    } else if (e.touches.length === 1) {
      const dx = e.touches[0].clientX - lastTouchX;
      containerRef.scrollLeft -= dx;
      lastTouchX = e.touches[0].clientX;
    }
  };

  const handleTouchEnd = () => {
    lastTouchDist = 0;
  };

  // --- Bar click ---
  const handleBarClick = (entry: TimelineDetailEntry) => {
    if (didDrag) return;
    const range = periodToDateRange(entry.period, granularity());
    navigate(`/?date_from=${range.from}&date_to=${range.to}`);
  };

  // --- Mount/cleanup ---
  onMount(() => {
    containerRef.addEventListener("wheel", handleWheel, { passive: false });
    containerRef.addEventListener("touchstart", handleTouchStart, { passive: false });
    containerRef.addEventListener("touchmove", handleTouchMove, { passive: false });
    containerRef.addEventListener("touchend", handleTouchEnd);
    requestAnimationFrame(() => {
      if (containerRef) containerRef.scrollLeft = containerRef.scrollWidth;
    });
  });

  onCleanup(() => {
    containerRef?.removeEventListener("wheel", handleWheel);
    containerRef?.removeEventListener("touchstart", handleTouchStart);
    containerRef?.removeEventListener("touchmove", handleTouchMove);
    containerRef?.removeEventListener("touchend", handleTouchEnd);
  });

  const presets: { key: Preset; label: string }[] = [
    { key: "all", label: "All" },
    { key: "1y", label: "1Y" },
    { key: "q", label: "Q" },
    { key: "m", label: "M" },
    { key: "w", label: "W" },
  ];

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      {/* Header */}
      <div class="flex items-center justify-between flex-wrap gap-2">
        <h3 class="text-white font-medium text-sm">Imaging Timeline</h3>
        <div class="flex items-center gap-3">
          {/* Daily mode toggle */}
          <Show when={granularity() === "daily"}>
            <div class="flex gap-0.5">
              <button
                class={`px-2 py-0.5 text-xs rounded ${dailyMode() === "imaged" ? "bg-theme-accent text-white" : "bg-theme-surface-alt text-theme-text-secondary"}`}
                onClick={() => setDailyMode("imaged")}
              >Imaged only</button>
              <button
                class={`px-2 py-0.5 text-xs rounded ${dailyMode() === "all" ? "bg-theme-accent text-white" : "bg-theme-surface-alt text-theme-text-secondary"}`}
                onClick={() => setDailyMode("all")}
              >All nights</button>
            </div>
          </Show>
          {/* Presets */}
          <div class="flex gap-0.5">
            <For each={presets}>
              {(p) => (
                <button
                  class={`px-2 py-0.5 text-xs rounded ${activePreset() === p.key ? "bg-theme-accent text-white" : "bg-theme-surface-alt text-theme-text-secondary hover:text-white"}`}
                  onClick={() => applyPreset(p.key)}
                >{p.label}</button>
              )}
            </For>
          </div>
          <span class="text-micro text-theme-text-secondary select-none hidden sm:inline">
            Scroll to zoom · Drag to pan
          </span>
        </div>
      </div>

      {/* Chart area */}
      <div
        ref={containerRef}
        class="overflow-x-auto scrollbar-thin select-none"
        style={{
          "scroll-behavior": "auto",
          cursor: isDragging() ? "grabbing" : "grab",
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <div style={{ width: `${innerWidth()}px`, "min-width": "100%" }}>
          {/* Bars with labels above */}
          <div class="flex items-end" style={{ height: `${BAR_AREA_HEIGHT}px`, gap: `${BAR_GAP}px` }}>
            <For each={activeData()}>
              {(entry, i) => {
                const pct = () => (entry.integration_seconds / maxVal()) * 100;
                const isEmpty = () => entry.integration_seconds === 0;
                return (
                  <div
                    class="h-full flex flex-col items-center justify-end"
                    style={{ width: `${barWidth()}px`, "flex-shrink": "0" }}
                  >
                    {/* Efficiency label */}
                    <Show when={showEfficiency() && entry.efficiency_pct != null}>
                      <span class="text-green-400 leading-none mb-0.5" style={{ "font-size": "0.6rem" }}>
                        {entry.efficiency_pct}%
                      </span>
                    </Show>
                    {/* Hour label */}
                    <Show when={!isEmpty() && i() % labelInterval() === 0}>
                      <span class="text-theme-accent leading-none mb-0.5" style={{ "font-size": "0.65rem" }}>
                        {formatHours(entry.integration_seconds)}
                      </span>
                    </Show>
                    {/* Bar */}
                    <div
                      class={`w-full rounded-t transition-colors ${isEmpty() ? "" : "bg-theme-accent hover:brightness-125 cursor-pointer"}`}
                      style={{ height: isEmpty() ? "0px" : `${Math.max(pct(), 1)}%`, "min-height": isEmpty() ? "0" : "2px" }}
                      onClick={() => !isEmpty() && handleBarClick(entry)}
                    />
                  </div>
                );
              }}
            </For>
          </div>

          {/* X-axis labels */}
          <div class="flex mt-1" style={{ gap: `${BAR_GAP}px` }}>
            <For each={activeData()}>
              {(entry, i) => (
                <div
                  class="text-center"
                  style={{ width: `${barWidth()}px`, "flex-shrink": "0" }}
                >
                  <span class="text-micro text-theme-text-secondary whitespace-nowrap">
                    {i() % labelInterval() === 0 ? formatLabel(entry.period, granularity()) : ""}
                  </span>
                </div>
              )}
            </For>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ImagingTimeline;
