import { createSignal, Show, type Component } from "solid-js";

interface ToastState {
  message: string;
  type: "success" | "error";
}

const [toast, setToast] = createSignal<ToastState | null>(null);
let timeout: ReturnType<typeof setTimeout>;

export function showToast(message: string, type: "success" | "error" = "success") {
  clearTimeout(timeout);
  setToast({ message, type });
  timeout = setTimeout(() => setToast(null), 3000);
}

export const Toast: Component = () => {
  return (
    <Show when={toast()}>
      {(t) => (
        <div class="fixed top-6 inset-x-0 flex justify-center z-50">
          <div
            class={`animate-toast-down px-5 py-2.5 rounded-[var(--radius-md)] text-sm font-medium backdrop-blur-xl shadow-lg border ${
              t().type === "success"
                ? "bg-theme-success/20 text-theme-success border-theme-success/30"
                : "bg-theme-error/20 text-theme-error border-theme-error/30"
            }`}
          >
            {t().message}
          </div>
        </div>
      )}
    </Show>
  );
};
