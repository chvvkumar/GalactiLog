import { type Component, createEffect, createSignal, For, onCleanup, Show } from "solid-js";
import { api } from "../../api/client";
import type { ValidateResponse, RestoreResponse } from "../../api/client";
import { showToast } from "../Toast";

const SECTION_LABELS: Record<string, string> = {
  settings: "Settings",
  session_notes: "Session Notes",
  custom_columns: "Custom Columns",
  target_overrides: "Target Overrides",
  mosaics: "Mosaics",
  users: "User Accounts",
  column_visibility: "Column Visibility",
};

const ALL_SECTIONS = Object.keys(SECTION_LABELS);

export const BackupRestoreTab: Component = () => {
  const [creating, setCreating] = createSignal(false);

  // Restore state
  const [file, setFile] = createSignal<File | null>(null);
  const [validating, setValidating] = createSignal(false);
  const [validation, setValidation] = createSignal<ValidateResponse | null>(null);
  const [selectedSections, setSelectedSections] = createSignal<Set<string>>(new Set(ALL_SECTIONS));
  const [mode, setMode] = createSignal<"merge" | "replace">("merge");
  const [showConfirm, setShowConfirm] = createSignal(false);
  const [restoring, setRestoring] = createSignal(false);
  const [restoreResult, setRestoreResult] = createSignal<RestoreResponse | null>(null);

  let fileInputRef: HTMLInputElement | undefined;
  let cancelButtonRef: HTMLButtonElement | undefined;

  createEffect(() => {
    if (showConfirm()) {
      const handler = (e: KeyboardEvent) => {
        if (e.key === "Escape") setShowConfirm(false);
      };
      window.addEventListener("keydown", handler);
      // Focus the cancel button (safer default for destructive action)
      queueMicrotask(() => cancelButtonRef?.focus());
      onCleanup(() => window.removeEventListener("keydown", handler));
    }
  });

  // ── Backup ──

  const handleCreateBackup = async () => {
    setCreating(true);
    try {
      const blob = await api.createBackup();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const date = new Date().toISOString().slice(0, 10);
      a.download = `galactilog-backup-${date}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Backup created successfully");
    } catch (err) {
      console.error("Backup create failed:", err);
      showToast("Failed to create backup", "error");
    } finally {
      setCreating(false);
    }
  };

  // ── Restore ──

  // Preview counts are derived from the backup content only (not current DB state
  // or mode), so we only need to validate once on file upload. Mode/section changes
  // take effect at restore time.
  const handleFileSelect = async (e: Event) => {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    if (!f) return;

    setFile(f);
    setValidation(null);
    setRestoreResult(null);
    setSelectedSections(new Set(ALL_SECTIONS));
    setMode("merge");
    setValidating(true);

    try {
      const result = await api.validateBackup(f, "merge", ALL_SECTIONS);
      setValidation(result);
      if (result.valid) {
        setSelectedSections(new Set(Object.keys(result.preview)));
      } else {
        showToast(result.error || "Invalid backup file", "error");
      }
    } catch (err) {
      console.error("Backup validate failed:", err);
      showToast("Failed to validate backup file", "error");
    } finally {
      setValidating(false);
    }
  };

  const toggleSection = (section: string) => {
    const current = new Set(selectedSections());
    if (current.has(section)) {
      current.delete(section);
    } else {
      current.add(section);
    }
    setSelectedSections(current);
  };

  const handleRestore = async () => {
    setShowConfirm(false);
    setRestoring(true);
    const f = file();
    if (!f) return;

    try {
      const result = await api.restoreBackup(f, mode(), [...selectedSections()]);
      setRestoreResult(result);
      if (result.success) {
        showToast("Backup restored successfully");
        setFile(null);
        setValidation(null);
        if (fileInputRef) fileInputRef.value = "";
      } else {
        showToast(result.error || "Restore failed", "error");
      }
    } catch (err) {
      console.error("Backup restore failed:", err);
      showToast("Failed to restore backup", "error");
    } finally {
      setRestoring(false);
    }
  };

  const resetRestore = () => {
    setFile(null);
    setValidation(null);
    setRestoreResult(null);
    setShowConfirm(false);
    if (fileInputRef) fileInputRef.value = "";
  };

  return (
    <div class="space-y-8">
      {/* ── Backup Section ── */}
      <section>
        <h3 class="text-lg font-semibold text-theme-text-primary mb-2">Create Backup</h3>
        <p class="text-sm text-theme-text-secondary mb-4">
          Download a backup of all your customizations: settings, filter and equipment
          configurations, session notes, custom columns, mosaics, user accounts, and
          display preferences.
        </p>
        <button
          class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-accent/15 text-theme-accent border border-theme-accent/30 hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
          disabled={creating()}
          onClick={handleCreateBackup}
        >
          {creating() ? "Creating..." : "Create Backup"}
        </button>
      </section>

      <hr class="border-theme-border" />

      {/* ── Restore Section ── */}
      <section>
        <h3 class="text-lg font-semibold text-theme-text-primary mb-2">Restore from Backup</h3>
        <p class="text-sm text-theme-text-secondary mb-4">
          Upload a previously created backup file to restore your customizations.
          You can choose which sections to restore and whether to merge with or replace
          existing data.
        </p>

        <label for="backup-file-input" class="sr-only">Backup file</label>
        <input
          id="backup-file-input"
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          class="block w-full text-sm text-theme-text-secondary file:mr-4 file:py-2 file:px-4 file:rounded-[var(--radius-md)] file:border file:border-theme-border file:text-sm file:font-medium file:bg-theme-elevated file:text-theme-text-primary hover:file:bg-theme-hover file:cursor-pointer"
        />

        <Show when={validating()}>
          <div class="mt-4 text-sm text-theme-text-secondary">Validating backup file...</div>
        </Show>

        <Show when={validation() && validation()!.valid}>
          <div class="mt-4 space-y-4">
            <div class="p-3 rounded-[var(--radius-md)] bg-theme-elevated border border-theme-border">
              <div class="text-sm space-y-1">
                <div>
                  <span class="text-theme-text-secondary">Created: </span>
                  <span class="text-theme-text-primary">
                    {new Date(validation()!.meta!.exported_at).toLocaleString()}
                  </span>
                </div>
                <div>
                  <span class="text-theme-text-secondary">App version: </span>
                  <span class="text-theme-text-primary">{validation()!.meta!.app_version}</span>
                </div>
                <div>
                  <span class="text-theme-text-secondary">Schema version: </span>
                  <span class="text-theme-text-primary">{validation()!.meta!.schema_version}</span>
                </div>
              </div>
            </div>

            <div>
              <h4 class="text-sm font-medium text-theme-text-primary mb-2">Sections to restore</h4>
              <div class="grid grid-cols-2 gap-2">
                <For each={Object.keys(validation()!.preview)}>
                  {(section) => {
                    const preview = () => validation()!.preview[section];
                    const count = () => {
                      const p = preview();
                      return p ? p.add + p.update : 0;
                    };
                    return (
                      <label class="flex items-center gap-2 text-sm text-theme-text-primary cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selectedSections().has(section)}
                          onChange={() => toggleSection(section)}
                          class="rounded"
                        />
                        <span>{SECTION_LABELS[section] || section}</span>
                        <Show when={count() > 0}>
                          <span class="text-theme-text-tertiary">({count()})</span>
                        </Show>
                      </label>
                    );
                  }}
                </For>
              </div>
            </div>

            <div>
              <h4 class="text-sm font-medium text-theme-text-primary mb-2">Restore mode</h4>
              <div class="flex gap-4">
                <label class="flex items-center gap-2 text-sm text-theme-text-primary cursor-pointer">
                  <input
                    type="radio"
                    name="restore-mode"
                    value="merge"
                    checked={mode() === "merge"}
                    onChange={() => setMode("merge")}
                  />
                  <span>Merge</span>
                  <span class="text-theme-text-tertiary">— add new items, update existing</span>
                </label>
                <label class="flex items-center gap-2 text-sm text-theme-text-primary cursor-pointer">
                  <input
                    type="radio"
                    name="restore-mode"
                    value="replace"
                    checked={mode() === "replace"}
                    onChange={() => setMode("replace")}
                  />
                  <span>Replace</span>
                  <span class="text-theme-text-tertiary">— clear sections first</span>
                </label>
              </div>
            </div>

            <Show when={validation()!.warnings.length > 0}>
              <div class="p-3 rounded-[var(--radius-md)] bg-theme-warning/10 border border-theme-warning/30">
                <h4 class="text-sm font-medium text-theme-warning mb-1">Warnings</h4>
                <ul class="text-sm text-theme-text-secondary list-disc list-inside">
                  <For each={validation()!.warnings}>
                    {(w) => <li>{w}</li>}
                  </For>
                </ul>
              </div>
            </Show>

            <div class="flex gap-3">
              <button
                class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-accent/15 text-theme-accent border border-theme-accent/30 hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
                disabled={selectedSections().size === 0 || restoring()}
                onClick={() => setShowConfirm(true)}
              >
                {restoring() ? "Restoring..." : "Restore"}
              </button>
              <button
                class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-elevated text-theme-text-secondary border border-theme-border hover:bg-theme-hover transition-colors"
                onClick={resetRestore}
              >
                Cancel
              </button>
            </div>
          </div>
        </Show>

        <Show when={restoreResult()}>
          <div class={`mt-4 p-3 rounded-[var(--radius-md)] border ${
            restoreResult()!.success
              ? "bg-theme-success/10 border-theme-success/30"
              : "bg-theme-error/10 border-theme-error/30"
          }`}>
            <Show when={restoreResult()!.success}>
              <h4 class="text-sm font-medium text-theme-success mb-2">Restore complete</h4>
              <div class="text-sm text-theme-text-secondary space-y-1">
                <For each={Object.entries(restoreResult()!.applied)}>
                  {([section, counts]) => (
                    <div>
                      {SECTION_LABELS[section] || section}:
                      {" "}{counts.add} added, {counts.update} updated
                      {counts.skip > 0 && `, ${counts.skip} skipped`}
                    </div>
                  )}
                </For>
              </div>

              <Show when={Object.keys(restoreResult()!.temporary_passwords).length > 0}>
                <div class="mt-3 p-3 rounded-[var(--radius-md)] bg-theme-warning/10 border border-theme-warning/30">
                  <h4 class="text-sm font-medium text-theme-warning mb-1">
                    New user accounts — save these passwords
                  </h4>
                  <div class="text-sm font-mono space-y-1">
                    <For each={Object.entries(restoreResult()!.temporary_passwords)}>
                      {([username, password]) => (
                        <div class="text-theme-text-primary">
                          {username}: <span class="select-all">{password}</span>
                        </div>
                      )}
                    </For>
                  </div>
                </div>
              </Show>

              <Show when={restoreResult()!.warnings.length > 0}>
                <div class="mt-2 text-sm text-theme-text-tertiary">
                  <For each={restoreResult()!.warnings}>
                    {(w) => <div>{w}</div>}
                  </For>
                </div>
              </Show>

              <div class="mt-3">
                <button
                  class="px-3 py-1.5 rounded-[var(--radius-md)] bg-theme-elevated text-theme-text-secondary border border-theme-border hover:bg-theme-hover transition-colors text-sm"
                  onClick={resetRestore}
                >
                  Restore another
                </button>
              </div>
            </Show>

            <Show when={!restoreResult()!.success}>
              <h4 class="text-sm font-medium text-theme-error">Restore failed</h4>
              <p class="text-sm text-theme-text-secondary">{restoreResult()!.error}</p>
            </Show>
          </div>
        </Show>
      </section>

      {/* ── Confirmation Modal ── */}
      <Show when={showConfirm()}>
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setShowConfirm(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="backup-restore-confirm-title"
        >
          <div
            class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div class="p-4 border-b border-theme-border">
              <h2 id="backup-restore-confirm-title" class="text-lg font-semibold text-theme-text-primary">Confirm Restore</h2>
            </div>
            <div class="p-4 space-y-3">
              <p class="text-sm text-theme-text-secondary">
                This will <strong class="text-theme-text-primary">{mode()}</strong> the
                following sections:
              </p>
              <ul class="text-sm text-theme-text-primary list-disc list-inside">
                <For each={[...selectedSections()]}>
                  {(s) => <li>{SECTION_LABELS[s]}</li>}
                </For>
              </ul>
              <Show when={mode() === "replace"}>
                <div class="p-2 rounded bg-theme-error/10 border border-theme-error/30 text-sm text-theme-error">
                  Replace mode will clear existing data in the selected sections before restoring.
                </div>
              </Show>
            </div>
            <div class="p-4 border-t border-theme-border flex gap-2 justify-end">
              <button
                ref={cancelButtonRef}
                class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-elevated text-theme-text-secondary border border-theme-border hover:bg-theme-hover transition-colors"
                onClick={() => setShowConfirm(false)}
              >
                Cancel
              </button>
              <button
                class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-accent/15 text-theme-accent border border-theme-accent/30 hover:bg-theme-accent/25 transition-colors"
                onClick={handleRestore}
              >
                Confirm Restore
              </button>
            </div>
          </div>
        </div>
      </Show>
    </div>
  );
};
