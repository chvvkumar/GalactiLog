import {
  Show,
  createEffect,
  createSignal,
  onCleanup,
  onMount,
  type Component,
  type JSX,
} from "solid-js";
import { Portal } from "solid-js/web";

interface HelpPopoverProps {
  label?: string;
  title?: string;
  children: JSX.Element;
  class?: string;
  align?: "left" | "right";
}

/** Viewport margin kept clear on every side of the panel. */
const GAP = 8;

const HelpPopover: Component<HelpPopoverProps> = (props) => {
  const [open, setOpen] = createSignal(false);
  const [pos, setPos] = createSignal({ left: 0, top: 0 });
  let wrapperRef: HTMLDivElement | undefined;
  let panelRef: HTMLDivElement | undefined;
  let triggerRef: HTMLButtonElement | undefined;

  // Hover-open must not move focus; click/keyboard still does.
  let hoverOpened = false;
  let openTimer: number | undefined;
  let closeTimer: number | undefined;
  const clearTimers = () => {
    clearTimeout(openTimer);
    clearTimeout(closeTimer);
    openTimer = undefined;
    closeTimer = undefined;
  };

  const close = () => setOpen(false);
  const toggle = (e: MouseEvent) => {
    e.stopPropagation();
    clearTimers();
    hoverOpened = false;
    setOpen((v) => !v);
  };
  const onPointerEnter = () => {
    clearTimers();
    if (open()) return;
    openTimer = window.setTimeout(() => {
      hoverOpened = true;
      setOpen(true);
    }, 150);
  };
  const onPointerLeave = () => {
    clearTimers();
    closeTimer = window.setTimeout(close, 200);
  };

  // The panel is portaled to the body with position:fixed so a scrolling
  // ancestor (e.g. a modal body) cannot clip it or gain a scrollbar from it.
  const place = () => {
    if (!wrapperRef) return;
    const t = wrapperRef.getBoundingClientRect();
    const w = panelRef?.offsetWidth ?? 0;
    const h = panelRef?.offsetHeight ?? 0;
    let left = props.align === "right" ? t.right - w : t.left;
    left = Math.max(GAP, Math.min(left, window.innerWidth - w - GAP));
    let top = t.bottom + GAP;
    if (h > 0 && top + h > window.innerHeight - GAP && t.top - h - GAP >= GAP) {
      top = t.top - h - GAP;
    }
    setPos({ left, top });
  };

  createEffect(() => {
    if (!open()) return;
    place();
    if (!hoverOpened) panelRef?.focus();
    // Capture phase so scrolling containers, not just the window, reposition.
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    onCleanup(() => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      if (!hoverOpened) triggerRef?.focus();
    });
  });

  const onDocClick = (e: MouseEvent) => {
    const target = e.target as Node;
    if (wrapperRef?.contains(target)) return;
    if (panelRef?.contains(target)) return;
    close();
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
    clearTimers();
  });

  return (
    <div
      ref={wrapperRef}
      class={`relative inline-flex ${props.class ?? ""}`}
      onMouseEnter={onPointerEnter}
      onMouseLeave={onPointerLeave}
    >
      <button
        ref={triggerRef}
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
        <Portal>
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            tabindex={-1}
            onClick={(e) => e.stopPropagation()}
            onMouseEnter={clearTimers}
            onMouseLeave={onPointerLeave}
            style={{ left: `${pos().left}px`, top: `${pos().top}px` }}
            class="glass-popover fixed z-50 w-[min(28rem,90vw)] max-w-[calc(100vw-16px)] border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] p-4"
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
        </Portal>
      </Show>
    </div>
  );
};

export default HelpPopover;
