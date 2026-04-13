import { Component, For, Show, createSignal } from "solid-js";
import { useDashboardFilters } from "./DashboardFilterProvider";
import { useFilterOptions } from "../store/filterOptions";

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
  const { filters, addFitsQuery, removeFitsQuery } = useDashboardFilters();
  const [newKey, setNewKey] = createSignal("");
  const [newOp, setNewOp] = createSignal("eq");
  const [newVal, setNewVal] = createSignal("");
  const { fitsKeys } = useFilterOptions();

  const addRow = () => {
    const key = newKey().trim();
    const val = newVal().trim();
    if (!key || !val) return;
    addFitsQuery(key, newOp(), val);
    setNewKey("");
    setNewVal("");
  };

  const removeRow = (index: number) => {
    removeFitsQuery(index);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addRow();
    }
  };

  return (
    <div class="space-y-2">
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
            class="flex-1 px-1.5 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary font-mono focus:border-theme-accent outline-none"
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
            class="w-16 px-1 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary focus:border-theme-accent outline-none"
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
            class="flex-1 px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-xs text-theme-text-primary placeholder:text-theme-text-tertiary focus:border-theme-accent outline-none"
          />
          <button onClick={addRow} class="px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded-[var(--radius-sm)] text-xs font-medium hover:bg-theme-accent/25 transition-colors">+</button>
        </div>
      </div>
    </div>
  );
};

export default FitsQueryBuilder;
