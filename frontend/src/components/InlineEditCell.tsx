import { createSignal, Show, For } from "solid-js";

interface Props {
  columnType: "boolean" | "text" | "dropdown";
  value: string | undefined;
  dropdownOptions?: string[] | null;
  onSave: (value: string) => void;
}

export default function InlineEditCell(props: Props) {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");

  function startEdit() {
    setDraft(props.value ?? "");
    setEditing(true);
  }

  function save() {
    props.onSave(draft());
    setEditing(false);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") save();
    if (e.key === "Escape") setEditing(false);
  }

  // Boolean: simple checkbox, no edit mode needed
  if (props.columnType === "boolean") {
    return (
      <input
        type="checkbox"
        checked={props.value === "true"}
        onChange={(e) => props.onSave(e.currentTarget.checked ? "true" : "false")}
        class="cursor-pointer"
      />
    );
  }

  // Dropdown: always shows select
  if (props.columnType === "dropdown") {
    return (
      <select
        value={props.value ?? ""}
        onChange={(e) => props.onSave(e.currentTarget.value)}
        class="px-1 py-0.5 rounded border border-[var(--border)] bg-transparent text-sm"
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
          class="cursor-pointer min-w-[2rem] inline-block hover:bg-[var(--bg-secondary)] rounded px-1"
          title="Click to edit"
        >
          {props.value || "-"}
        </span>
      }
    >
      <input
        type="text"
        value={draft()}
        onInput={(e) => setDraft(e.currentTarget.value)}
        onBlur={save}
        onKeyDown={handleKeyDown}
        class="px-1 py-0.5 rounded border border-[var(--border)] bg-transparent text-sm w-full"
        autofocus
      />
    </Show>
  );
}
