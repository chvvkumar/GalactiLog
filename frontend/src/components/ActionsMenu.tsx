import { Show, createSignal, onCleanup, onMount, type Component, type JSX } from "solid-js";

interface ActionsMenuProps {
  // Menu contents; receives `close` so items can dismiss the menu after acting.
  children: (close: () => void) => JSX.Element;
  ariaLabel?: string;
  buttonClass?: string;
  menuClass?: string;
  // Optional trigger content. Defaults to the "..." ellipsis glyph.
  triggerContent?: JSX.Element;
}

// Dropdown "..." actions menu with document click-outside and Escape-to-close
// handling. Manages its own open state so callers only need to supply the
// menu items.
const ActionsMenu: Component<ActionsMenuProps> = (props) => {
  const [open, setOpen] = createSignal(false);
  let menuRef: HTMLDivElement | undefined;

  const close = () => setOpen(false);

  const onDocClick = (e: MouseEvent) => {
    if (!menuRef) return;
    if (!menuRef.contains(e.target as Node)) close();
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
    <div ref={menuRef} class="relative inline-flex">
      <button
        type="button"
        aria-label={props.ariaLabel ?? "More actions"}
        aria-haspopup="menu"
        aria-expanded={open()}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        class={
          props.buttonClass ??
          "inline-flex items-center justify-center w-8 h-8 rounded border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer"
        }
      >
        <Show when={props.triggerContent} fallback={<span class="text-lg leading-none" aria-hidden="true">&#8943;</span>}>
          {props.triggerContent}
        </Show>
      </button>
      <Show when={open()}>
        <div
          role="menu"
          onClick={(e) => e.stopPropagation()}
          class={
            props.menuClass ??
            "absolute top-full right-0 mt-2 z-50 min-w-[12rem] glass-popover border border-theme-border rounded-[var(--radius-sm)] shadow-[var(--shadow-lg)] py-1"
          }
        >
          {props.children(close)}
        </div>
      </Show>
    </div>
  );
};

export default ActionsMenu;
