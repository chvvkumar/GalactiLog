import { Component, Show, createSignal } from "solid-js";
import { api } from "../api/client";

const MaintenanceActions: Component<{
  disabled: boolean;
  rebuildRunning: boolean;
  rebuildMode: string;
  onRegenThumbnails: () => void;
  onStartedAction: () => void;
}> = (props) => {
  const [showFullConfirm, setShowFullConfirm] = createSignal(false);
  const [showRefThumbChoice, setShowRefThumbChoice] = createSignal(false);

  const runAction = async (action: () => Promise<any>) => {
    setShowFullConfirm(false);
    setShowRefThumbChoice(false);
    try {
      await action();
      props.onStartedAction();
    } catch { /* ignore */ }
  };

  const anyDisabled = () => props.disabled || props.rebuildRunning;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Maintenance</h3>
        <div class="flex gap-2 flex-shrink-0 flex-wrap">
          <button
            onClick={() => runAction(api.smartRebuildTargets)}
            disabled={anyDisabled()}
            title="Re-matches orphaned images to existing targets using known aliases and cached SIMBAD results. Fast and offline - no network calls needed."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            {props.rebuildRunning && props.rebuildMode === "smart" ? "Running..." : "Fix Orphans"}
          </button>
          <button
            onClick={() => runAction(api.retryUnresolved)}
            disabled={anyDisabled()}
            title="Clears SIMBAD negative cache and SESAME cache, then re-resolves unresolved targets through SIMBAD and SESAME (NED + VizieR). Existing targets are not affected."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            {props.rebuildRunning && props.rebuildMode === "retry" ? "Running..." : "Re-resolve"}
          </button>
          <button
            onClick={() => props.onRegenThumbnails()}
            disabled={anyDisabled()}
            title="Re-creates all thumbnails using current stretch settings. Does not affect database records."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Regen Thumbs
          </button>
          <button
            onClick={() => runAction(api.triggerXmatchEnrichment)}
            disabled={anyDisabled()}
            title="Runs bulk cross-match enrichment against external catalogs (Caldwell, Herschel 400, Arp, Abell) for all targets."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            {props.rebuildRunning && props.rebuildMode === "xmatch" ? "Running..." : "Catalog Match"}
          </button>
          <button
            onClick={() => setShowRefThumbChoice(true)}
            disabled={anyDisabled()}
            title="Fetch DSS reference thumbnails from SkyView for targets with coordinates."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            {props.rebuildRunning && props.rebuildMode === "ref_thumbnails" ? "Running..." : "Fetch DSS"}
          </button>
          <button
            onClick={() => setShowFullConfirm(true)}
            disabled={anyDisabled()}
            title="Deletes all targets and re-resolves from FITS headers via SIMBAD, SESAME (NED + VizieR), and VizieR enrichment. Cached results make repeat runs fast."
            class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 hover:text-theme-error transition-colors"
          >
            {props.rebuildRunning && props.rebuildMode === "full" ? "Running..." : "Full Rebuild"}
          </button>
        </div>
      </div>

      <Show when={showRefThumbChoice()}>
        <div class="bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-text-primary font-medium">Reference Thumbnails</p>
          <p class="text-xs text-theme-text-secondary">
            Fetch missing thumbnails only, or re-fetch all (replacing existing ones with improved processing)?
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => runAction(() => api.triggerReferenceThumbnails(false))}
              class="px-3 py-1.5 border border-theme-accent text-theme-accent rounded text-xs font-medium hover:bg-theme-accent/20 transition-colors"
            >
              Missing only
            </button>
            <button
              onClick={() => runAction(() => api.triggerReferenceThumbnails(true))}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-theme-accent hover:text-theme-text-primary transition-colors"
            >
              Re-fetch all
            </button>
            <button
              onClick={() => setShowRefThumbChoice(false)}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-white hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </Show>

      <Show when={showFullConfirm()}>
        <div class="bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-error font-medium">Are you sure?</p>
          <p class="text-xs text-theme-error/70">
            This will delete all target records, merge history, and suggested merges.
            All targets will be re-resolved from scratch using SIMBAD with SESAME
            (NED + VizieR) fallback. Fast if results are cached from a previous run.
            First run may take 30 minutes or more depending on the number of unique
            targets and external service response times.
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => runAction(api.rebuildTargets)}
              class="px-3 py-1.5 bg-theme-error text-theme-text-primary rounded text-xs font-medium hover:opacity-90 transition-colors"
            >
              Yes, rebuild everything
            </button>
            <button
              onClick={() => setShowFullConfirm(false)}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-white hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </Show>
    </div>
  );
};

export default MaintenanceActions;
