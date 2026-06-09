import {
  Component,
  JSX,
  Show,
  createEffect,
  onCleanup,
} from "solid-js";
import { Portal } from "solid-js/web";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  /** Rendered into role="dialog". Provide one of aria-labelledby or aria-label. */
  "aria-labelledby"?: string;
  "aria-label"?: string;
  /** Extra classes forwarded to the outer backdrop div. */
  class?: string;
  children: JSX.Element;
}

/**
 * Accessible modal wrapper.
 *
 * Provides:
 *   - Portal so the DOM node appears at the document body root.
 *   - role="dialog" + aria-modal="true" on the backdrop container.
 *   - Escape-to-close.
 *   - Moves focus into the dialog when it opens.
 *   - Basic focus trap (Tab/Shift+Tab stays inside the dialog).
 *   - Restores focus to the previously focused element on close.
 *
 * The inner content element must be passed as children; this wrapper only
 * supplies the backdrop overlay and accessibility layer.
 */
const Dialog: Component<DialogProps> = (props) => {
  let dialogRef: HTMLDivElement | undefined;
  let previouslyFocused: Element | null = null;

  // Focusable element selector reused for trap and initial focus.
  const FOCUSABLE =
    'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  const getFocusable = (): HTMLElement[] => {
    if (!dialogRef) return [];
    return Array.from(dialogRef.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      // offsetParent is null for hidden elements in browsers; in test environments
      // it is always null, so fall back to checking that the element is not inert.
      (el) => el.offsetParent !== null || (el as HTMLElement).getClientRects().length > 0 || el.closest("[hidden]") === null,
    );
  };

  const moveFocusIn = () => {
    const focusable = getFocusable();
    if (focusable.length > 0) {
      focusable[0].focus();
    } else {
      // Fallback: focus the dialog container itself.
      dialogRef?.focus();
    }
  };

  const trapFocus = (e: KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const focusable = getFocusable();
    if (focusable.length === 0) {
      // No focusable children — keep focus pinned to the container so Tab
      // cannot escape the modal entirely.
      e.preventDefault();
      dialogRef?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first || document.activeElement === dialogRef) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last || document.activeElement === dialogRef) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      props.onClose();
      return;
    }
    trapFocus(e);
  };

  createEffect(() => {
    if (props.open) {
      previouslyFocused = document.activeElement;
      // Defer focus move until after the DOM has rendered.
      queueMicrotask(moveFocusIn);
    } else {
      if (previouslyFocused && (previouslyFocused as HTMLElement).focus) {
        (previouslyFocused as HTMLElement).focus();
      }
      previouslyFocused = null;
    }
  });

  onCleanup(() => {
    if (previouslyFocused && (previouslyFocused as HTMLElement).focus) {
      (previouslyFocused as HTMLElement).focus();
    }
  });

  return (
    <Show when={props.open}>
      <Portal>
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={props["aria-labelledby"]}
          aria-label={props["aria-label"]}
          class={`fixed inset-0 z-50 flex items-center justify-center bg-black/60 ${props.class ?? ""}`}
          onKeyDown={onKeyDown}
          // tabIndex allows the container itself to receive focus as a fallback.
          tabIndex={-1}
          onClick={props.onClose}
        >
          {props.children}
        </div>
      </Portal>
    </Show>
  );
};

export default Dialog;
