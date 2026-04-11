import { Component, JSX, Show, createSignal, onMount, createEffect } from "solid-js";
import { expandRequestId, expandRequestTick } from "./sidebarLayout";

const STORAGE_KEY = "galactilog.sidebar.sections";
const LEGACY_KEY = "sidebar_collapsed";

function getCollapsedState(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (legacy) {
      let parsed: unknown = null;
      try { parsed = JSON.parse(legacy); } catch { /* ignore */ }
      const valid = (parsed && typeof parsed === "object" && !Array.isArray(parsed))
        ? (parsed as Record<string, boolean>)
        : {};
      localStorage.setItem(STORAGE_KEY, JSON.stringify(valid));
      localStorage.removeItem(LEGACY_KEY);
      return valid;
    }
    return {};
  } catch {
    return {};
  }
}

function saveCollapsedState(state: Record<string, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch { /* ignore */ }
}

const CollapsibleSection: Component<{ id: string; label: string; children: JSX.Element }> = (props) => {
  const [collapsed, setCollapsed] = createSignal(false);
  let sectionRef: HTMLElement | undefined;

  onMount(() => {
    const state = getCollapsedState();
    if (state[props.id]) setCollapsed(true);
  });

  createEffect(() => {
    expandRequestTick();
    if (expandRequestId() === props.id) {
      if (collapsed()) {
        setCollapsed(false);
        const state = getCollapsedState();
        delete state[props.id];
        saveCollapsedState(state);
      }
      queueMicrotask(() => {
        sectionRef?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    }
  });

  const toggle = () => {
    const next = !collapsed();
    setCollapsed(next);
    const state = getCollapsedState();
    if (next) {
      state[props.id] = true;
    } else {
      delete state[props.id];
    }
    saveCollapsedState(state);
  };

  return (
    <section
      ref={(el) => (sectionRef = el)}
      class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-3"
    >
      <button
        onClick={toggle}
        class="flex items-center justify-between w-full text-label font-medium uppercase tracking-wider text-theme-text-tertiary hover:text-theme-text-secondary transition-colors cursor-pointer select-none"
      >
        {props.label}
        <span class={`text-caption transition-transform ${collapsed() ? "-rotate-90" : ""}`}>&#9660;</span>
      </button>
      <Show when={!collapsed()}>
        <div class="mt-2">{props.children}</div>
      </Show>
    </section>
  );
};

export default CollapsibleSection;
