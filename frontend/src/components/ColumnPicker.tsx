import { createSignal, createEffect, onCleanup, For, Show } from "solid-js";
import type { CustomColumn, ColumnVisibility } from "../types";
import { isColumnVisible } from "../utils/displaySettings";

interface BuiltinColumn {
  key: string;
  label: string;
  alwaysVisible?: boolean;
}

interface Props {
  table: keyof ColumnVisibility;
  builtinColumns: BuiltinColumn[];
  customColumns: CustomColumn[];
  visibility: ColumnVisibility | undefined;
  onToggle: (kind: "builtin" | "custom", key: string, visible: boolean) => void;
}

export default function ColumnPicker(props: Props) {
  const [open, setOpen] = createSignal(false);
  let containerRef: HTMLDivElement | undefined;

  // Close on click outside
  createEffect(() => {
    if (!open()) return;
    const handler = (e: MouseEvent) => {
      if (containerRef && !containerRef.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    onCleanup(() => document.removeEventListener("mousedown", handler));
  });

  return (
    <div class="relative inline-block" ref={containerRef}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open()); }}
        class="p-1 rounded hover:bg-theme-hover text-theme-text-secondary"
        title="Configure columns"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
      </button>

      <Show when={open()}>
        <div
          class="absolute right-0 top-full mt-1 z-50 glass-popover border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] p-3 min-w-[200px]"
          onClick={(e) => e.stopPropagation()}
        >
          <div class="text-xs font-semibold text-theme-text-secondary mb-2">Built-in</div>
          <For each={props.builtinColumns}>
            {(col) => (
              <label class="flex items-center gap-2 py-0.5 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={col.alwaysVisible || isColumnVisible(props.visibility, props.table, "builtin", col.key)}
                  disabled={col.alwaysVisible}
                  onChange={(e) => props.onToggle("builtin", col.key, e.currentTarget.checked)}
                />
                {col.label}
              </label>
            )}
          </For>

          <Show when={props.customColumns.length > 0}>
            <div class="text-xs font-semibold text-theme-text-secondary mt-3 mb-2">Custom</div>
            <For each={props.customColumns}>
              {(col) => (
                <label class="flex items-center gap-2 py-0.5 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isColumnVisible(props.visibility, props.table, "custom", col.slug)}
                    onChange={(e) => props.onToggle("custom", col.slug, e.currentTarget.checked)}
                  />
                  {col.name}
                </label>
              )}
            </For>
          </Show>
        </div>
      </Show>
    </div>
  );
}
