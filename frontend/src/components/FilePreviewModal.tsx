import { createSignal, Show, onCleanup, onMount } from "solid-js";
import { Portal } from "solid-js/web";
import { useSettingsContext } from "./SettingsProvider";

type Props = {
  imageId: string;
  filePath: string;
  thumbnailUrl?: string | null;
  onClose: () => void;
};

export function FilePreviewModal(props: Props) {
  const { settings } = useSettingsContext();
  const [zoomed, setZoomed] = createSignal(false);
  const [loading, setLoading] = createSignal(false);
  const [error, setError] = createSignal<string | null>(null);
  const [zoomUrl, setZoomUrl] = createSignal<string | null>(null);

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

  const handleEscape = (e: KeyboardEvent) => {
    if (e.key === "Escape") props.onClose();
  };
  onMount(() => window.addEventListener("keydown", handleEscape));
  onCleanup(() => window.removeEventListener("keydown", handleEscape));

  const requestZoom = async () => {
    const prev = zoomUrl();
    if (prev) URL.revokeObjectURL(prev);
    setZoomUrl(null);
    setLoading(true);
    setError(null);
    resetTransform();
    const url = `/api/preview/${props.imageId}?resolution=${previewResolution()}`;
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(body.detail || `HTTP ${resp.status}`);
      }
      // Browser followed the X-Accel-Redirect internally; resp body is the JPEG bytes
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
          <div class="mb-2 text-xs text-neutral-400 truncate max-w-[80ch]">{props.filePath}</div>

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
                  when={props.thumbnailUrl}
                  fallback={
                    <div class="text-neutral-500 italic">No thumbnail available. Click Zoom to render.</div>
                  }
                >
                  <img
                    src={props.thumbnailUrl!}
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
