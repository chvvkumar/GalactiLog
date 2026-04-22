import { Component, Show, createSignal } from "solid-js";
import { api } from "../api/client";
import { emitWithToast } from "../lib/emitWithToast";

const MaintenanceActions: Component = () => {
  const [showRefThumbChoice, setShowRefThumbChoice] = createSignal(false);
  const [showRegenChoice, setShowRegenChoice] = createSignal(false);
  const [confirmPurgeRegen, setConfirmPurgeRegen] = createSignal(false);
  const [busy, setBusy] = createSignal(false);

  const run = async (fn: () => Promise<void>) => {
    if (busy()) return;
    setBusy(true);
    setShowRefThumbChoice(false);
    setShowRegenChoice(false);
    setConfirmPurgeRegen(false);
    try { await fn(); } finally { setBusy(false); }
  };

  const fetchRefImages = (forceAll: boolean) => run(() => emitWithToast({
    action: () => api.triggerReferenceThumbnails(forceAll) as Promise<{ task_id: string }>,
    pendingLabel: "Starting reference image fetch...",
    successLabel: "Reference image fetch complete",
    errorLabel: "Reference image fetch failed",
    category: "thumbnail",
    taskLabel: forceAll ? "Fetch Reference Images (all)" : "Fetch Reference Images (missing)",
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

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Maintenance</h3>
        <div class="flex gap-2 flex-shrink-0 flex-wrap">
          <button
            onClick={() => setShowRefThumbChoice(true)}
            disabled={busy()}
            title="Downloads survey images from NASA SkyView for targets with coordinates."
            class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
          >
            Fetch Reference Images
          </button>
          <button
            onClick={() => setShowRegenChoice(true)}
            disabled={busy()}
            title="Re-create all thumbnails using current stretch settings. Optionally delete existing thumbnails first."
            class="px-3 py-1.5 bg-theme-warning/15 text-theme-warning border border-theme-warning/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-warning/25 transition-colors"
          >
            Regenerate Thumbnails
          </button>
        </div>
      </div>

      <Show when={showRefThumbChoice()}>
        <div class="bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-text-primary font-medium">Fetch Reference Images</p>
          <p class="text-xs text-theme-text-secondary">
            Downloads survey images from NASA SkyView. Fetch missing images only, or re-fetch all (replacing existing ones with improved processing)?
          </p>
          <div class="flex gap-2 pt-1">
            <button
              onClick={() => fetchRefImages(false)}
              class="px-3 py-1.5 border border-theme-accent text-theme-accent rounded text-xs font-medium hover:bg-theme-accent/20 transition-colors"
            >
              Missing only
            </button>
            <button
              onClick={() => fetchRefImages(true)}
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
    </div>
  );
};

export default MaintenanceActions;
