import { Show, createSignal, onCleanup, onMount, type Component, type JSX } from "solid-js";

interface HelpPopoverProps {
  label?: string;
  title?: string;
  children: JSX.Element;
  class?: string;
  align?: "left" | "right";
}

const HelpPopover: Component<HelpPopoverProps> = (props) => {
  const [open, setOpen] = createSignal(false);
  let wrapperRef: HTMLDivElement | undefined;

  const close = () => setOpen(false);
  const toggle = (e: MouseEvent) => {
    e.stopPropagation();
    setOpen((v) => !v);
  };

  const onDocClick = (e: MouseEvent) => {
    if (!wrapperRef) return;
    if (!wrapperRef.contains(e.target as Node)) close();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") close();
  };

  onMount(() => {
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
  });
  onCleanup(() => {
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKey);
  });

  return (
    <div ref={wrapperRef} class={`relative inline-flex ${props.class ?? ""}`}>
      <button
        type="button"
        onClick={toggle}
        aria-label={props.label ?? "About this section"}
        aria-expanded={open()}
        class="inline-flex items-center justify-center w-6 h-6 rounded-full text-theme-text-tertiary hover:text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer"
      >
        <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
            clip-rule="evenodd"
          />
        </svg>
      </button>
      <Show when={open()}>
        <div
          role="dialog"
          onClick={(e) => e.stopPropagation()}
          class={`glass-popover absolute top-full mt-2 z-50 w-[min(28rem,90vw)] ${
            props.align === "right" ? "right-0" : "left-0"
          } border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] p-4`}
        >
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="text-sm font-medium text-theme-text-primary">
              {props.title ?? "About this section"}
            </div>
            <button
              type="button"
              onClick={close}
              aria-label="Close"
              class="text-theme-text-tertiary hover:text-theme-text-primary cursor-pointer"
            >
              <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path
                  fill-rule="evenodd"
                  d="M4.3 4.3a1 1 0 011.4 0L10 8.6l4.3-4.3a1 1 0 111.4 1.4L11.4 10l4.3 4.3a1 1 0 01-1.4 1.4L10 11.4l-4.3 4.3a1 1 0 01-1.4-1.4L8.6 10 4.3 5.7a1 1 0 010-1.4z"
                  clip-rule="evenodd"
                />
              </svg>
            </button>
          </div>
          <div class="space-y-2 text-sm text-theme-text-secondary">{props.children}</div>
        </div>
      </Show>
    </div>
  );
};

export default HelpPopover;
