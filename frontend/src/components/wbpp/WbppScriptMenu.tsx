import { For, Show, createSignal, onCleanup, onMount, type JSX } from "solid-js";
import Button from "../ui/Button";

export type ScriptOs = "windows" | "posix";

export interface WbppScriptMenuProps {
  /** Resolved by the parent: pinned preference if set, else detection. */
  defaultOs: ScriptOs;
  /** Why defaultOs is what it is; drives the marker text, nothing else. */
  defaultReason: "detected" | "preference";
  /** Disables the trigger and swaps the label while a script is being built. */
  generating: boolean;
  /**
   * Whether a script already exists for the current settings. Drives the
   * "Regenerate" wording so the trigger admits it is about to replace one.
   * The parent owns the fact; this component only reads it.
   */
  hasScript: boolean;
  /** Extra reason to disable, e.g. no library root set. */
  disabled?: boolean;
  /** Parent runs the generate + download path for the chosen flavour. */
  onGenerate: (os: ScriptOs) => void;
}

const ITEMS: { os: ScriptOs; label: string }[] = [
  { os: "windows", label: "PowerShell (.ps1)" },
  { os: "posix", label: "Shell (.sh)" },
];

/**
 * Footer secondary action: pick the script flavour at the point of use rather
 * than in a settings select. The default OS is highlighted, but either flavour
 * is one click away. Resolving the default (pinned preference over detection)
 * stays with the parent; this component only reports which it was.
 */
export default function WbppScriptMenu(props: WbppScriptMenuProps): JSX.Element {
  const [open, setOpen] = createSignal(false);
  const triggerLabel = () => {
    if (props.generating) return "Generating...";
    return props.hasScript ? "Regenerate script" : "Generate script";
  };
  let wrapperRef: HTMLDivElement | undefined;
  let triggerRef: HTMLButtonElement | undefined;

  const close = () => setOpen(false);
  const closeAndRefocus = () => {
    close();
    triggerRef?.focus();
  };

  const onDocClick = (e: MouseEvent) => {
    if (!wrapperRef) return;
    if (!wrapperRef.contains(e.target as Node)) close();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape" && open()) closeAndRefocus();
  };

  onMount(() => {
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKey);
  });
  onCleanup(() => {
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKey);
  });

  const choose = (os: ScriptOs) => {
    close();
    props.onGenerate(os);
  };

  return (
    <div ref={wrapperRef} class="relative inline-flex">
      <Button
        ref={triggerRef}
        variant="secondary"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open()}
        disabled={props.generating || props.disabled}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        class="inline-flex items-center gap-1.5 cursor-pointer"
      >
        {triggerLabel()}
        <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            d="M5.3 7.3a1 1 0 011.4 0L10 10.6l3.3-3.3a1 1 0 111.4 1.4l-4 4a1 1 0 01-1.4 0l-4-4a1 1 0 010-1.4z"
            clip-rule="evenodd"
          />
        </svg>
      </Button>
      <Show when={open()}>
        <div
          role="menu"
          aria-label="Script type"
          onClick={(e) => e.stopPropagation()}
          class="glass-popover absolute bottom-full right-0 mb-2 z-50 min-w-[12rem] border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] py-1"
        >
          <For each={ITEMS}>
            {(item) => {
              const isDefault = () => item.os === props.defaultOs;
              return (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => choose(item.os)}
                  class={`w-full flex items-center justify-between gap-3 px-3 py-1.5 text-left text-sm cursor-pointer transition-colors hover:bg-theme-hover ${
                    isDefault()
                      ? "bg-theme-elevated text-theme-text-primary font-medium"
                      : "text-theme-text-secondary hover:text-theme-text-primary"
                  }`}
                >
                  <span>{item.label}</span>
                  <Show when={isDefault()}>
                    <span class="text-tiny uppercase tracking-wide text-theme-text-tertiary">
                      {props.defaultReason === "preference" ? "Your default" : "Detected"}
                    </span>
                  </Show>
                </button>
              );
            }}
          </For>
        </div>
      </Show>
    </div>
  );
}
