import { Component, Show, createSignal } from "solid-js";
import { Portal } from "solid-js/web";
import { api } from "../api/client";

const ReferenceThumbnail: Component<{ url: string | null; fill?: boolean }> = (props) => {
  const [open, setOpen] = createSignal(false);

  return (
    <Show when={props.url} fallback={
      <div class={`bg-theme-base rounded flex items-center justify-center text-theme-text-secondary text-sm ${props.fill ? "h-full w-24" : "w-full h-48"}`}>
        No thumbnail
      </div>
    }>
      {(url) => (
        <>
          <img
            src={api.thumbnailUrl(url())}
            alt="Reference frame"
            class={`rounded bg-black cursor-pointer ${props.fill ? "max-h-full w-auto" : "w-full object-contain max-h-64"}`}
            loading="lazy"
            onClick={(e) => { e.stopPropagation(); setOpen(true); }}
          />
          <Show when={open()}>
            <Portal>
              <div
                class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-pointer"
                onClick={() => setOpen(false)}
              >
                <img
                  src={api.thumbnailUrl(url())}
                  alt="Reference frame"
                  class="max-w-[90vw] max-h-[90vh]"
                />
              </div>
            </Portal>
          </Show>
        </>
      )}
    </Show>
  );
};

export default ReferenceThumbnail;
