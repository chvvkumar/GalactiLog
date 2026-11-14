import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@solidjs/testing-library";
import { ApiError } from "../../api/unwrap";

vi.mock("../../api/generated/client", () => ({
  apiClient: {
    POST: vi.fn(() => Promise.reject(new ApiError(502, "SIMBAD lookup for 'IC 1396' failed: SIMBAD is unavailable"))),
  },
}));
vi.mock("../AuthProvider", () => ({ useAuth: () => ({ isAdmin: () => false }) }));
vi.mock("../Toast", () => ({ showToast: vi.fn() }));

import UnresolvedSection from "./UnresolvedSection";

describe("UnresolvedSection", () => {
  it("shows the ApiError message when the preview lookup fails", async () => {
    const candidates = () => [
      { id: "1", source_name: "IC 1396", source_image_count: 3 },
    ] as never;
    render(() => <UnresolvedSection candidates={candidates} onAction={() => {}} />);
    expect(await screen.findByText("Lookup failed")).toBeTruthy();
    expect(await screen.findByText(/SIMBAD is unavailable/)).toBeTruthy();
  });
});
