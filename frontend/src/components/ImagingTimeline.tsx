import { Component, For, createMemo, createSignal, onMount, onCleanup } from "solid-js";
import type { TimelineEntry } from "../types";

const MIN_ZOOM = 1;
const MAX_ZOOM = 8;
const BAR_BASE_WIDTH = 28; // px per bar at zoom 1
const BAR_GAP = 2;

const ImagingTimeline: Component<{ timeline: TimelineEntry[] }> = (props) => {
  const maxVal = () => Math.max(...props.timeline.map((t) => t.integration_seconds), 1);

  const [zoom, setZoom] = createSignal(1);
  let containerRef!: HTMLDivElement;

  const labelInterval = createMemo(() => {
    const z = zoom();
    if (z >= 4) return 1;
    if (z >= 2) return 2;
    const len = props.timeline.length;
    if (len <= 12) return 1;
    if (len <= 18) return 2;
    if (len <= 30) return 3;
    return 4;
  });

  const innerWidth = createMemo(() => {
    const count = props.timeline.length;
    return count * (BAR_BASE_WIDTH * zoom() + BAR_GAP);
  });

  const formatLabel = (month: string) => {
    const [y, m] = month.split("-");
    const names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${names[parseInt(m, 10) - 1]} ${y}`;
  };

  // Scroll to right end (newest) on mount
  onMount(() => {
    if (containerRef) {
      containerRef.scrollLeft = containerRef.scrollWidth;
    }
  });

  // Zoom via Ctrl+wheel, pan via plain wheel
  const handleWheel = (e: WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const rect = containerRef.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const scrollBefore = containerRef.scrollLeft;
      const posInContent = scrollBefore + mouseX;
      const oldZoom = zoom();

      const delta = e.deltaY > 0 ? -0.15 : 0.15;
      const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom + delta * oldZoom));
      setZoom(newZoom);

      // Keep the point under the cursor stable
      requestAnimationFrame(() => {
        const scale = newZoom / oldZoom;
        containerRef.scrollLeft = posInContent * scale - mouseX;
      });
    }
  };

  // Touch pinch-to-zoom
  let lastTouchDist = 0;
  let lastTouchCenter = 0;

  const getTouchDist = (touches: TouchList): number => {
    if (touches.length < 2) return 0;
    const dx = touches[1].clientX - touches[0].clientX;
    const dy = touches[1].clientY - touches[0].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  };

  const getTouchCenter = (touches: TouchList): number => {
    if (touches.length < 2) return touches[0].clientX;
    return (touches[0].clientX + touches[1].clientX) / 2;
  };

  const handleTouchStart = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      lastTouchDist = getTouchDist(e.touches);
      lastTouchCenter = getTouchCenter(e.touches);
    }
  };

  const handleTouchMove = (e: TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dist = getTouchDist(e.touches);
      const center = getTouchCenter(e.touches);

      if (lastTouchDist > 0) {
        const scale = dist / lastTouchDist;
        const rect = containerRef.getBoundingClientRect();
        const centerX = center - rect.left;
        const scrollBefore = containerRef.scrollLeft;
        const posInContent = scrollBefore + centerX;
        const oldZoom = zoom();
        const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, oldZoom * scale));
        setZoom(newZoom);

        requestAnimationFrame(() => {
          const zoomScale = newZoom / oldZoom;
          containerRef.scrollLeft = posInContent * zoomScale - centerX;
        });
      }

      lastTouchDist = dist;
      lastTouchCenter = center;
    }
  };

  const handleTouchEnd = () => {
    lastTouchDist = 0;
    lastTouchCenter = 0;
  };

  onMount(() => {
    containerRef.addEventListener("wheel", handleWheel, { passive: false });
    containerRef.addEventListener("touchstart", handleTouchStart, { passive: false });
    containerRef.addEventListener("touchmove", handleTouchMove, { passive: false });
    containerRef.addEventListener("touchend", handleTouchEnd);
  });
  onCleanup(() => {
    containerRef?.removeEventListener("wheel", handleWheel);
    containerRef?.removeEventListener("touchstart", handleTouchStart);
    containerRef?.removeEventListener("touchmove", handleTouchMove);
    containerRef?.removeEventListener("touchend", handleTouchEnd);
  });

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <div class="flex items-center justify-between">
        <h3 class="text-white font-medium text-sm">Imaging Timeline</h3>
        <span class="text-caption text-theme-text-secondary select-none">
          <span class="hidden sm:inline">Ctrl+Scroll to zoom</span>
          <span class="sm:hidden">Pinch to zoom</span>
        </span>
      </div>
      <div
        ref={containerRef}
        class="overflow-x-auto scrollbar-thin"
        style={{ "scroll-behavior": "auto" }}
      >
        <div style={{ width: `${innerWidth()}px`, "min-width": "100%" }}>
          {/* Bars */}
          <div class="flex items-end h-36" style={{ gap: `${BAR_GAP}px` }}>
            <For each={props.timeline}>
              {(entry) => {
                const pct = () => (entry.integration_seconds / maxVal()) * 100;
                return (
                  <div
                    class="h-full flex items-end"
                    style={{ width: `${BAR_BASE_WIDTH * zoom()}px`, "flex-shrink": "0" }}
                    title={`${formatLabel(entry.month)}: ${(entry.integration_seconds / 3600).toFixed(1)}h`}
                  >
                    <div
                      class="w-full bg-theme-accent rounded-t min-h-[2px]"
                      style={{ height: `${pct()}%` }}
                    />
                  </div>
                );
              }}
            </For>
          </div>
          {/* Labels */}
          <div class="flex mt-1" style={{ gap: `${BAR_GAP}px` }}>
            <For each={props.timeline}>
              {(entry, i) => (
                <div
                  class="text-center"
                  style={{ width: `${BAR_BASE_WIDTH * zoom()}px`, "flex-shrink": "0" }}
                >
                  <span class="text-micro text-theme-text-secondary whitespace-nowrap">
                    {i() % labelInterval() === 0 ? formatLabel(entry.month) : ""}
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
