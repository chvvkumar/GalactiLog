import { For, type Component } from "solid-js";
import { createSignal } from "solid-js";

export type ToastSeverity = "success" | "error" | "info";

export interface ToastEntry {
  id: number;
  message: string;
  type: ToastSeverity;
  duration: number;
}

const [toasts, setToasts] = createSignal<ToastEntry[]>([]);
const timers = new Map<number, ReturnType<typeof setTimeout>>();
let nextId = 1;

function clearTimer(id: number): void {
  const t = timers.get(id);
  if (t !== undefined) {
    clearTimeout(t);
    timers.delete(id);
  }
}

function scheduleAutoDismiss(id: number, duration: number): void {
  if (duration <= 0) return;
  const t = setTimeout(() => {
    timers.delete(id);
    setToasts((list) => list.filter((x) => x.id !== id));
  }, duration);
  timers.set(id, t);
}

/**
 * Show a toast. Returns the toast id, which can be passed to `dismissToast(id)`
 * to dismiss that specific toast. Calling `dismissToast()` with no arguments
 * dismisses all toasts (legacy behavior).
 *
 * Multiple toasts stack vertically; each has its own auto-dismiss timer.
 */
export function showToast(
  message: string,
  type: ToastSeverity = "success",
  duration = 3000,
): number {
  const id = nextId++;
  const entry: ToastEntry = { id, message, type, duration };
  setToasts((list) => [...list, entry]);
  scheduleAutoDismiss(id, duration);
  return id;
}

/**
 * Dismiss a toast. With no argument, dismisses all toasts (back-compat).
 * With an id, dismisses just that toast.
 */
export function dismissToast(id?: number): void {
  if (id === undefined) {
    for (const t of timers.values()) clearTimeout(t);
    timers.clear();
    setToasts([]);
    return;
  }
  clearTimer(id);
  setToasts((list) => list.filter((x) => x.id !== id));
}

/** Returns the number of toasts currently visible. */
export function toastCount(): number {
  return toasts().length;
}

export const Toast: Component = () => {
  return (
    <div class="fixed top-6 inset-x-0 flex flex-col items-center gap-2 z-50 pointer-events-none">
      <For each={toasts()}>
        {(t) => (
          <div
            class={`animate-toast-down pointer-events-auto px-5 py-2.5 rounded-[var(--radius-md)] text-sm font-medium backdrop-blur-xl shadow-lg border flex items-center gap-3 ${
              t.type === "success"
                ? "bg-theme-success/20 text-theme-success border-theme-success/30"
                : t.type === "info"
                ? "bg-theme-accent/20 text-theme-accent border-theme-accent/30"
                : "bg-theme-error/20 text-theme-error border-theme-error/30"
            }`}
          >
            <span>{t.message}</span>
            <button
              onClick={() => dismissToast(t.id)}
              class="opacity-60 hover:opacity-100 transition-opacity ml-1"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        )}
      </For>
    </div>
  );
};
