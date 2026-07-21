import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import { createSignal } from "solid-js";

vi.mock("./Toast", () => ({ showToast: vi.fn() }));

import InlineEditCell from "./InlineEditCell";

function flush() {
  return new Promise((r) => setTimeout(r, 0));
}

describe("InlineEditCell boolean", () => {
  it("keeps the new checked state after save resolves even if props.value is stale", async () => {
    // Parent does not refetch after save, so props.value stays at the old value.
    const onSave = vi.fn().mockResolvedValue(undefined);
    const { container } = render(() => (
      <InlineEditCell columnType="boolean" value="false" onSave={onSave} />
    ));
    const box = container.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(box.checked).toBe(false);

    fireEvent.click(box);
    await flush();

    expect(onSave).toHaveBeenCalledWith("true");
    // Bug: setSaving(false) re-ran the sync effect with the stale prop and
    // reverted the checkbox to unchecked.
    expect(box.checked).toBe(true);
  });

  it("still syncs when props.value actually changes from outside", async () => {
    const [value, setValue] = createSignal<string | undefined>("false");
    const { container } = render(() => (
      <InlineEditCell columnType="boolean" value={value()} onSave={vi.fn()} />
    ));
    const box = container.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(box.checked).toBe(false);

    setValue("true");
    await flush();
    expect(box.checked).toBe(true);
  });

  it("reverts to the previous value when save fails", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("boom"));
    const { container } = render(() => (
      <InlineEditCell columnType="boolean" value="false" onSave={onSave} />
    ));
    const box = container.querySelector("input[type=checkbox]") as HTMLInputElement;

    fireEvent.click(box);
    await flush();

    expect(box.checked).toBe(false);
  });
});
