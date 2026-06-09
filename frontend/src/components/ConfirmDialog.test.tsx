import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";
import ConfirmDialog from "./ConfirmDialog";

// Portal renders into document.body, so queries must search the full document.
const bodyGetByText = (text: string) => {
  const el = Array.from(document.body.querySelectorAll("*")).find(
    (n) => n.textContent?.trim() === text,
  ) as HTMLElement | undefined;
  if (!el) throw new Error(`Unable to find element with text: ${text}`);
  return el;
};

const bodyQueryByText = (text: string): HTMLElement | null => {
  return (
    (Array.from(document.body.querySelectorAll("*")).find(
      (n) => n.textContent?.trim() === text,
    ) as HTMLElement | undefined) ?? null
  );
};

const bodyGetByRole = (role: string) => {
  const el = document.body.querySelector(`[role="${role}"]`) as HTMLElement | null;
  if (!el) throw new Error(`Unable to find element with role: ${role}`);
  return el;
};

const bodyQueryByRole = (role: string): HTMLElement | null =>
  document.body.querySelector(`[role="${role}"]`);

describe("ConfirmDialog", () => {
  it("renders title and message when open", () => {
    render(() => (
      <ConfirmDialog
        open={true}
        title="Delete panel"
        message="Are you sure you want to delete this panel?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    ));

    expect(bodyGetByText("Delete panel")).toBeDefined();
    expect(bodyGetByText("Are you sure you want to delete this panel?")).toBeDefined();
  });

  it("does not render when open is false", () => {
    render(() => (
      <ConfirmDialog
        open={false}
        title="Delete panel"
        message="Are you sure?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    ));

    expect(bodyQueryByRole("dialog")).toBeNull();
  });

  it("calls onConfirm when Confirm button is clicked", () => {
    const onConfirm = vi.fn();
    render(() => (
      <ConfirmDialog
        open={true}
        title="Delete"
        message="Confirm delete?"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />
    ));

    fireEvent.click(bodyGetByText("Confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when Cancel button is clicked", () => {
    const onCancel = vi.fn();
    render(() => (
      <ConfirmDialog
        open={true}
        title="Delete"
        message="Confirm delete?"
        onConfirm={() => {}}
        onCancel={onCancel}
      />
    ));

    fireEvent.click(bodyGetByText("Cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when Escape key is pressed", () => {
    const onCancel = vi.fn();
    render(() => (
      <ConfirmDialog
        open={true}
        title="Delete"
        message="Confirm delete?"
        onConfirm={() => {}}
        onCancel={onCancel}
      />
    ));

    const dialog = bodyGetByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not call onCancel on Escape when closed", () => {
    const onCancel = vi.fn();
    render(() => (
      <ConfirmDialog
        open={false}
        title="Delete"
        message="Confirm delete?"
        onConfirm={() => {}}
        onCancel={onCancel}
      />
    ));

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("uses custom confirmLabel and cancelLabel when provided", () => {
    render(() => (
      <ConfirmDialog
        open={true}
        title="Remove images"
        message="This is destructive."
        confirmLabel="Remove"
        cancelLabel="Keep"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    ));

    expect(bodyGetByText("Remove")).toBeDefined();
    expect(bodyGetByText("Keep")).toBeDefined();
  });

  it("responds to open changing from false to true", () => {
    const [open, setOpen] = createSignal(false);
    render(() => (
      <ConfirmDialog
        open={open()}
        title="Delete"
        message="Are you sure?"
        onConfirm={() => {}}
        onCancel={() => {}}
      />
    ));

    expect(bodyQueryByRole("dialog")).toBeNull();
    setOpen(true);
    expect(bodyGetByRole("dialog")).toBeDefined();
  });
});
