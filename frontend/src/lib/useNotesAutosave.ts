import { createSignal, createEffect, onCleanup } from "solid-js";
import { showToast } from "../components/Toast";
import { getErrorMessage } from "../utils/errors";

interface Options {
  /**
   * Current server-side value for the notes field. Return `undefined` while the
   * source data has not loaded yet so seeding is deferred until real data
   * arrives; return `null`/`""` for an intentionally empty value.
   */
  serverValue: () => string | null | undefined;
  /** Persist the edited text. Should reject on failure. */
  save: (text: string) => Promise<void>;
  /** Debounce delay in ms before saving. Defaults to 1000. */
  delay?: number;
  /** Toast message shown when a save fails. */
  errorLabel?: string;
}

/**
 * Autosave rule shared by target and mosaic notes:
 *  - Seed the field from server data once it loads.
 *  - While the user has unsaved typing (dirty), never overwrite from a refetch.
 *  - When not dirty, reflect the server value including clears (external edits).
 *
 * `lastServer` tracks the last server value we applied so that a stale refetch
 * carrying the pre-save value cannot revert the field right after a save.
 */
export function useNotesAutosave(opts: Options) {
  const [notes, setNotesRaw] = createSignal("");
  const [dirty, setDirty] = createSignal(false);
  const [saving, setSaving] = createSignal(false);
  let lastServer: string | undefined = undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  createEffect(() => {
    const sv = opts.serverValue();
    if (sv === undefined) return; // not loaded yet
    const s = sv ?? "";
    if (s === lastServer) return; // no external change
    lastServer = s;
    if (!dirty()) setNotesRaw(s); // reflect only when the field is clean
  });

  const onInput = (text: string) => {
    setNotesRaw(text);
    setDirty(true);
    clearTimeout(timer);
    timer = setTimeout(async () => {
      setSaving(true);
      try {
        await opts.save(text);
        // Treat the saved text as the known server value so a lagging refetch
        // reporting the old value does not clobber it, then re-open to external
        // changes.
        lastServer = text;
        setDirty(false);
      } catch (e) {
        showToast(getErrorMessage(e, opts.errorLabel ?? "Failed to save notes"), "error", 5000);
      } finally {
        setSaving(false);
      }
    }, opts.delay ?? 1000);
  };

  onCleanup(() => clearTimeout(timer));

  return { notes, onInput, saving };
}
