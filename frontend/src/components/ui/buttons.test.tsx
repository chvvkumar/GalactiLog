import { describe, it, expect } from "vitest";
import { render } from "@solidjs/testing-library";
import Button, { buttonClasses } from "./Button";
import Toggle, { toggleStyle, toggleClasses } from "./Toggle";
import IconButton, { iconButtonClasses } from "./IconButton";

describe("buttonClasses", () => {
  it("carries the signature token for each variant", () => {
    expect(buttonClasses("primary")).toContain("bg-theme-accent/15");
    expect(buttonClasses("secondary")).toContain("bg-theme-surface");
    expect(buttonClasses("danger")).toContain("bg-theme-error/15");
    expect(buttonClasses("warning")).toContain("bg-theme-warning/15");
  });

  it("applies size padding", () => {
    expect(buttonClasses("primary", "sm")).toContain("px-3 py-1");
    expect(buttonClasses("primary", "md")).toContain("px-4 py-1.5");
  });

  it("includes base tokens", () => {
    const cls = buttonClasses("primary", "md");
    expect(cls).toContain("rounded");
    expect(cls).toContain("text-sm");
    expect(cls).toContain("font-medium");
    expect(cls).toContain("transition-colors");
    expect(cls).toContain("disabled:opacity-50");
    expect(cls).toContain("disabled:cursor-not-allowed");
  });

  it("appends extra classes last", () => {
    const cls = buttonClasses("primary", "md", "w-full custom-x");
    expect(cls).toContain("w-full custom-x");
    expect(cls.trim().endsWith("w-full custom-x")).toBe(true);
  });

  it("defaults to primary + md", () => {
    expect(buttonClasses()).toBe(buttonClasses("primary", "md"));
  });
});

describe("toggleStyle", () => {
  it("builds active inline style from a color", () => {
    expect(toggleStyle(true, "#e0b0ff")).toEqual({
      "border-color": "#e0b0ff",
      "background-color": "#e0b0ff22",
      color: "#e0b0ff",
    });
  });

  it("mixes a var() color instead of appending a hex alpha suffix", () => {
    const style = toggleStyle(true, "var(--color-info)");
    expect(style?.["background-color"]).toBe(
      "color-mix(in srgb, var(--color-info) 13%, transparent)",
    );
    // Border and text keep the raw color in both paths.
    expect(style?.["border-color"]).toBe("var(--color-info)");
    expect(style?.color).toBe("var(--color-info)");
    // A hex literal still uses the plain alpha-suffix path.
    expect(toggleStyle(true, "#e0b0ff")?.["background-color"]).toBe("#e0b0ff22");
  });

  it("builds inactive inline style with var() fallbacks", () => {
    expect(toggleStyle(false, "#e0b0ff")).toEqual({
      "border-color": "var(--color-border-default)",
      "background-color": "var(--color-bg-elevated)",
      color: "var(--color-text-tertiary)",
    });
  });

  it("returns null without a color", () => {
    expect(toggleStyle(true)).toBeNull();
    expect(toggleStyle(false)).toBeNull();
  });
});

describe("toggleClasses", () => {
  it("uses accent token when active and no color", () => {
    expect(toggleClasses(true, false)).toContain("bg-theme-accent/20");
    expect(toggleClasses(true, false)).toContain("border-theme-accent");
    expect(toggleClasses(true, false)).toContain("text-theme-accent");
  });

  it("uses tertiary token when inactive and no color", () => {
    const cls = toggleClasses(false, false);
    expect(cls).toContain("text-theme-text-tertiary");
    expect(cls).toContain("bg-theme-elevated");
    expect(cls).toContain("border-theme-border");
  });

  it("omits state tokens when a color drives styling", () => {
    const cls = toggleClasses(true, true);
    expect(cls).not.toContain("bg-theme-accent/20");
    expect(cls).not.toContain("text-theme-text-tertiary");
  });

  it("includes base tokens and appends extra", () => {
    const cls = toggleClasses(false, false, "extra-x");
    expect(cls).toContain("px-2 py-0.5");
    expect(cls).toContain("text-caption");
    expect(cls).toContain("cursor-pointer");
    expect(cls).toContain("extra-x");
  });
});

describe("iconButtonClasses", () => {
  it("uses text-primary hover for default", () => {
    const cls = iconButtonClasses("default");
    expect(cls).toContain("text-theme-text-tertiary");
    expect(cls).toContain("hover:text-theme-text-primary");
  });

  it("uses error hover for danger", () => {
    const cls = iconButtonClasses("danger");
    expect(cls).toContain("hover:text-theme-error");
    expect(cls).not.toContain("hover:text-theme-text-primary");
  });

  it("defaults to default variant and appends extra", () => {
    expect(iconButtonClasses()).toBe(iconButtonClasses("default"));
    expect(iconButtonClasses("default", "leading-none")).toContain("leading-none");
  });
});

describe("rendered components carry the right classes", () => {
  it("Button renders a native button with variant + size classes", () => {
    const { getByRole } = render(() => (
      <Button variant="danger" size="sm">
        Delete
      </Button>
    ));
    const btn = getByRole("button") as HTMLButtonElement;
    expect(btn.className).toContain("bg-theme-error/15");
    expect(btn.className).toContain("px-3 py-1");
  });

  it("Button spreads through native props", () => {
    const { getByRole } = render(() => (
      <Button type="submit" disabled aria-label="save">
        Save
      </Button>
    ));
    const btn = getByRole("button") as HTMLButtonElement;
    expect(btn.type).toBe("submit");
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-label")).toBe("save");
  });

  it("Toggle applies inline style when a color is given", () => {
    const { getByRole } = render(() => (
      <Toggle active={true} color="#e0b0ff">
        HFR
      </Toggle>
    ));
    const btn = getByRole("button") as HTMLButtonElement;
    expect(btn.style.backgroundColor).not.toBe("");
    expect(btn.className).not.toContain("bg-theme-accent/20");
  });

  it("Toggle uses accent classes without a color", () => {
    const { getByRole } = render(() => <Toggle active={true}>All</Toggle>);
    const btn = getByRole("button") as HTMLButtonElement;
    expect(btn.className).toContain("bg-theme-accent/20");
    expect(btn.getAttribute("style")).toBeNull();
  });

  it("IconButton renders danger hover class", () => {
    const { getByRole } = render(() => (
      <IconButton variant="danger" aria-label="remove">
        x
      </IconButton>
    ));
    const btn = getByRole("button") as HTMLButtonElement;
    expect(btn.className).toContain("hover:text-theme-error");
    expect(btn.getAttribute("aria-label")).toBe("remove");
  });
});
