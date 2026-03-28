import { Component, For, Show, createSignal, createResource } from "solid-js";
import { useCatalog } from "../store/catalog";
import { api } from "../api/client";

const OPERATORS = [
  { value: "eq", label: "=" },
  { value: "neq", label: "!=" },
  { value: "gt", label: ">" },
  { value: "lt", label: "<" },
  { value: "gte", label: ">=" },
  { value: "lte", label: "<=" },
  { value: "contains", label: "contains" },
];

const FitsQueryBuilder: Component = () => {
  const { filters, setFilters } = useCatalog();
  const [newKey, setNewKey] = createSignal("");
  const [newOp, setNewOp] = createSignal("eq");
  const [newVal, setNewVal] = createSignal("");
  const [fitsKeys] = createResource(() => api.getFitsKeys());

  const addRow = () => {
    const key = newKey().trim();
    const val = newVal().trim();
    if (!key || !val) return;
    setFilters((prev) => ({
      ...prev,
      fitsQueries: [...prev.fitsQueries, { key, operator: newOp(), value: val }],
    }));
    setNewKey("");
    setNewVal("");
  };

  const removeRow = (index: number) => {
    setFilters((prev) => ({
      ...prev,
      fitsQueries: prev.fitsQueries.filter((_, i) => i !== index),
    }));
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addRow();
    }
  };

  return (
    <div class="space-y-2">
      <label class="text-xs text-theme-text-secondary">FITS Header Query</label>

      {/* Existing rows */}
      <For each={filters().fitsQueries}>
        {(row, i) => (
          <div class="flex items-center gap-1 text-xs">
            <span class="text-theme-text-primary font-mono flex-1 truncate">{row.key} {row.operator} {row.value}</span>
            <button onClick={() => removeRow(i())} class="text-theme-error hover:text-theme-error px-1">&times;</button>
          </div>
        )}
      </For>

      {/* New row inputs */}
      <div class="space-y-1.5">
        <div class="flex gap-1.5">
          <select
            value={newKey()}
            onChange={(e) => setNewKey(e.currentTarget.value)}
            class="flex-1 px-1.5 py-1.5 bg-theme-base border border-theme-border rounded text-xs text-theme-text-primary font-mono focus:outline-none focus:ring-1 focus:border-theme-accent"
          >
            <option value="" disabled>Header Key</option>
            <Show when={fitsKeys()}>
              <For each={fitsKeys()}>
                {(key) => <option value={key}>{key}</option>}
              </For>
            </Show>
          </select>
          <select
            value={newOp()}
            onChange={(e) => setNewOp(e.currentTarget.value)}
            class="w-16 px-1 py-1.5 bg-theme-base border border-theme-border rounded text-xs text-theme-text-primary focus:outline-none"
          >
            <For each={OPERATORS}>{(op) => <option value={op.value}>{op.label}</option>}</For>
          </select>
        </div>
        <div class="flex gap-1.5">
          <input
            type="text"
            value={newVal()}
            onInput={(e) => setNewVal(e.currentTarget.value)}
            onKeyDown={onKeyDown}
            placeholder="Value"
            class="flex-1 px-2 py-1.5 bg-theme-base border border-theme-border rounded text-xs text-theme-text-primary focus:outline-none focus:ring-1 focus:border-theme-accent"
          />
          <button onClick={addRow} class="px-3 py-1.5 bg-theme-accent text-theme-text-primary rounded text-xs hover:bg-theme-accent/80">+</button>
        </div>
      </div>
    </div>
  );
};

export default FitsQueryBuilder;
