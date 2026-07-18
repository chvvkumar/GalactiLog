import { Show, createSignal, onCleanup, onMount, type Component, type JSX } from "solid-js";

interface HelpPopoverProps {
  label?: string;
  title?: string;
  children: JSX.Element;
  class?: string;
  align?: "left" | "right";
  // Panel width class. Defaults to the narrow single-column popover; pass a
  // wider class (e.g. "w-[min(44rem,90vw)]") for multi-column content.
  width?: string;
}

const HelpPopover: Component<HelpPopoverProps> = (props) => {
  const [open, setOpen] = createSignal(false);
  // Flip above the trigger when there is no room below, and clamp the panel
  // body height to whatever space the chosen side offers so it never runs off
  // the viewport (or the modal it sits in).
  const [placeAbove, setPlaceAbove] = createSignal(false);
  const [bodyMaxH, setBodyMaxH] = createSignal<number | null>(null);
  let wrapperRef: HTMLDivElement | undefined;

  const measure = () => {
    if (!wrapperRef) return;
    const rect = wrapperRef.getBoundingClientRect();
    const margin = 16;
    const spaceBelow = window.innerHeight - rect.bottom - margin;
    const spaceAbove = rect.top - margin;
    const above = spaceBelow < 260 && spaceAbove > spaceBelow;
    setPlaceAbove(above);
    // Reserve room for the header/padding chrome (~72px) inside the panel.
    const avail = (above ? spaceAbove : spaceBelow) - 72;
    setBodyMaxH(Math.max(160, avail));
  };

  const close = () => setOpen(false);
  const toggle = (e: MouseEvent) => {
    e.stopPropagation();
    setOpen((v) => {
      const next = !v;
      if (next) measure();
      return next;
    });
  };

  const onDocClick = (e: MouseEvent) => {
    if (!wrapperRef) return;
    if (!wrapperRef.contains(e.target as Node)) close();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") close();
  };
  const onReflow = () => {
    if (open()) measure();
  };

  onMount(() => {
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onReflow);
    window.addEventListener("scroll", onReflow, true);
  });
  onCleanup(() => {
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onReflow);
    window.removeEventListener("scroll", onReflow, true);
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
          aria-modal="true"
          onClick={(e) => e.stopPropagation()}
          class={`glass-popover absolute z-50 ${props.width ?? "w-[min(28rem,90vw)]"} ${
            placeAbove() ? "bottom-full mb-2" : "top-full mt-2"
          } ${
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
          <div
            class="space-y-2 text-sm text-theme-text-secondary overflow-y-auto pr-1"
            style={{ "max-height": bodyMaxH() ? `${bodyMaxH()}px` : undefined }}
          >
            {props.children}
          </div>
        </div>
      </Show>
    </div>
  );
};

export default HelpPopover;
