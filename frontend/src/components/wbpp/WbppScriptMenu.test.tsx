import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@solidjs/testing-library";
import WbppScriptMenu, { type ScriptOs } from "./WbppScriptMenu";

function setup(over: Partial<Parameters<typeof WbppScriptMenu>[0]> = {}) {
  const onGenerate = vi.fn();
  const defaultOs: ScriptOs = over.defaultOs ?? "windows";
  const result = render(() => (
    <WbppScriptMenu
      defaultOs={defaultOs}
      defaultReason={over.defaultReason ?? "detected"}
      generating={over.generating ?? false}
      hasScript={over.hasScript ?? false}
      disabled={over.disabled}
      onGenerate={over.onGenerate ?? onGenerate}
    />
  ));
  const trigger = result.getByRole("button") as HTMLButtonElement;
  return { ...result, trigger, onGenerate };
}

/** The menu item row whose text contains the given label. */
function itemByLabel(items: HTMLElement[], label: string): HTMLElement {
  const found = items.find((i) => (i.textContent ?? "").includes(label));
  if (!found) throw new Error(`no menu item matching ${label}`);
  return found;
}

describe("WbppScriptMenu", () => {
  it("renders a trigger reading 'Generate script'", () => {
    const { trigger } = setup();
    expect((trigger.textContent ?? "").includes("Generate script")).toBe(true);
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  });

  // FIX 1: once a script exists the trigger has to admit it is replacing it.
  it("reads 'Regenerate script' once a script exists", () => {
    const { trigger } = setup({ hasScript: true });
    expect((trigger.textContent ?? "").includes("Regenerate script")).toBe(true);
  });

  it("prefers the generating label over the regenerate label", () => {
    const { trigger } = setup({ hasScript: true, generating: true });
    expect((trigger.textContent ?? "").includes("Generating...")).toBe(true);
    expect((trigger.textContent ?? "").includes("Regenerate script")).toBe(false);
  });

  it("shows nothing until opened, then both items", () => {
    const { trigger, queryAllByRole, getAllByRole } = setup();
    expect(queryAllByRole("menuitem").length).toBe(0);
    fireEvent.click(trigger);
    const items = getAllByRole("menuitem");
    expect(items.length).toBe(2);
    expect((items[0].textContent ?? "").includes("PowerShell (.ps1)")).toBe(true);
    expect((items[1].textContent ?? "").includes("Shell (.sh)")).toBe(true);
  });

  it("marks only the default item when defaultOs is windows", () => {
    const { trigger, getAllByRole } = setup({ defaultOs: "windows" });
    fireEvent.click(trigger);
    const items = getAllByRole("menuitem");
    expect((itemByLabel(items, "PowerShell").textContent ?? "").includes("Detected")).toBe(true);
    expect((itemByLabel(items, "Shell (.sh)").textContent ?? "").includes("Detected")).toBe(false);
  });

  it("marks Shell and not PowerShell when defaultOs is posix", () => {
    const { trigger, getAllByRole } = setup({ defaultOs: "posix" });
    fireEvent.click(trigger);
    const items = getAllByRole("menuitem");
    expect((itemByLabel(items, "Shell (.sh)").textContent ?? "").includes("Detected")).toBe(true);
    expect((itemByLabel(items, "PowerShell").textContent ?? "").includes("Detected")).toBe(false);
  });

  it("reads 'Detected' when the default came from detection", () => {
    const { trigger, getAllByRole } = setup({ defaultOs: "windows", defaultReason: "detected" });
    fireEvent.click(trigger);
    const marked = itemByLabel(getAllByRole("menuitem"), "PowerShell");
    expect((marked.textContent ?? "").includes("Detected")).toBe(true);
    expect((marked.textContent ?? "").includes("Your default")).toBe(false);
  });

  it("reads 'Your default' when the default came from a pinned preference", () => {
    const { trigger, getAllByRole } = setup({ defaultOs: "windows", defaultReason: "preference" });
    fireEvent.click(trigger);
    const marked = itemByLabel(getAllByRole("menuitem"), "PowerShell");
    expect((marked.textContent ?? "").includes("Your default")).toBe(true);
    expect((marked.textContent ?? "").includes("Detected")).toBe(false);
  });

  it("marks only one item regardless of reason", () => {
    const { trigger, getAllByRole } = setup({ defaultOs: "posix", defaultReason: "preference" });
    fireEvent.click(trigger);
    const items = getAllByRole("menuitem");
    expect((itemByLabel(items, "Shell (.sh)").textContent ?? "").includes("Your default")).toBe(
      true,
    );
    expect((itemByLabel(items, "PowerShell").textContent ?? "").includes("Your default")).toBe(
      false,
    );
  });

  it("lets defaultOs alone drive the highlight, not defaultReason", () => {
    // Same defaultOs, both reasons: the highlighted item must not move.
    for (const reason of ["detected", "preference"] as const) {
      const { trigger, getAllByRole, unmount } = setup({
        defaultOs: "posix",
        defaultReason: reason,
      });
      fireEvent.click(trigger);
      const items = getAllByRole("menuitem");
      expect(itemByLabel(items, "Shell (.sh)").className).toContain("bg-theme-elevated");
      expect(itemByLabel(items, "PowerShell").className).not.toContain("bg-theme-elevated");
      unmount();
    }
  });

  it("calls onGenerate with the chosen os and closes", () => {
    const { trigger, getAllByRole, queryAllByRole, onGenerate } = setup({ defaultOs: "windows" });
    fireEvent.click(trigger);
    fireEvent.click(itemByLabel(getAllByRole("menuitem"), "Shell (.sh)"));
    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(onGenerate.mock.calls[0][0]).toBe("posix");
    expect(queryAllByRole("menuitem").length).toBe(0);
  });

  it("generates the default flavour when its item is chosen", () => {
    const { trigger, getAllByRole, onGenerate } = setup({ defaultOs: "windows" });
    fireEvent.click(trigger);
    fireEvent.click(itemByLabel(getAllByRole("menuitem"), "PowerShell"));
    expect(onGenerate.mock.calls[0][0]).toBe("windows");
  });

  it("disables and relabels the trigger while generating", () => {
    const { trigger, queryAllByRole } = setup({ generating: true });
    expect(trigger.disabled).toBe(true);
    expect((trigger.textContent ?? "").includes("Generating...")).toBe(true);
    expect((trigger.textContent ?? "").includes("Generate script")).toBe(false);
    fireEvent.click(trigger);
    expect(queryAllByRole("menuitem").length).toBe(0);
  });

  it("disables the trigger when disabled is set", () => {
    const { trigger } = setup({ disabled: true });
    expect(trigger.disabled).toBe(true);
  });

  it("flips aria-expanded as the menu opens and closes", () => {
    const { trigger } = setup();
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on Escape and returns focus to the trigger", () => {
    const { trigger, queryAllByRole } = setup();
    fireEvent.click(trigger);
    expect(queryAllByRole("menuitem").length).toBe(2);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(queryAllByRole("menuitem").length).toBe(0);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on a click outside", () => {
    const { trigger, queryAllByRole } = setup();
    fireEvent.click(trigger);
    expect(queryAllByRole("menuitem").length).toBe(2);
    fireEvent.click(document.body);
    expect(queryAllByRole("menuitem").length).toBe(0);
  });

  it("stays open when the menu panel itself is clicked", () => {
    const { trigger, getByRole, queryAllByRole } = setup();
    fireEvent.click(trigger);
    fireEvent.click(getByRole("menu"));
    expect(queryAllByRole("menuitem").length).toBe(2);
  });
});
