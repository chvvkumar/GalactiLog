import { Component, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { A } from "@solidjs/router";
import { scanFilters } from "../api/scanFilters";
import { showToast } from "./Toast";

interface Props {
  variant?: "inline" | "global";
  onReview?: () => void;
}

const ScanFiltersOnboarding: Component<Props> = (props) => {
  const [show, setShow] = createSignal(false);
  const [saving, setSaving] = createSignal(false);
  const variant = () => props.variant ?? "inline";

  const load = async () => {
    try {
      const r = await scanFilters.get();
      setShow(!r.configured);
    } catch { /* ignore */ }
  };

  createEffect(() => { load(); });

  const onConfigured = () => setShow(false);
  window.addEventListener("scan-filters-configured", onConfigured);
  onCleanup(() => window.removeEventListener("scan-filters-configured", onConfigured));

  const useDefaults = async () => {
    setSaving(true);
    try {
      await scanFilters.put({
        include_paths: [], exclude_paths: [], name_rules: [],
      });
      setShow(false);
      window.dispatchEvent(new CustomEvent("scan-filters-configured"));
      showToast("Scanning everything under the data root");
    } catch (e: any) {
      showToast(e?.message ?? "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  };

  const primaryBtnClass =
    "px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 " +
    "rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors";
  const secondaryBtnClass =
    "px-4 py-1.5 bg-theme-surface text-theme-text-primary border border-theme-border " +
    "rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-hover transition-colors";

  return (
    <Show when={show()}>
      <div class="mx-4 mt-4 rounded-[var(--radius-md)] border border-theme-accent/40 bg-theme-accent/10 p-4 space-y-3">
        <div class="flex items-start gap-3">
          <svg
            class="w-5 h-5 mt-0.5 text-theme-accent flex-shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div class="flex-1 space-y-1">
            <h4 class="text-sm font-medium text-theme-text-primary">
              Review scan filters before your first scan
            </h4>
            <p class="text-xs text-theme-text-secondary">
              <Show
                when={variant() === "global"}
                fallback={
                  <>
                    This install has not been configured with scan filters yet. By
                    default the scanner will walk every folder under the configured
                    data root and ingest every supported file. Auto-scan is paused
                    until you either review the filters below or accept the defaults.
                  </>
                }
              >
                Auto-scan is paused until you configure scan filters. Restrict which
                folders are scanned and which file or folder names are included or
                excluded under Settings → Library, or accept the defaults to
                scan everything under the configured data root.
              </Show>
            </p>
          </div>
        </div>
        <div class="flex flex-wrap gap-2 pl-8">
          <Show
            when={variant() === "global"}
            fallback={
              <button
                class={primaryBtnClass}
                onClick={props.onReview}
              >
                Review scan filters
              </button>
            }
          >
            <A href="/settings?tab=scan" class={primaryBtnClass}>
              Open scan settings
            </A>
          </Show>
          <button
            class={secondaryBtnClass}
            disabled={saving()}
            onClick={useDefaults}
          >
            {saving() ? "Saving…" : "Use defaults (scan everything)"}
          </button>
        </div>
      </div>
    </Show>
  );
};

export default ScanFiltersOnboarding;
