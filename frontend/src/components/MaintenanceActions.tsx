import { Component, Show, createSignal } from "solid-js";
import { api } from "../api/client";
import { emitWithToast } from "../lib/emitWithToast";

const MaintenanceActions: Component = () => {
  const [showFullConfirm, setShowFullConfirm] = createSignal(false);
  const [showRefThumbChoice, setShowRefThumbChoice] = createSignal(false);
  const [showRegenChoice, setShowRegenChoice] = createSignal(false);
  const [confirmPurgeRegen, setConfirmPurgeRegen] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  const run = async (fn: () => Promise<void>) => {
    if (busy()) return;
    setBusy(true);
    setShowFullConfirm(false);
    setShowRefThumbChoice(false);
    setShowRegenChoice(false);
    setConfirmPurgeRegen(false);
    try { await fn(); } finally { setBusy(false); }
  };

  const fixOrphans = () => run(() => emitWithToast({
    action: () => api.smartRebuildTargets() as Promise<{ task_id: string }>,
    pendingLabel: "Starting Fix Orphans...",
    successLabel: "Fix Orphans complete",
    errorLabel: "Fix Orphans failed",
    category: "rebuild",
    taskLabel: "Fix Orphans",
    timeout: 600_000,
  }));

  const reResolve = () => run(() => emitWithToast({
    action: () => api.retryUnresolved() as Promise<{ task_id: string }>,
    pendingLabel: "Starting Re-resolve...",
    successLabel: "Re-resolve complete",
    errorLabel: "Re-resolve failed",
    category: "enrichment",
    taskLabel: "Re-resolve targets",
    timeout: 600_000,
  }));

  const catalogMatch = () => run(() => emitWithToast({
    action: () => api.triggerXmatchEnrichment() as Promise<{ task_id: string }>,
    pendingLabel: "Starting Catalog Match...",
    successLabel: "Catalog Match complete",
    errorLabel: "Catalog Match failed",
    category: "enrichment",
    taskLabel: "Catalog Match",
    timeout: 600_000,
  }));

  const fetchDss = (forceAll: boolean) => run(() => emitWithToast({
    action: () => api.triggerReferenceThumbnails(forceAll) as Promise<{ task_id: string }>,
    pendingLabel: "Starting DSS fetch...",
    successLabel: "DSS fetch complete",
    errorLabel: "DSS fetch failed",
    category: "thumbnail",
    taskLabel: forceAll ? "Fetch DSS (all)" : "Fetch DSS (missing)",
    timeout: 600_000,
  }));

  const regenThumbs = (purge: boolean) => run(() => emitWithToast({
    action: () => api.regenerateThumbnails({ purge }) as Promise<{ task_id: string }>,
    pendingLabel: purge ? "Deleting and regenerating thumbnails..." : "Regenerating thumbnails...",
    successLabel: "Thumbnail regeneration complete",
    errorLabel: "Thumbnail regeneration failed",
    category: "thumbnail",
    taskLabel: purge ? "Regen Thumbnails (purge)" : "Regen Thumbnails",
    timeout: 1_800_000,
  }));

  const fullRebuild = () => run(() => emitWithToast({
    action: () => api.rebuildTargets() as Promise<{ task_id: string }>,
    pendingLabel: "Starting Full Rebuild...",
    successLabel: "Full Rebuild complete",
    errorLabel: "Full Rebuild failed",
    category: "rebuild",
    taskLabel: "Full Rebuild",
    timeout: 3_600_000,
  }));

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Maintenance</h3>
        <div class="flex gap-2 flex-shrink-0 flex-wrap">
          <button
            onClick={fixOrphans}
            disabled={busy()}
            title="Re-matches orphaned images to existing targets using known aliases and cached SIMBAD results. Fast and offline - no network calls needed."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Fix Orphans
          </button>
          <button
            onClick={reResolve}
            disabled={busy()}
            title="Clears SIMBAD negative cache and SESAME cache, then re-resolves unresolved targets through SIMBAD and SESAME (NED + VizieR). Existing targets are not affected."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Re-resolve
          </button>
          <button
            onClick={catalogMatch}
            disabled={busy()}
            title="Runs bulk cross-match enrichment against external catalogs (Caldwell, Herschel 400, Arp, Abell) for all targets."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Catalog Match
          </button>
          <button
            onClick={() => setShowRefThumbChoice(true)}
            disabled={busy()}
            title="Fetch DSS reference thumbnails from SkyView for targets with coordinates."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Fetch DSS
          </button>
          <button
            onClick={() => setShowRegenChoice(true)}
            disabled={busy()}
            title="Re-create all thumbnails using current stretch settings. Optionally delete existing thumbnails first."
            class="px-3 py-1.5 bg-theme-warning/15 text-theme-warning border border-theme-warning/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-warning/25 transition-colors"
          >
            Regen Thumbs
          </button>
          <button
            onClick={() => setShowFullConfirm(true)}
            disabled={busy()}
            title="Deletes all targets and re-resolves from FITS headers via SIMBAD, SESAME (NED + VizieR), and VizieR enrichment. Cached results make repeat runs fast."
            class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 hover:text-theme-error transition-colors"
          >
            Full Rebuild
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
              onClick={() => fetchDss(false)}
              class="px-3 py-1.5 border border-theme-accent text-theme-accent rounded text-xs font-medium hover:bg-theme-accent/20 transition-colors"
            >
              Missing only
            </button>
            <button
              onClick={() => fetchDss(true)}
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

      <Show when={showRegenChoice() && !confirmPurgeRegen()}>
        <div class="bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-text-primary font-medium">Regenerate Thumbnails</p>
          <p class="text-xs text-theme-text-secondary">
            Regenerate in place (overwrite existing files), or delete all thumbnails first then regenerate?
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => regenThumbs(false)}
              class="px-3 py-1.5 border border-theme-accent text-theme-accent rounded text-xs font-medium hover:bg-theme-accent/20 transition-colors"
            >
              Regenerate in place
            </button>
            <button
              onClick={() => setConfirmPurgeRegen(true)}
              class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-xs hover:bg-theme-error/20 transition-colors"
            >
              Delete & regenerate
            </button>
            <button
              onClick={() => setShowRegenChoice(false)}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:border-white hover:text-theme-text-primary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </Show>

      <Show when={confirmPurgeRegen()}>
        <div class="bg-theme-error/20 border border-theme-error/50 rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-error font-medium">Delete all thumbnails?</p>
          <p class="text-xs text-theme-error/70">
            This will delete every thumbnail file on disk and then regenerate each one
            from the original FITS/XISF data using current stretch settings. Database
            records are not affected. Progress will be reported in the activity log.
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => regenThumbs(true)}
              class="px-3 py-1.5 bg-theme-error text-theme-text-primary rounded text-xs font-medium hover:opacity-90 transition-colors"
            >
              Yes, delete and regenerate
            </button>
            <button
              onClick={() => { setConfirmPurgeRegen(false); setShowRegenChoice(false); }}
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
              onClick={fullRebuild}
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
