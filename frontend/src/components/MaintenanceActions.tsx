import { Component, Show, createSignal } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { emitWithToast } from "../lib/emitWithToast";
import Button from "./ui/Button";

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
    action: () =>
      apiClient
        .POST("/api/scan/generate-reference-thumbnails", { params: { query: { force: forceAll || undefined } } })
        .then(unwrap) as Promise<{ task_id: string }>,
    pendingLabel: "Starting reference image fetch...",
    successLabel: "Reference image fetch complete",
    errorLabel: "Reference image fetch failed",
    category: "thumbnail",
    taskLabel: forceAll ? "Fetch Reference Images (all)" : "Fetch Reference Images (missing)",
    timeout: 600_000,
  }));

  const regenThumbs = (opts: { purge?: boolean; missingOnly?: boolean }) => run(() => emitWithToast({
    action: () =>
      apiClient
        .POST("/api/scan/regenerate-thumbnails", {
          params: { query: { purge: opts.purge || undefined, missing_only: opts.missingOnly || undefined } },
        })
        .then(unwrap) as Promise<{ task_id: string }>,
    pendingLabel: opts.missingOnly ? "Checking for missing thumbnails..." : opts.purge ? "Deleting and regenerating thumbnails..." : "Regenerating thumbnails...",
    successLabel: "Thumbnail regeneration complete",
    errorLabel: "Thumbnail regeneration failed",
    category: "thumbnail",
    taskLabel: opts.missingOnly ? "Regen Thumbnails (missing)" : opts.purge ? "Regen Thumbnails (purge)" : "Regen Thumbnails",
    timeout: 1_800_000,
  }));

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex justify-between items-center flex-wrap gap-2">
        <h3 class="text-theme-text-primary font-medium">Maintenance</h3>
        <div class="flex gap-2 flex-shrink-0 flex-wrap">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowRefThumbChoice(true)}
            disabled={busy()}
            title="Downloads survey images from NASA SkyView for targets with coordinates."
          >
            Fetch Reference Images
          </Button>
          <Button
            variant="warning"
            size="sm"
            onClick={() => setShowRegenChoice(true)}
            disabled={busy()}
            title="Re-create all thumbnails using current stretch settings. Optionally delete existing thumbnails first."
          >
            Regenerate Thumbnails
          </Button>
        </div>
      </div>

      <Show when={showRefThumbChoice()}>
        <div class="bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-text-primary font-medium">Fetch Reference Images</p>
          <p class="text-xs text-theme-text-secondary">
            Downloads survey images from NASA SkyView. Fetch missing images only, or re-fetch all (replacing existing ones with improved processing)?
          </p>
          <div class="flex gap-2 pt-1">
            <Button variant="primary" size="sm" onClick={() => fetchRefImages(false)}>
              Missing only
            </Button>
            <Button variant="secondary" size="sm" onClick={() => fetchRefImages(true)}>
              Re-fetch all
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setShowRefThumbChoice(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Show>

      <Show when={showRegenChoice() && !confirmPurgeRegen()}>
        <div class="bg-theme-surface border border-theme-border-em rounded-[var(--radius-md)] p-3 space-y-2">
          <p class="text-sm text-theme-text-primary font-medium">Regenerate Thumbnails</p>
          <p class="text-xs text-theme-text-secondary">
            Regenerate only missing files (fast), overwrite all existing files, or delete all then regenerate?
          </p>
          <div class="flex gap-2 pt-1">
            <Button variant="primary" size="sm" onClick={() => regenThumbs({ missingOnly: true })}>
              Missing only
            </Button>
            <Button variant="secondary" size="sm" onClick={() => regenThumbs({})}>
              Regenerate all
            </Button>
            <Button variant="danger" size="sm" onClick={() => setConfirmPurgeRegen(true)}>
              Delete & regenerate
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setShowRegenChoice(false)}>
              Cancel
            </Button>
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
            <Button variant="danger" size="sm" onClick={() => regenThumbs({ purge: true })}>
              Yes, delete and regenerate
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => { setConfirmPurgeRegen(false); setShowRegenChoice(false); }}
            >
              Cancel
            </Button>
          </div>
        </div>
      </Show>
    </div>
  );
};

export default MaintenanceActions;
