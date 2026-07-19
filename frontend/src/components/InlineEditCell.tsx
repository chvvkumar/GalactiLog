import { createSignal, Show, For, createEffect, on, untrack } from "solid-js";
import { showToast } from "./Toast";
import { getErrorMessage } from "../utils/errors";

interface Props {
  columnType: "boolean" | "text" | "dropdown";
  value: string | undefined;
  dropdownOptions?: string[] | null;
  onSave: (value: string) => void | Promise<void>;
}

export default function InlineEditCell(props: Props) {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const [localValue, setLocalValue] = createSignal(props.value);
  const [saving, setSaving] = createSignal(false);

  // Sync from props when external data changes (e.g. refetch), but never
  // stomp on an in-flight save that has not yet resolved. Track only
  // props.value: tracking saving() too would re-run this when a save
  // finishes and clobber the just-committed value with a stale prop.
  createEffect(on(
    () => props.value,
    (incoming) => {
      if (!untrack(saving)) setLocalValue(incoming);
    },
  ));

  // Confirm-then-commit: keep the old value visible (with a spinner) until the
  // save resolves. On success show the new value; on failure keep the old value
  // and surface the error.
  async function save(val: string) {
    const previous = localValue();
    setSaving(true);
    try {
      await Promise.resolve(props.onSave(val));
      setLocalValue(val);
    } catch (e) {
      setLocalValue(previous);
      showToast(getErrorMessage(e, "Failed to save"), "error", 5000);
    } finally {
      setSaving(false);
    }
  }

  function startEdit() {
    if (saving()) return;
    setDraft(localValue() ?? "");
    setEditing(true);
  }

  function saveText() {
    setEditing(false);
    const val = draft();
    if (val !== (localValue() ?? "")) void save(val);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") saveText();
    if (e.key === "Escape") setEditing(false);
  }

  // Saving feedback is the greyed-out disabled control itself; anything that
  // mounts next to it (spinner) flashes on fast LAN saves and reads as a
  // rendering artifact.

  // Boolean: simple checkbox
  if (props.columnType === "boolean") {
    return (
      <span class="inline-flex items-center">
        <input
          type="checkbox"
          checked={localValue() === "true"}
          disabled={saving()}
          onChange={(e) => {
            const el = e.currentTarget;
            const want = el.checked ? "true" : "false";
            // Confirm-then-commit: snap the DOM back to the committed value;
            // a successful save flips localValue and re-checks it. Without
            // this a failed save leaves the DOM out of sync, since the
            // unchanged signal never rewrites the checked attribute.
            el.checked = localValue() === "true";
            void save(want);
          }}
          class="cursor-pointer disabled:opacity-40"
          title={saving() ? "Saving..." : undefined}
        />
      </span>
    );
  }

  // Dropdown: select
  if (props.columnType === "dropdown") {
    return (
      <span class="inline-flex items-center">
        <select
          value={localValue() ?? ""}
          disabled={saving()}
          onChange={(e) => {
            const val = e.currentTarget.value;
            if (val) void save(val);
          }}
          class="px-1 py-0.5 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm disabled:opacity-40"
          title={saving() ? "Saving..." : undefined}
        >
          <option value="">-</option>
          <For each={props.dropdownOptions ?? []}>
            {(opt) => <option value={opt}>{opt}</option>}
          </For>
        </select>
      </span>
    );
  }

  // Text: click-to-edit
  return (
    <Show
      when={editing()}
      fallback={
        <span
          onClick={startEdit}
          class="cursor-pointer min-w-[2rem] inline-block hover:bg-theme-hover rounded px-1"
          classList={{ "opacity-40 cursor-wait": saving() }}
          title={saving() ? "Saving..." : "Click to edit"}
        >
          {localValue() || "-"}
        </span>
      }
    >
      <input
        type="text"
        value={draft()}
        onInput={(e) => setDraft(e.currentTarget.value)}
        onBlur={saveText}
        onKeyDown={handleKeyDown}
        class="px-1 py-0.5 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm w-full"
        autofocus
      />
    </Show>
  );
}
