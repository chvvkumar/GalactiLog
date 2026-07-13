import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, findByTestId } from "@solidjs/testing-library";
import { Suspense } from "solid-js";
import { Router, Route } from "@solidjs/router";
import { QueryClient, QueryClientProvider } from "@tanstack/solid-query";

// Reproduces the Dashboard sidebar-search focus-loss bug.
//
// Root cause: @tanstack/solid-query's useQuery is backed by createResource.
// Its `data` getter reads the underlying (suspending) resource whenever the
// query has no cached data for the CURRENT key. Every keystroke rewrites the
// `search` URL param -> the targets query key changes -> no cached data for
// the new key -> reading `targetData()` re-enters the pending resource ->
// the app's single top-level <Suspense> re-suspends and swaps the whole
// subtree (including the search <input>) for the fallback, detaching the
// focused input. The fix is `placeholderData: keepPreviousData`, which keeps
// `state.data` defined across key changes so the getter never reads the
// pending resource.

const targetsResponse = {
  targets: [],
  total_count: 5,
  page: 1,
  page_size: 25,
  aggregates: {
    total_integration_seconds: 0,
    target_count: 0,
    total_frames: 0,
  },
};

vi.mock("../api/generated/client", () => ({
  apiClient: {
    GET: vi.fn((path: string) => {
      if (path === "/api/targets/search") {
        return Promise.resolve({ data: [], response: { ok: true } });
      }
      return Promise.resolve({ data: targetsResponse, response: { ok: true } });
    }),
  },
}));

vi.mock("./SettingsProvider", () => ({
  useSettingsContext: () => ({
    settings: () => ({ general: { default_page_size: 25 } }),
    customColumns: () => [],
    saveGeneral: () => {},
  }),
}));

import SearchBar from "./SearchBar";
import DashboardFilterProvider, { useDashboardFilters } from "./DashboardFilterProvider";

// A consumer that READS targetData() (like Sidebar and TargetFeed do) so the
// resource is subscribed under the Suspense boundary.
function TargetCountConsumer() {
  const { targetData } = useDashboardFilters();
  return <div data-testid="count">{targetData()?.total_count ?? "none"}</div>;
}

function DashboardHarness() {
  return (
    <Suspense fallback={<div data-testid="fallback">Loading...</div>}>
      <DashboardFilterProvider>
        <SearchBar />
        <TargetCountConsumer />
      </DashboardFilterProvider>
    </Suspense>
  );
}

function App() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <Router>
        <Route path="/" component={DashboardHarness} />
      </Router>
    </QueryClientProvider>
  );
}

describe("Dashboard sidebar search focus retention", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("does not re-suspend / detach the search input when typing", async () => {
    const { getByPlaceholderText, queryByTestId, baseElement } = render(() => <App />);

    // Wait for the initial targets fetch to resolve so we have "previous data".
    await findByTestId(baseElement as HTMLElement, "count");
    expect(queryByTestId("fallback")).toBeNull();

    const input = getByPlaceholderText("M31, NGC 7000...") as HTMLInputElement;
    input.focus();
    expect(document.activeElement).toBe(input);

    // Type a single character. This rewrites the `search` param and changes the
    // targets query key. Without keepPreviousData, reading targetData() re-enters
    // the pending resource and re-suspends the top-level Suspense; under the
    // router's navigation transition the resolved subtree is swapped out and back
    // in, which blurs the focused input (document.activeElement -> <body>).
    fireEvent.input(input, { target: { value: "M" } });

    // The focus loss happens across microtasks (resource pends, then resolves),
    // so observe over several async ticks.
    for (let i = 0; i < 8; i++) {
      await Promise.resolve();
      await new Promise((r) => setTimeout(r, 0));
    }

    // The Suspense fallback must never appear, and the input must keep focus.
    expect(queryByTestId("fallback")).toBeNull();
    const currentInput = getByPlaceholderText("M31, NGC 7000...") as HTMLInputElement;
    expect(currentInput).toBe(input);
    expect(currentInput.isConnected).toBe(true);
    expect(document.activeElement).toBe(input);
  });
});
