import { Component, For, Show } from "solid-js";

interface FailedFile {
  path: string;
  reason: string;
}

const DISPLAY_LIMIT = 10;

const FailedFilesList: Component<{
  files: FailedFile[];
  truncated: boolean;
}> = (props) => {
  const shown = () => props.files.slice(0, DISPLAY_LIMIT);
  const overflow = () => props.files.length - DISPLAY_LIMIT;

  return (
    <div class="space-y-1 mt-1 max-h-48 overflow-y-auto">
      <For each={shown()}>
        {(f) => (
          <div class="border border-theme-border rounded px-2 py-1">
            <div class="text-xs text-theme-text-secondary break-all font-mono">
              {f.path}
            </div>
            <div
              class="text-xs text-[var(--color-warning)] truncate"
              title={f.reason}
            >
              {f.reason}
            </div>
          </div>
        )}
      </For>
      <Show when={overflow() > 0}>
        <p class="text-xs text-theme-text-secondary pl-1">
          {overflow()} more file{overflow() > 1 ? "s" : ""}
        </p>
      </Show>
      <Show when={props.truncated}>
        <p class="text-xs text-[var(--color-warning)] pl-1">
          List truncated at 500 entries.
        </p>
      </Show>
    </div>
  );
};

export default FailedFilesList;
