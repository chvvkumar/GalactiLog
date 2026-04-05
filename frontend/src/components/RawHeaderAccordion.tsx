import { Component, For, Show, createSignal } from "solid-js";

const RawHeaderAccordion: Component<{ headers: Record<string, unknown> | null }> = (props) => {
  const [open, setOpen] = createSignal(false);

  const entries = () => {
    if (!props.headers) return [];
    return Object.entries(props.headers).sort(([a], [b]) => a.localeCompare(b));
  };

  return (
    <div class="bg-theme-base rounded-[var(--radius-md)]">
      <button
        onClick={() => setOpen((v) => !v)}
        class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-md)] hover:text-theme-text-primary transition-colors cursor-pointer"
        classList={{ "text-theme-text-primary": open(), "text-theme-text-secondary": !open() }}
      >
        <span class="font-semibold border-l-2 border-theme-accent pl-2">
          FITS Headers <span class="text-theme-text-tertiary font-normal">({entries().length} keys)</span>
        </span>
        <svg
          class={`w-3.5 h-3.5 transition-transform duration-200 ${open() ? "rotate-180" : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
        </svg>
      </button>
      <Show when={open()}>
        <div class="px-3 pb-3 max-h-64 overflow-y-auto">
          <table class="w-full text-xs">
            <thead class="sticky top-0 bg-theme-base">
              <tr class="text-theme-text-secondary">
                <th class="text-left py-1 px-2 font-normal">Key</th>
                <th class="text-left py-1 px-2 font-normal">Value</th>
              </tr>
            </thead>
            <tbody>
              <For each={entries()}>
                {([key, value]) => (
                  <tr class="border-t border-theme-border/30">
                    <td class="py-1 px-2 text-theme-text-secondary font-mono">{key}</td>
                    <td class="py-1 px-2 text-theme-text-primary font-mono break-all">{String(value)}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </Show>
    </div>
  );
};

export default RawHeaderAccordion;
