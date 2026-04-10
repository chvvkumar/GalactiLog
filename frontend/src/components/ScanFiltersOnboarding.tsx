import { Component, createSignal, createEffect, onCleanup, Show } from "solid-js";
import { scanFilters } from "../api/scanFilters";
import { showToast } from "./Toast";

interface Props {
  onReview: () => void;
}

const ScanFiltersOnboarding: Component<Props> = (props) => {
  const [show, setShow] = createSignal(false);

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
    try {
      await scanFilters.put({
        include_paths: [], exclude_paths: [], name_rules: [],
      });
      setShow(false);
      showToast("Scanning everything under the data root");
    } catch (e: any) {
      showToast(e?.message ?? "Failed to save", "error");
    }
  };

  return (
    <Show when={show()}>
      <div class="rounded-[var(--radius-md)] border border-amber-500/50 bg-amber-500/10 p-4 space-y-2">
        <h4 class="text-sm font-medium text-amber-200">Review scan filters</h4>
        <p class="text-xs text-theme-text-secondary">
          This install has not been configured with scan filters yet. By default
          the scanner will walk every folder under the configured data root and
          ingest every supported file. You can restrict which folders are scanned
          and which file or folder names are included or excluded. Review the
          filters below before running your first scan, or accept the defaults
          to scan everything.
        </p>
        <div class="flex gap-2">
          <button
            class="px-3 py-1.5 text-xs rounded bg-theme-accent text-white"
            onClick={props.onReview}
          >
            Review scan filters
          </button>
          <button
            class="px-3 py-1.5 text-xs rounded border border-theme-border"
            onClick={useDefaults}
          >
            Use defaults (scan everything)
          </button>
        </div>
      </div>
    </Show>
  );
};

export default ScanFiltersOnboarding;
