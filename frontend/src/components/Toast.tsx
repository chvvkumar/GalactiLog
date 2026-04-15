import { Show, type Component } from "solid-js";
import { createSignal } from "solid-js";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
}

const [toast, setToast] = createSignal<ToastState | null>(null);
let timeout: ReturnType<typeof setTimeout>;

export function showToast(
  message: string,
  type: "success" | "error" | "info" = "success",
  duration = 3000,
) {
  clearTimeout(timeout);
  setToast({ message, type });
  if (duration > 0) {
    timeout = setTimeout(() => setToast(null), duration);
  }
}

export function dismissToast() {
  clearTimeout(timeout);
  setToast(null);
}

export const Toast: Component = () => {
  return (
    <Show when={toast()}>
      {(t) => (
        <div class="fixed top-6 inset-x-0 flex justify-center z-50">
          <div
            class={`animate-toast-down px-5 py-2.5 rounded-[var(--radius-md)] text-sm font-medium backdrop-blur-xl shadow-lg border flex items-center gap-3 ${
              t().type === "success"
                ? "bg-theme-success/20 text-theme-success border-theme-success/30"
                : t().type === "info"
                ? "bg-theme-accent/20 text-theme-accent border-theme-accent/30"
                : "bg-theme-error/20 text-theme-error border-theme-error/30"
            }`}
          >
            <span>{t().message}</span>
            <button
              onClick={() => setToast(null)}
              class="opacity-60 hover:opacity-100 transition-opacity ml-1"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        </div>
      )}
    </Show>
  );
};
