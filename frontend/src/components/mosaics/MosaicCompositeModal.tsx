import { Component, Show, createResource, onCleanup } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { getErrorMessage } from "../../utils/errors";
import Dialog from "../Dialog";

interface Props {
  mosaicId: string;
  mosaicName: string;
  filter: string | null;
  onClose: () => void;
}

/**
 * Lightbox that generates and displays the mosaic composite JPEG for the
 * currently selected filter. The composite can take a few seconds to build,
 * so a loading state is shown while the request is in flight, and an error
 * state with a retry action is shown on failure. A download link is provided
 * for the generated JPEG.
 */
const MosaicCompositeModal: Component<Props> = (props) => {
  // The generated schema types this endpoint's success body as `unknown`
  // (FastAPI's streaming JPEG response has no declared content schema), so
  // the unwrap result is cast to `Blob` -- same pattern as
  // TargetDetailPage.tsx's reference-thumbnail blob fetch.
  const [composite, { refetch }] = createResource(
    () => props.filter ?? "__default__",
    async (): Promise<string> => {
      const blob = await apiClient
        .GET("/api/mosaics/{mosaic_id}/composite", {
          params: { path: { mosaic_id: props.mosaicId }, query: { filter: props.filter } },
          parseAs: "blob",
        })
        .then(unwrap) as Blob;
      return URL.createObjectURL(blob);
    },
  );

  // Revoke the previous object URL whenever a new one replaces it or the
  // component unmounts, to avoid leaking blob URLs.
  let lastUrl: string | undefined;
  const trackUrl = (url: string | undefined) => {
    if (lastUrl && lastUrl !== url) URL.revokeObjectURL(lastUrl);
    lastUrl = url;
    return url;
  };
  onCleanup(() => {
    if (lastUrl) URL.revokeObjectURL(lastUrl);
  });

  const safeName = () => props.mosaicName.replace(/[^a-zA-Z0-9]/g, "_");
  const filterSuffix = () => (props.filter ? `_${props.filter}` : "");

  return (
    <Dialog open aria-labelledby="composite-modal-title" onClose={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-5xl w-full mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border flex items-center justify-between gap-3">
          <h2 id="composite-modal-title" class="text-sm font-medium text-theme-text-primary truncate">
            Composite - {props.mosaicName}
            <Show when={props.filter}>
              <span class="text-theme-text-secondary"> ({props.filter})</span>
            </Show>
          </h2>
          <button
            class="text-theme-text-secondary hover:text-theme-text-primary shrink-0"
            onClick={props.onClose}
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
        </div>

        <div class="p-4 flex-1 overflow-auto flex items-center justify-center min-h-[200px]">
          <Show when={composite.loading}>
            <div class="flex flex-col items-center gap-3 text-theme-text-secondary">
              <div class="w-8 h-8 border-2 border-theme-border border-t-theme-accent rounded-full animate-spin" />
              <span class="text-xs">Generating composite...</span>
            </div>
          </Show>

          <Show when={composite.error}>
            <div class="flex flex-col items-center gap-3 text-center">
              <p class="text-sm text-theme-danger">
                {getErrorMessage(composite.error, "Failed to generate composite")}
              </p>
              <button
                class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors"
                onClick={() => refetch()}
              >
                Retry
              </button>
            </div>
          </Show>

          <Show when={!composite.loading && !composite.error && composite()}>
            {(url) => {
              const tracked = trackUrl(url());
              return (
                <img
                  src={tracked}
                  alt={`Composite of ${props.mosaicName}`}
                  class="max-w-full max-h-[70vh] object-contain rounded"
                />
              );
            }}
          </Show>
        </div>

        <div class="p-4 border-t border-theme-border flex gap-2 justify-end">
          <Show when={!composite.loading && !composite.error && composite()}>
            {(url) => (
              <a
                href={url()}
                download={`${safeName()}${filterSuffix()}_composite.jpg`}
                class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors"
              >
                Download JPEG
              </a>
            )}
          </Show>
        </div>
      </div>
    </Dialog>
  );
};

export default MosaicCompositeModal;
