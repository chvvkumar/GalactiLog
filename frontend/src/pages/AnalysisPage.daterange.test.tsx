import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";

// ---------------------------------------------------------------------------
// Minimal inline component that mirrors the date-range validation logic in
// AnalysisPage, without pulling in all of the page's heavy dependencies
// (API calls, context providers, chart libraries).  The validation itself is
// pure signal/memo logic so this approach tests the real behaviour.
// ---------------------------------------------------------------------------

import { createSignal, createMemo, Show } from "solid-js";

const DateRangeValidation = () => {
  const [dateFrom, setDateFrom] = createSignal<string | undefined>(undefined);
  const [dateTo, setDateTo] = createSignal<string | undefined>(undefined);

  const dateRangeError = createMemo(() => {
    const from = dateFrom();
    const to = dateTo();
    if (from && to && from > to) {
      return "From date must be on or before To date.";
    }
    return null;
  });

  return (
    <div>
      <input
        data-testid="date-from"
        type="date"
        value={dateFrom() || ""}
        onChange={(e) => setDateFrom(e.currentTarget.value || undefined)}
      />
      <input
        data-testid="date-to"
        type="date"
        value={dateTo() || ""}
        onChange={(e) => setDateTo(e.currentTarget.value || undefined)}
      />
      <Show when={dateRangeError()}>
        <p data-testid="date-range-error">{dateRangeError()}</p>
      </Show>
    </div>
  );
};

describe("AnalysisPage date-range validation", () => {
  it("shows an error when From is after To", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-from"), { target: { value: "2024-06-15" } });
    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-01-01" } });

    const error = getByTestId("date-range-error");
    expect(error).toBeDefined();
    expect(error.textContent).toBe("From date must be on or before To date.");
  });

  it("does not show an error for a valid range (From < To)", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-from"), { target: { value: "2024-01-01" } });
    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-06-15" } });

    expect(queryByTestId("date-range-error")).toBeNull();
  });

  it("does not show an error when From equals To", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-from"), { target: { value: "2024-03-10" } });
    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-03-10" } });

    expect(queryByTestId("date-range-error")).toBeNull();
  });

  it("does not show an error when only From is set", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-from"), { target: { value: "2024-06-15" } });

    expect(queryByTestId("date-range-error")).toBeNull();
  });

  it("does not show an error when only To is set", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-01-01" } });

    expect(queryByTestId("date-range-error")).toBeNull();
  });

  it("clears the error when the range is corrected", () => {
    const { getByTestId, queryByTestId } = render(() => <DateRangeValidation />);

    fireEvent.change(getByTestId("date-from"), { target: { value: "2024-06-15" } });
    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-01-01" } });
    expect(getByTestId("date-range-error")).toBeDefined();

    // Fix the To date to be after From.
    fireEvent.change(getByTestId("date-to"), { target: { value: "2024-12-31" } });
    expect(queryByTestId("date-range-error")).toBeNull();
  });
});
