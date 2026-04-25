import { createSignal, For, Show } from "solid-js";
import { api } from "../api/client";
import type { CustomColumn } from "../types";
import { useSettingsContext } from "./SettingsProvider";
import HelpPopover from "./HelpPopover";

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
  const ctx = useSettingsContext();
  const columns = ctx.customColumns;
  const refetch = ctx.refetchCustomColumns;
  const [newName, setNewName] = createSignal("");
  const [newType, setNewType] = createSignal<"boolean" | "text" | "dropdown">("boolean");
  const [newAppliesTo, setNewAppliesTo] = createSignal<"target" | "session" | "rig" | "mosaic">("target");
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
    <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Custom Columns</h2>
          <HelpPopover title="Custom Columns">
            <p>User-defined columns that attach to targets, sessions, or rigs. Use them for metadata that is not in FITS headers, such as processing state, notes, or rig assignments.</p>
            <p>Three column types are available: boolean (checkbox), text (free-form string), and dropdown (fixed set of values). Column definitions and values are shared across all users of this GalactiLog instance.</p>
            <p>Example: a boolean "Processed" column on targets, or a dropdown "Priority" on sessions with values Low, Normal, High.</p>
          </HelpPopover>
        </div>
      </div>

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Add Column</h2>
          <HelpPopover title="Add Column">
            <p>Creates a new custom column. Name is the label shown in tables. Type sets how values are entered (boolean, text, or dropdown). Applies To selects where the column appears: target pages, session rows, or rig entries.</p>
            <p>For dropdown columns, list the allowed values in the Dropdown Options area before adding.</p>
            <p>Example: Name "Status", Type dropdown, Applies To target, Options "Raw, Stacked, Processed".</p>
          </HelpPopover>
        </div>
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
              <option value="mosaic">Mosaic</option>
            </select>
          </div>
          <button
            onClick={handleCreate}
            class="px-3 py-1 rounded bg-theme-accent/15 text-theme-accent border border-theme-accent/30 text-sm font-medium hover:bg-theme-accent/25 transition-colors"
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

      <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-theme-text-primary">Existing Columns</h2>
          <HelpPopover title="Existing Columns">
            <p>Lists every defined custom column with its type, scope, and options. Use the order arrows to reorder columns in target and session tables; delete removes the column and all stored values for it.</p>
            <p>Example: reorder so "Processed" appears before "Priority" in the target dashboard.</p>
          </HelpPopover>
        </div>
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
                        <button onClick={() => handleSaveEdit(col)} class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors">Save</button>
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
    </div>
  );
}
