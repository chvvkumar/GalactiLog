import { createSignal, Show, onCleanup, onMount, createEffect, createMemo } from "solid-js";
import { Portal } from "solid-js/web";
import { useSettingsContext } from "./SettingsProvider";
import HelpPopover from "./HelpPopover";

export type PreviewFile = {
  imageId: string;
  filePath: string;
  thumbnailUrl?: string | null;
};

type Props = {
  imageId: string;
  filePath: string;
  thumbnailUrl?: string | null;
  files?: PreviewFile[];
  initialIndex?: number;
  onClose: () => void;
};

export function FilePreviewModal(props: Props) {
  const { settings } = useSettingsContext();
  const [zoomed, setZoomed] = createSignal(false);
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);
  const [zoomUrl, setZoomUrl] = createSignal<string | null>(null);
  const [index, setIndex] = createSignal(props.initialIndex ?? 0);
  const [autoZoom, setAutoZoom] = createSignal(false);

  const files = createMemo<PreviewFile[]>(() =>
    props.files && props.files.length > 0
      ? props.files
      : [{ imageId: props.imageId, filePath: props.filePath, thumbnailUrl: props.thumbnailUrl ?? null }],
  );
  const current = () => {
    const list = files();
    const i = Math.min(Math.max(index(), 0), list.length - 1);
    return list[i];
  };
  const hasList = () => files().length > 1;

  const [scale, setScale] = createSignal(1);
  const [tx, setTx] = createSignal(0);
  const [ty, setTy] = createSignal(0);
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let panStartX = 0;
  let panStartY = 0;
  let viewportEl: HTMLDivElement | undefined;

  const resetTransform = () => {
    setScale(1);
    setTx(0);
    setTy(0);
  };

  const resetForNewFile = () => {
    const prev = zoomUrl();
    if (prev) URL.revokeObjectURL(prev);
    setZoomUrl(null);
    setZoomed(false);
    setLoading(false);
    setError(null);
    resetTransform();
  };

  const goTo = (next: number) => {
    const list = files();
    if (list.length === 0) return;
    const n = ((next % list.length) + list.length) % list.length;
    if (n === index()) return;
    resetForNewFile();
    setIndex(n);
    if (autoZoom()) requestZoom();
  };
  const goPrev = () => goTo(index() - 1);
  const goNext = () => goTo(index() + 1);

  createEffect(() => {
    const max = files().length - 1;
    if (index() > max) setIndex(Math.max(0, max));
  });

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    if (!viewportEl) return;
    const rect = viewportEl.getBoundingClientRect();
    const cx = e.clientX - rect.left - rect.width / 2;
    const cy = e.clientY - rect.top - rect.height / 2;
    const factor = Math.exp(-e.deltaY * 0.0015);
    const oldScale = scale();
    const newScale = Math.min(20, Math.max(1, oldScale * factor));
    if (newScale === oldScale) return;
    const ratio = newScale / oldScale;
    setTx(cx - (cx - tx()) * ratio);
    setTy(cy - (cy - ty()) * ratio);
    setScale(newScale);
    if (newScale === 1) {
      setTx(0);
      setTy(0);
    }
  };

  const onPointerDown = (e: PointerEvent) => {
    if (scale() <= 1) return;
    dragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    panStartX = tx();
    panStartY = ty();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!dragging) return;
    setTx(panStartX + (e.clientX - dragStartX));
    setTy(panStartY + (e.clientY - dragStartY));
  };
  const onPointerUp = (e: PointerEvent) => {
    dragging = false;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
  };
  const onDoubleClick = () => resetTransform();

  const previewResolution = () => settings()?.general.preview_resolution ?? 2400;

  const handleKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      props.onClose();
    } else if (hasList() && e.key === "ArrowLeft") {
      e.preventDefault();
      goPrev();
    } else if (hasList() && e.key === "ArrowRight") {
      e.preventDefault();
      goNext();
    }
  };
  onMount(() => window.addEventListener("keydown", handleKey));
  onCleanup(() => window.removeEventListener("keydown", handleKey));

  const requestZoom = async () => {
    const prev = zoomUrl();
    if (prev) URL.revokeObjectURL(prev);
    setZoomUrl(null);
    setLoading(true);
    setError(null);
    resetTransform();
    const target = current();
    const url = `/api/preview/${target.imageId}?resolution=${previewResolution()}`;
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      setZoomUrl(URL.createObjectURL(blob));
      setZoomed(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load preview");
    } finally {
      setLoading(false);
    }
  };

  onCleanup(() => {
    const u = zoomUrl();
    if (u) URL.revokeObjectURL(u);
  });

  return (
    <Portal>
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
        onClick={props.onClose}
        onPointerDown={(e) => e.stopPropagation()}
        onPointerMove={(e) => e.stopPropagation()}
        onPointerUp={(e) => e.stopPropagation()}
        onPointerCancel={(e) => e.stopPropagation()}
      >
        <div
          class="relative max-h-[90vh] max-w-[90vw] rounded-lg bg-neutral-900 p-4 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            class="absolute right-2 top-2 rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-white"
            onClick={props.onClose}
          >
            &times;
          </button>
          <Show when={hasList()}>
            <div class="mb-2 flex items-center gap-2 pr-8">
              <button
                class="rounded px-2 py-0.5 text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
                onClick={goPrev}
                title="Previous (←)"
                disabled={loading()}
              >
                &#8592;
              </button>
              <span class="text-xs text-neutral-400 tabular-nums shrink-0">
                {index() + 1} / {files().length}
              </span>
              <button
                class="rounded px-2 py-0.5 text-neutral-300 hover:bg-neutral-800 disabled:opacity-40"
                onClick={goNext}
                title="Next (→)"
                disabled={loading()}
              >
                &#8594;
              </button>
              <div class="ml-2 flex items-center gap-1 shrink-0">
                <label class="flex items-center gap-1 text-xs text-neutral-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    class="cursor-pointer"
                    checked={autoZoom()}
                    onChange={(e) => {
                      const on = e.currentTarget.checked;
                      setAutoZoom(on);
                      if (on) {
                        if (!zoomed() && !loading()) requestZoom();
                      } else {
                        const u = zoomUrl();
                        if (u) URL.revokeObjectURL(u);
                        setZoomUrl(null);
                        setZoomed(false);
                        resetTransform();
                      }
                    }}
                  />
                  Render full preview on navigation
                </label>
                <HelpPopover title="Render full preview on navigation" align="left">
                  <p>
                    Controls what is shown when stepping through files with the ← / → keys or buttons.
                  </p>
                  <p>
                    <span class="font-medium text-theme-text-primary">Off (default):</span> shows only
                    the cached thumbnail for each file. Fast scrolling through many frames.
                  </p>
                  <p>
                    <span class="font-medium text-theme-text-primary">On:</span> automatically renders
                    a fresh full-resolution preview for every file at the configured Preview resolution.
                    Slower per step; useful for inspecting detail across frames.
                  </p>
                </HelpPopover>
              </div>
            </div>
          </Show>
          <div class="mb-2 pr-8 text-xs text-neutral-400 truncate" title={current().filePath}>
            {current().filePath}
          </div>

          <div
            ref={viewportEl}
            class="relative flex items-center justify-center min-h-[200px] overflow-hidden touch-none select-none"
            onWheel={onWheel}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDblClick={onDoubleClick}
            style={{ cursor: scale() > 1 ? (dragging ? "grabbing" : "grab") : "zoom-in" }}
          >
            <Show
              when={zoomed() && zoomUrl()}
              fallback={
                <Show
                  when={current().thumbnailUrl}
                  fallback={
                    <div class="text-neutral-500 italic">No thumbnail available. Click Zoom to render.</div>
                  }
                >
                  <img
                    src={current().thumbnailUrl!}
                    alt="Thumbnail"
                    draggable={false}
                    class="max-h-[70vh] max-w-full"
                    style={{ transform: `translate(${tx()}px, ${ty()}px) scale(${scale()})`, "transform-origin": "center center", "will-change": "transform" }}
                  />
                </Show>
              }
            >
              <img
                src={zoomUrl()!}
                alt="Preview"
                draggable={false}
                class="max-h-[80vh] max-w-full"
                style={{ transform: `translate(${tx()}px, ${ty()}px) scale(${scale()})`, "transform-origin": "center center", "will-change": "transform" }}
              />
            </Show>

            <Show when={loading()}>
              <div class="absolute inset-0 flex items-center justify-center bg-black/60">
                <div class="text-white">Rendering preview...</div>
              </div>
            </Show>
          </div>

          <Show when={error()}>
            <div class="mt-2 rounded bg-red-900/50 p-2 text-sm text-red-200">
              {error()}
              <button class="ml-2 underline disabled:opacity-50" onClick={requestZoom} disabled={loading()}>Retry</button>
            </div>
          </Show>

          <div class="mt-3 flex justify-end gap-2">
            <Show when={!zoomed()}>
              <button
                class="rounded bg-blue-600 px-3 py-1 text-white hover:bg-blue-500 disabled:opacity-50"
                onClick={requestZoom}
                disabled={loading()}
              >
                Zoom ({previewResolution() === 0 ? "Native" : `${previewResolution()}px`})
              </button>
            </Show>
          </div>
        </div>
      </div>
    </Portal>
  );
}
