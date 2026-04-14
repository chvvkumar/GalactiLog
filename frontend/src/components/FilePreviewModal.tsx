import { createSignal, Show, onCleanup, onMount } from "solid-js";
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

        <div class="relative flex items-center justify-center min-h-[200px]">
          <Show
            when={zoomed() && zoomUrl()}
            fallback={
              <Show
                when={props.thumbnailUrl}
                fallback={
                  <div class="text-neutral-500 italic">No thumbnail available. Click Zoom to render.</div>
                }
              >
                <img src={props.thumbnailUrl!} alt="Thumbnail" class="max-h-[70vh] max-w-full" />
              </Show>
            }
          >
            <img src={zoomUrl()!} alt="Preview" class="max-h-[80vh] max-w-full" />
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
  );
}
