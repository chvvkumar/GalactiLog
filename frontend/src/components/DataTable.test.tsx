import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";
import DataTable, { type DataTableColumn } from "./DataTable";
import type { ColumnVisibility } from "../types";

interface Row {
  id: string;
  name: string;
  count: number;
}

const rows: Row[] = [
  { id: "a", name: "Alpha", count: 3 },
  { id: "b", name: "Beta", count: 1 },
];

const columns: DataTableColumn<Row>[] = [
  { key: "name", label: "Name", sortable: true, alwaysVisible: true, render: (r) => r.name },
  { key: "count", label: "Count", align: "right", render: (r) => r.count },
];

describe("DataTable", () => {
  it("renders a plain table with rows for the given columns", () => {
    const { getByRole, getByText } = render(() => (
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />
    ));
    expect(getByRole("table")).toBeDefined();
    expect(getByText("Alpha")).toBeDefined();
    expect(getByText("Beta")).toBeDefined();
    expect(getByText("3")).toBeDefined();
  });

  it("renders custom column content via each column's render function", () => {
    const cols: DataTableColumn<Row>[] = [
      { key: "name", label: "Name", render: (r) => `${r.name}!` },
    ];
    const { getByText } = render(() => (
      <DataTable columns={cols} rows={rows} rowKey={(r) => r.id} />
    ));
    expect(getByText("Alpha!")).toBeDefined();
  });

  it("fires onSort with the clicked column's key on a sortable header", () => {
    const onSort = vi.fn();
    const { getByText } = render(() => (
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        sortKey={() => null}
        sortDir={() => "asc"}
        onSort={onSort}
      />
    ));
    fireEvent.click(getByText(/Name/));
    expect(onSort).toHaveBeenCalledWith("name");
  });

  it("does not attach a click handler on non-sortable headers", () => {
    const onSort = vi.fn();
    const { getByText } = render(() => (
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} onSort={onSort} />
    ));
    fireEvent.click(getByText("Count"));
    expect(onSort).not.toHaveBeenCalled();
  });

  it("hides columns marked not-visible via the visibility record", () => {
    const { queryByText } = render(() => (
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        visibility={() => ({ count: false })}
      />
    ));
    expect(queryByText("Count")).toBeNull();
    expect(queryByText("3")).toBeNull();
  });

  it("keeps alwaysVisible columns rendered regardless of the visibility record", () => {
    const { getByText } = render(() => (
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        visibility={() => ({ name: false, count: false })}
      />
    ));
    // "name" is alwaysVisible: true, so it must still render despite visibility saying false.
    expect(getByText("Alpha")).toBeDefined();
  });

  it("shows a loading indicator instead of stale or empty rows while loading", () => {
    const { getByText, queryByText } = render(() => (
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} loading />
    ));
    expect(getByText("Loading...")).toBeDefined();
    expect(queryByText("Alpha")).toBeNull();
  });

  it("shows the error message instead of rows when error is set", () => {
    const { getByText, queryByText } = render(() => (
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} error="Failed to load" />
    ));
    expect(getByText("Failed to load")).toBeDefined();
    expect(queryByText("Alpha")).toBeNull();
  });

  it("shows emptyMessage when rows is empty", () => {
    const { getByText } = render(() => (
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyMessage="Nothing here" />
    ));
    expect(getByText("Nothing here")).toBeDefined();
  });

  it("falls back to a default empty message when none is given", () => {
    const { getByText } = render(() => (
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} />
    ));
    expect(getByText("No data found")).toBeDefined();
  });

  it("composes ColumnPicker in a trailing header cell and toggling a column calls onToggle", () => {
    const [visibility] = createSignal<ColumnVisibility>({
      dashboard: { builtin: { count: false }, custom: {} },
      session_table: { builtin: {}, custom: {} },
      session_detail: { builtin: {}, custom: {} },
      mosaic_table: { builtin: {}, custom: {} },
    });
    const onToggle = vi.fn();

    const { getByTitle, getByLabelText } = render(() => (
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        columnPicker={{
          table: "dashboard",
          builtinColumns: [
            { key: "name", label: "Name", alwaysVisible: true },
            { key: "count", label: "Count" },
          ],
          customColumns: [],
          visibility: visibility(),
          onToggle,
        }}
      />
    ));

    fireEvent.click(getByTitle("Configure columns"));
    fireEvent.click(getByLabelText("Count"));
    expect(onToggle).toHaveBeenCalledWith("builtin", "count", true);
  });
});
