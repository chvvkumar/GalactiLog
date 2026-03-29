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
        <div
          class={`fixed bottom-4 right-4 px-4 py-2 rounded-[var(--radius-md)] text-sm text-white shadow-[var(--shadow-lg)] border border-theme-border animate-slide-in-right z-50 ${
            t().type === "success" ? "bg-theme-success" : "bg-theme-error"
          }`}
        >
          {t().message}
        </div>
      )}
    </Show>
  );
};
