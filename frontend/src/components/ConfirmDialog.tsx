import { Component, Show, createEffect, onCleanup } from "solid-js";
import { Portal } from "solid-js/web";
import Button from "./ui/Button";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

// Focusable element selector — matches the pattern used elsewhere in the codebase.
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

const ConfirmDialog: Component<Props> = (props) => {
  let containerRef: HTMLDivElement | undefined;
  let previouslyFocused: Element | null = null;

  const getFocusable = (): HTMLElement[] => {
    if (!containerRef) return [];
    return Array.from(containerRef.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null,
    );
  };

  // Move focus in and restore on close.
  createEffect(() => {
    if (props.open) {
      previouslyFocused = document.activeElement;
      queueMicrotask(() => {
        const focusable = getFocusable();
        if (focusable.length > 0) focusable[0].focus();
        else containerRef?.focus();
      });
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

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      props.onCancel();
      return;
    }
    // Basic focus trap: keep Tab/Shift+Tab inside the dialog.
    if (e.key === "Tab") {
      const focusable = getFocusable();
      if (focusable.length === 0) {
        // No focusable children — keep focus on the container itself.
        e.preventDefault();
        containerRef?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
  };

  return (
    <Show when={props.open}>
      <Portal>
        <div
          ref={containerRef}
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
          onKeyDown={onKeyDown}
          tabIndex={-1}
        >
          <div
            class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] w-full max-w-sm p-6 space-y-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3
              id="confirm-dialog-title"
              class="text-sm font-semibold text-theme-text-primary"
            >
              {props.title}
            </h3>
            <p class="text-sm text-theme-text-secondary">{props.message}</p>
            <div class="flex justify-end gap-2">
              <Button variant="secondary" onClick={props.onCancel}>
                {props.cancelLabel ?? "Cancel"}
              </Button>
              <Button variant="danger" onClick={props.onConfirm}>
                {props.confirmLabel ?? "Confirm"}
              </Button>
            </div>
          </div>
        </div>
      </Portal>
    </Show>
  );
};

export default ConfirmDialog;
