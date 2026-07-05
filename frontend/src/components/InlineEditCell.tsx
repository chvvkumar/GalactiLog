import { createSignal, Show, For, createEffect } from "solid-js";
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
  // stomp on an in-flight save that has not yet resolved.
  createEffect(() => {
    const incoming = props.value;
    if (!saving()) setLocalValue(incoming);
  });

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

  const Spinner = () => (
    <span
      class="inline-block w-3 h-3 ml-1 align-middle border border-theme-border border-t-theme-accent rounded-full animate-spin"
      aria-label="Saving"
    />
  );

  // Boolean: simple checkbox
  if (props.columnType === "boolean") {
    return (
      <span class="inline-flex items-center">
        <input
          type="checkbox"
          checked={localValue() === "true"}
          disabled={saving()}
          onChange={(e) => void save(e.currentTarget.checked ? "true" : "false")}
          class="cursor-pointer disabled:opacity-50"
        />
        <Show when={saving()}><Spinner /></Show>
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
          class="px-1 py-0.5 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm disabled:opacity-50"
        >
          <option value="">-</option>
          <For each={props.dropdownOptions ?? []}>
            {(opt) => <option value={opt}>{opt}</option>}
          </For>
        </select>
        <Show when={saving()}><Spinner /></Show>
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
          classList={{ "opacity-60 cursor-wait": saving() }}
          title={saving() ? "Saving..." : "Click to edit"}
        >
          {localValue() || "-"}
          <Show when={saving()}><Spinner /></Show>
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
