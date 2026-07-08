import { For, Show, type JSX } from "solid-js";
import ColumnPicker from "./ColumnPicker";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  /** Fixed column width (any CSS length/%), applied via <colgroup>. Requires the table
   *  to use `table-fixed` (pass it through `class`) for widths to be honored. */
  width?: string;
  /** Header becomes clickable and shows a sort arrow; click fires onSort(key). */
  sortable?: boolean;
  /** Column is always rendered, ignoring the visibility record. */
  alwaysVisible?: boolean;
  render: (row: T) => JSX.Element | string | number | null;
}

// Reuse ColumnPicker's own prop shape rather than inventing a parallel one -
// DataTable forwards these untouched, it never interprets ColumnVisibility itself.
type ColumnPickerProps = Parameters<typeof ColumnPicker>[0];

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Stable per-row identifier, exposed as data-row-key for tests/DOM hooks. */
  rowKey: (row: T) => string;
  sortKey?: () => string | null;
  sortDir?: () => "asc" | "desc";
  onSort?: (key: string) => void;
  /** Resolved key -> visible map. Caller pre-resolves via isColumnVisible; DataTable
   *  stays decoupled from the app's ColumnVisibility schema. Omit to show all columns. */
  visibility?: () => Record<string, boolean>;
  /** Pass-through props for a trailing <ColumnPicker> header cell. Omit to skip the picker. */
  columnPicker?: ColumnPickerProps;
  loading?: boolean;
  error?: string | null;
  emptyMessage?: string;
  /** Extra classes for the <table> element (width/text-size variants). */
  class?: string;
}

function DataTable<T>(props: DataTableProps<T>) {
  const isVisible = (col: DataTableColumn<T>) => {
    if (col.alwaysVisible) return true;
    const vis = props.visibility?.();
    if (!vis || !(col.key in vis)) return true;
    return vis[col.key];
  };

  const visibleColumns = () => props.columns.filter(isVisible);

  const colCount = () => visibleColumns().length + (props.columnPicker ? 1 : 0);

  const arrow = (key: string) => {
    if (props.sortKey?.() !== key) return " ↕";
    return props.sortDir?.() === "asc" ? " ↑" : " ↓";
  };

  // Ports TargetTable.tsx's header class construction so sortable vs plain
  // headers keep exact visual parity once T5 swaps consumers onto DataTable.
  const headerClass = (col: DataTableColumn<T>) => {
    const align = col.align ?? "left";
    const base = `text-${align} py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap`;
    if (!col.sortable) return base;
    const active = props.sortKey?.() === col.key;
    return `${base} cursor-pointer select-none hover:text-theme-text-primary transition-colors${active ? " border-b-2 border-theme-accent" : ""}`;
  };

  return (
    <table class={`w-full text-sm border-collapse${props.class ? ` ${props.class}` : ""}`}>
      <Show when={visibleColumns().some((c) => c.width)}>
        <colgroup>
          <For each={visibleColumns()}>
            {(col) => <col style={col.width ? { width: col.width } : undefined} />}
          </For>
          <Show when={props.columnPicker}>
            <col />
          </Show>
        </colgroup>
      </Show>
      <thead>
        <tr class="border-b border-theme-border-em text-theme-text-tertiary text-label uppercase tracking-wider">
          <For each={visibleColumns()}>
            {(col) => (
              <th
                class={headerClass(col)}
                onClick={col.sortable ? () => props.onSort?.(col.key) : undefined}
              >
                {col.label}
                {col.sortable ? arrow(col.key) : ""}
              </th>
            )}
          </For>
          <Show when={props.columnPicker}>
            <th class="text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap">
              <ColumnPicker {...(props.columnPicker as ColumnPickerProps)} />
            </th>
          </Show>
        </tr>
      </thead>
      <tbody>
        <Show
          when={!props.loading}
          fallback={
            <tr>
              <td colSpan={colCount()} class="py-6 text-center text-theme-text-secondary text-sm">
                Loading...
              </td>
            </tr>
          }
        >
          <Show
            when={!props.error}
            fallback={
              <tr>
                <td colSpan={colCount()} class="py-6 text-center text-theme-error text-sm">
                  {props.error}
                </td>
              </tr>
            }
          >
            <Show
              when={props.rows.length > 0}
              fallback={
                <tr>
                  <td colSpan={colCount()} class="py-6 text-center text-theme-text-secondary text-sm">
                    {props.emptyMessage ?? "No data found"}
                  </td>
                </tr>
              }
            >
              <For each={props.rows}>
                {(row) => (
                  <tr
                    data-row-key={props.rowKey(row)}
                    class="border-b border-theme-border/50 hover:bg-theme-hover transition-colors duration-150"
                  >
                    <For each={visibleColumns()}>
                      {(col) => (
                        <td class={`py-2 px-3 text-${col.align ?? "left"} text-theme-text-primary tabular-nums${col.align === "right" ? " whitespace-nowrap" : ""}`}>
                          {col.render(row)}
                        </td>
                      )}
                    </For>
                  </tr>
                )}
              </For>
            </Show>
          </Show>
        </Show>
      </tbody>
    </table>
  );
}

export default DataTable;
