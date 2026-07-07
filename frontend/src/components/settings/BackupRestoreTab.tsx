import { type Component, createEffect, createSignal, For, onCleanup, Show } from "solid-js";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import type {
  ValidateResponse as GeneratedValidateResponse,
  RestoreResponse as GeneratedRestoreResponse,
  SectionPreview,
} from "../../api/types";
import { showToast } from "../Toast";
import HelpPopover from "../HelpPopover";
import { useSettingsContext } from "../SettingsProvider";
import { formatDateTime } from "../../utils/dateTime";

// The generated ValidateResponse/RestoreResponse type `preview`/`warnings`/
// `applied`/`temporary_passwords` as optional (OpenAPI drops the backend's
// Pydantic defaults). The backend always populates them when
// `valid`/`success` is true, matching the old hand-written client.ts's
// required-field versions that this component's rendering logic
// (`validation()!.preview[section]`, `.warnings.length`, etc.) depends on.
// Re-narrowed here; casts at the two fetch call sites below reflect actual
// runtime data, not a behavior change.
type ValidateResponse = Omit<GeneratedValidateResponse, "preview" | "warnings"> & {
  preview: Record<string, SectionPreview>;
  warnings: string[];
};
type RestoreResponse = Omit<GeneratedRestoreResponse, "applied" | "temporary_passwords" | "warnings"> & {
  applied: Record<string, SectionPreview>;
  temporary_passwords: Record<string, string>;
  warnings: string[];
};

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
  const { timezone, use24hTime } = useSettingsContext();
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
      // The generated schema types this endpoint's success body as `unknown`
      // (FastAPI's StreamingResponse download isn't declared with a content
      // schema); `parseAs: "blob"` matches the old fetchWithRefresh(...).blob()
      // behavior -- same pattern as TargetDetailPage.tsx's reference-thumbnail
      // fetch and MosaicCompositeModal.tsx's composite fetch.
      const blob = (await apiClient
        .POST("/api/backup/create", { parseAs: "blob" })
        .then(unwrap)) as Blob;
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
      // The generated ValidateResponse types `preview`/`warnings` as optional
      // (OpenAPI drops FastAPI's Pydantic defaults); the backend always
      // populates them when `valid` is true, matching the old hand-written
      // client.ts's required-field ValidateResponse that this component's
      // logic (`validation()!.preview[section]`, `.warnings.length`, etc.)
      // depends on. Cast reflects actual runtime data, not a behavior change
      // -- same precedent as SettingsProvider.tsx's bootstrap cast.
      const result = (await apiClient
        .POST("/api/backup/validate", {
          // The generated Body_validate_backup_endpoint_..._post schema types
          // `file` as `string` (OpenAPI's binary-format looseness); a real
          // File is passed at runtime and handed to bodySerializer below,
          // which builds actual multipart FormData -- see openapi-fetch docs
          // on bodySerializer for multipart/form-data.
          body: { file: f, mode: "merge", sections: ALL_SECTIONS.join(",") } as unknown as never,
          bodySerializer(body) {
            const fd = new FormData();
            for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
              fd.append(key, value as string | Blob);
            }
            return fd;
          },
        })
        .then(unwrap)) as ValidateResponse;
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
      // Same discrepancy as validateBackup above: generated RestoreResponse
      // types `applied`/`temporary_passwords`/`warnings` as optional; the
      // backend always populates them when `success` is true. Cast reflects
      // actual runtime data.
      const result = (await apiClient
        .POST("/api/backup/restore", {
          body: {
            file: f,
            mode: mode(),
            sections: [...selectedSections()].join(","),
          } as unknown as never,
          bodySerializer(body) {
            const fd = new FormData();
            for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
              fd.append(key, value as string | Blob);
            }
            return fd;
          },
        })
        .then(unwrap)) as RestoreResponse;
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
    <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
      <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Create Backup</h2>
          <HelpPopover title="Create Backup">
            <p>Exports every user-facing customization as a versioned JSON file: settings, filter and equipment configurations, session notes, custom columns, mosaic definitions, user accounts, and display preferences.</p>
            <p>The backup does not include scanned FITS file data or derived catalog tables. Those are rebuilt by running a scan against the same library.</p>
            <p>Example: run Create Backup before upgrading the app, save the file somewhere safe, then restore on the upgraded instance if anything goes wrong.</p>
          </HelpPopover>
        </div>
        <button
          class="px-4 py-2 rounded-[var(--radius-md)] bg-theme-accent/15 text-theme-accent border border-theme-accent/30 hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
          disabled={creating()}
          onClick={handleCreateBackup}
        >
          {creating() ? "Creating..." : "Create Backup"}
        </button>
      </section>

      <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Restore from Backup</h2>
          <HelpPopover title="Restore from Backup">
            <p>Imports a previously created backup file. After selecting the file, pick which sections to restore and choose a restore mode.</p>
            <p>Merge mode adds or updates items from the backup and leaves everything else untouched. Replace mode first clears each selected section, then imports its contents from the file.</p>
            <p>Backups carry a schema version; older files restore cleanly against newer app versions. When restoring user accounts, temporary passwords are generated and shown once, so copy them before closing the result dialog.</p>
            <p>Example: restore only the Session Notes section in Merge mode to recover notes lost to an accidental deletion, without touching filter or equipment config.</p>
          </HelpPopover>
        </div>

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
                    {formatDateTime(validation()!.meta!.exported_at, timezone(), use24hTime())}
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
                  <span class="text-theme-text-tertiary">- add new items, update existing</span>
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
                  <span class="text-theme-text-tertiary">- clear sections first</span>
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
                    New user accounts - save these passwords
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
