import { createSignal, Show, For, createEffect } from "solid-js";

interface Props {
  columnType: "boolean" | "text" | "dropdown";
  value: string | undefined;
  dropdownOptions?: string[] | null;
  onSave: (value: string) => void;
}

export default function InlineEditCell(props: Props) {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const [localValue, setLocalValue] = createSignal(props.value);

  // Sync from props when external data changes (e.g. refetch)
  createEffect(() => {
    setLocalValue(props.value);
  });

  function save(val: string) {
    setLocalValue(val);
    props.onSave(val);
  }

  function startEdit() {
    setDraft(localValue() ?? "");
    setEditing(true);
  }

  function saveText() {
    save(draft());
    setEditing(false);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") saveText();
    if (e.key === "Escape") setEditing(false);
  }

  // Boolean: simple checkbox
  if (props.columnType === "boolean") {
    return (
      <input
        type="checkbox"
        checked={localValue() === "true"}
        onChange={(e) => save(e.currentTarget.checked ? "true" : "false")}
        class="cursor-pointer"
      />
    );
  }

  // Dropdown: select
  if (props.columnType === "dropdown") {
    return (
      <select
        value={localValue() ?? ""}
        onChange={(e) => {
          const val = e.currentTarget.value;
          if (val) save(val);
        }}
        class="px-1 py-0.5 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
      >
        <option value="">-</option>
        <For each={props.dropdownOptions ?? []}>
          {(opt) => <option value={opt}>{opt}</option>}
        </For>
      </select>
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
          title="Click to edit"
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
