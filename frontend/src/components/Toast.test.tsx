import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@solidjs/testing-library";
import { Toast, showToast, dismissToast } from "./Toast";

beforeEach(() => {
  // Clear all toasts between tests so module-level signal state doesn't leak.
  dismissToast();
});

describe("Toast aria attributes", () => {
  it("renders a polite status region for non-error toasts", () => {
    const { container } = render(() => <Toast />);
    const statusEl = container.querySelector('[role="status"]');
    expect(statusEl).not.toBeNull();
    expect(statusEl!.getAttribute("aria-live")).toBe("polite");
    expect(statusEl!.getAttribute("aria-atomic")).toBe("true");
  });

  it("renders an assertive alert region for error toasts", () => {
    const { container } = render(() => <Toast />);
    const alertEl = container.querySelector('[role="alert"]');
    expect(alertEl).not.toBeNull();
    expect(alertEl!.getAttribute("aria-live")).toBe("assertive");
    expect(alertEl!.getAttribute("aria-atomic")).toBe("true");
  });

  it("places success toast in the polite region, not the alert region", () => {
    showToast("Scan complete", "success", 0);
    const { container } = render(() => <Toast />);

    const statusEl = container.querySelector('[role="status"]')!;
    const alertEl = container.querySelector('[role="alert"]')!;

    expect(statusEl.textContent).toContain("Scan complete");
    expect(alertEl.textContent).not.toContain("Scan complete");
  });

  it("places info toast in the polite region, not the alert region", () => {
    showToast("Import started", "info", 0);
    const { container } = render(() => <Toast />);

    const statusEl = container.querySelector('[role="status"]')!;
    const alertEl = container.querySelector('[role="alert"]')!;

    expect(statusEl.textContent).toContain("Import started");
    expect(alertEl.textContent).not.toContain("Import started");
  });

  it("places error toast in the alert region, not the polite region", () => {
    showToast("Something failed", "error", 0);
    const { container } = render(() => <Toast />);

    const statusEl = container.querySelector('[role="status"]')!;
    const alertEl = container.querySelector('[role="alert"]')!;

    expect(alertEl.textContent).toContain("Something failed");
    expect(statusEl.textContent).not.toContain("Something failed");
  });

  it("dismiss button has aria-label on toasts in both regions", () => {
    showToast("Info message", "info", 0);
    showToast("Error message", "error", 0);
    const { getAllByRole } = render(() => <Toast />);

    const dismissButtons = getAllByRole("button", { name: "Dismiss" });
    expect(dismissButtons.length).toBe(2);
  });
});
