import { describe, expect, it } from "vitest";
import { FILTER_STYLE_OPTIONS, getFilterBadgeStyle } from "./filterStyles";

describe("getFilterBadgeStyle", () => {
  it("returns a non-empty style for every picker option", () => {
    for (const opt of FILTER_STYLE_OPTIONS) {
      const result = getFilterBadgeStyle(opt.value, "#c44040");
      expect(Object.keys(result.style).length, opt.value).toBeGreaterThan(0);
    }
  });

  it("keeps rendering styles removed from the picker", () => {
    expect(getFilterBadgeStyle("indicator-dots", "#c44040").dot).toBe("#c44040");
    expect(getFilterBadgeStyle("underline", "#c44040").style["border-bottom"]).toContain("#c44040");
  });

  it("ghost exposes --ghost for the ::first-letter rule in index.css", () => {
    const { style } = getFilterBadgeStyle("ghost", "#c44040");
    expect(style["--ghost"]).toBe("#c44040");
    expect(style.color).toContain("transparent");
  });
});
