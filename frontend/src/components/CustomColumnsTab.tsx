import { createSignal, createResource, For, Show } from "solid-js";
import { api } from "../api/client";
import type { CustomColumn } from "../types";

function OptionsList(props: { options: string[]; onChange: (opts: string[]) => void }) {
  const [draft, setDraft] = createSignal("");

  function addOption() {
    const val = draft().trim();
    if (!val || props.options.includes(val)) return;
    props.onChange([...props.options, val]);
    setDraft("");
  }

  function removeOption(index: number) {
    props.onChange(props.options.filter((_, i) => i !== index));
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      addOption();
    }
  }

  return (
    <div class="space-y-1.5">
      <div class="flex flex-wrap gap-1.5">
        <For each={props.options}>
          {(opt, i) => (
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-theme-elevated border border-theme-border text-sm">
              {opt}
              <button
                onClick={() => removeOption(i())}
                class="text-theme-text-tertiary hover:text-red-400 text-xs leading-none"
                title="Remove"
              >x</button>
            </span>
          )}
        </For>
      </div>
      <div class="flex gap-1.5">
        <input
          type="text"
          value={draft()}
          onInput={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={handleKeyDown}
          class="px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm flex-1"
          placeholder="Type an option and press Enter"
        />
        <button
          onClick={addOption}
          class="px-2 py-1 rounded border border-theme-border text-theme-text-secondary hover:text-theme-accent text-sm"
          title="Add option"
        >+</button>
      </div>
    </div>
  );
}

export default function CustomColumnsTab() {
  const [columns, { refetch }] = createResource(() => api.getCustomColumns());
  const [newName, setNewName] = createSignal("");
  const [newType, setNewType] = createSignal<"boolean" | "text" | "dropdown">("boolean");
  const [newAppliesTo, setNewAppliesTo] = createSignal<"target" | "session" | "rig">("target");
  const [newOptions, setNewOptions] = createSignal<string[]>([]);
  const [editingId, setEditingId] = createSignal<string | null>(null);
  const [editName, setEditName] = createSignal("");
  const [editOptions, setEditOptions] = createSignal<string[]>([]);

  async function handleCreate() {
    const name = newName().trim();
    if (!name) return;
    const body: Parameters<typeof api.createCustomColumn>[0] = {
      name,
      column_type: newType(),
      applies_to: newAppliesTo(),
    };
    if (newType() === "dropdown") {
      body.dropdown_options = newOptions();
    }
    await api.createCustomColumn(body);
    setNewName("");
    setNewOptions([]);
    refetch();
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this column and all its values?")) return;
    await api.deleteCustomColumn(id);
    refetch();
  }

  function startEdit(col: CustomColumn) {
    setEditingId(col.id);
    setEditName(col.name);
    setEditOptions(col.dropdown_options ?? []);
  }

  async function handleSaveEdit(col: CustomColumn) {
    const updates: Parameters<typeof api.updateCustomColumn>[1] = {};
    const name = editName().trim();
    if (name && name !== col.name) updates.name = name;
    if (col.column_type === "dropdown") {
      updates.dropdown_options = editOptions();
    }
    await api.updateCustomColumn(col.id, updates);
    setEditingId(null);
    refetch();
  }

  async function moveColumn(col: CustomColumn, direction: -1 | 1) {
    await api.updateCustomColumn(col.id, { display_order: col.display_order + direction });
    refetch();
  }

  return (
    <div class="space-y-6">
      <h3 class="text-lg font-semibold">Custom Columns</h3>
      <p class="text-sm text-theme-text-secondary">
        Define custom columns that appear in the dashboard and session tables.
        All users share the same column definitions and values.
      </p>

      {/* Create Form */}
      <div class="rounded-lg border border-theme-border p-4 space-y-3">
        <h4 class="font-medium">Add Column</h4>
        <div class="flex flex-wrap gap-3 items-end">
          <div>
            <label class="block text-xs mb-1">Name</label>
            <input
              type="text"
              value={newName()}
              onInput={(e) => setNewName(e.currentTarget.value)}
              class="px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
              placeholder="e.g. Processed"
            />
          </div>
          <div>
            <label class="block text-xs mb-1">Type</label>
            <select
              value={newType()}
              onChange={(e) => setNewType(e.currentTarget.value as any)}
              class="px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
            >
              <option value="boolean">Boolean</option>
              <option value="text">Text</option>
              <option value="dropdown">Dropdown</option>
            </select>
          </div>
          <div>
            <label class="block text-xs mb-1">Applies To</label>
            <select
              value={newAppliesTo()}
              onChange={(e) => setNewAppliesTo(e.currentTarget.value as any)}
              class="px-2 py-1 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm"
            >
              <option value="target">Target</option>
              <option value="session">Session</option>
              <option value="rig">Rig</option>
            </select>
          </div>
          <button
            onClick={handleCreate}
            class="px-3 py-1 rounded bg-theme-accent text-white text-sm hover:opacity-90"
          >
            Add
          </button>
        </div>
        <Show when={newType() === "dropdown"}>
          <div>
            <label class="block text-xs mb-1">Dropdown Options</label>
            <OptionsList options={newOptions()} onChange={setNewOptions} />
          </div>
        </Show>
      </div>

      {/* Existing Columns */}
      <Show when={columns()?.length} fallback={<p class="text-sm text-theme-text-secondary">No custom columns defined yet.</p>}>
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-theme-border text-left text-theme-text-secondary">
              <th class="py-2 px-2">Order</th>
              <th class="py-2 px-2">Name</th>
              <th class="py-2 px-2">Type</th>
              <th class="py-2 px-2">Applies To</th>
              <th class="py-2 px-2">Options</th>
              <th class="py-2 px-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            <For each={columns()}>
              {(col) => (
                <tr class="border-b border-theme-border">
                  <td class="py-2 px-2">
                    <div class="flex gap-1">
                      <button onClick={() => moveColumn(col, -1)} class="text-xs hover:text-theme-accent" title="Move up">^</button>
                      <button onClick={() => moveColumn(col, 1)} class="text-xs hover:text-theme-accent" title="Move down">v</button>
                    </div>
                  </td>
                  <td class="py-2 px-2">
                    <Show when={editingId() === col.id} fallback={col.name}>
                      <input
                        type="text"
                        value={editName()}
                        onInput={(e) => setEditName(e.currentTarget.value)}
                        class="px-1 py-0.5 rounded border border-theme-border bg-theme-input text-theme-text-primary text-sm w-full"
                      />
                    </Show>
                  </td>
                  <td class="py-2 px-2 capitalize">{col.column_type}</td>
                  <td class="py-2 px-2 capitalize">{col.applies_to}</td>
                  <td class="py-2 px-2">
                    <Show when={editingId() === col.id && col.column_type === "dropdown"}
                      fallback={
                        <div class="flex flex-wrap gap-1">
                          <For each={col.dropdown_options ?? []}>
                            {(opt) => (
                              <span class="px-1.5 py-0.5 rounded bg-theme-elevated border border-theme-border text-xs">{opt}</span>
                            )}
                          </For>
                          <Show when={!col.dropdown_options?.length}>
                            <span class="text-theme-text-tertiary">-</span>
                          </Show>
                        </div>
                      }
                    >
                      <OptionsList options={editOptions()} onChange={setEditOptions} />
                    </Show>
                  </td>
                  <td class="py-2 px-2">
                    <div class="flex gap-2">
                      <Show
                        when={editingId() === col.id}
                        fallback={
                          <button onClick={() => startEdit(col)} class="text-xs text-theme-accent hover:underline">Edit</button>
                        }
                      >
                        <button onClick={() => handleSaveEdit(col)} class="text-xs text-green-500 hover:underline">Save</button>
                        <button onClick={() => setEditingId(null)} class="text-xs text-theme-text-secondary hover:underline">Cancel</button>
                      </Show>
                      <button onClick={() => handleDelete(col.id)} class="text-xs text-red-500 hover:underline">Delete</button>
                    </div>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </Show>
    </div>
  );
}
