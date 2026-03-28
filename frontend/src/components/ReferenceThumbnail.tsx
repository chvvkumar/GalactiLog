import { Component, Show } from "solid-js";
import { api } from "../api/client";

const ReferenceThumbnail: Component<{ url: string | null }> = (props) => {
  return (
    <Show when={props.url} fallback={
      <div class="w-full h-48 bg-theme-base rounded flex items-center justify-center text-theme-text-secondary text-sm">
        No thumbnail
      </div>
    }>
      {(url) => (
        <img
          src={api.thumbnailUrl(url())}
          alt="Reference frame"
          class="w-full rounded object-contain max-h-64 bg-black"
          loading="lazy"
        />
      )}
    </Show>
  );
};

export default ReferenceThumbnail;
