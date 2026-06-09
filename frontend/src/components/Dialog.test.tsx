import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import Dialog from "./Dialog";

// Portal renders into document.body, so queries must search the full document.
const bodyGetByRole = (role: string): HTMLElement => {
  const el = document.body.querySelector(`[role="${role}"]`) as HTMLElement | null;
  if (!el) throw new Error(`Unable to find element with role: ${role}`);
  return el;
};

const bodyQueryByRole = (role: string): HTMLElement | null =>
  document.body.querySelector(`[role="${role}"]`);

const bodyGetByText = (text: string): HTMLElement => {
  const el = Array.from(document.body.querySelectorAll("*")).find(
    (n) => n.textContent?.trim() === text,
  ) as HTMLElement | undefined;
  if (!el) throw new Error(`Unable to find element with text: ${text}`);
  return el;
};

describe("Dialog", () => {
  it("renders role=dialog and aria-modal when open", () => {
    render(() => (
      <Dialog open onClose={() => {}}>
        <div>content</div>
      </Dialog>
    ));
    const dialog = bodyGetByRole("dialog");
    expect(dialog).toBeDefined();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });

  it("renders children inside the dialog", () => {
    render(() => (
      <Dialog open onClose={() => {}}>
        <div>hello world</div>
      </Dialog>
    ));
    expect(bodyGetByText("hello world")).toBeDefined();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(() => (
      <Dialog open onClose={onClose}>
        <div>content</div>
      </Dialog>
    ));
    const dialog = bodyGetByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not render when open is false", () => {
    render(() => (
      <Dialog open={false} onClose={() => {}}>
        <div>hidden</div>
      </Dialog>
    ));
    expect(bodyQueryByRole("dialog")).toBeNull();
  });

  it("forwards aria-labelledby to the dialog element", () => {
    render(() => (
      <Dialog open aria-labelledby="my-title" onClose={() => {}}>
        <div id="my-title">My Modal Title</div>
      </Dialog>
    ));
    const dialog = bodyGetByRole("dialog");
    expect(dialog.getAttribute("aria-labelledby")).toBe("my-title");
  });

  it("forwards aria-label to the dialog element", () => {
    render(() => (
      <Dialog open aria-label="Test dialog" onClose={() => {}}>
        <div>content</div>
      </Dialog>
    ));
    const dialog = bodyGetByRole("dialog");
    expect(dialog.getAttribute("aria-label")).toBe("Test dialog");
  });

  it("moves focus into the dialog when it opens", async () => {
    render(() => (
      <Dialog open onClose={() => {}}>
        <button>First focusable</button>
      </Dialog>
    ));
    // queueMicrotask schedules focus — flush it.
    await Promise.resolve();
    const dialog = bodyGetByRole("dialog");
    const btn = dialog.querySelector("button");
    expect(document.activeElement).toBe(btn);
  });
});
