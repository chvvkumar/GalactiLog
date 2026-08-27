import { describe, expect, it } from "vitest";
import { THEMES, THEME_GROUPS } from "./themes";

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe("THEME_GROUPS", () => {
  it("lists every theme exactly once", () => {
    const ids = THEME_GROUPS.flatMap((g) => g.themes.map((t) => t.id));
    expect(ids.sort()).toEqual(THEMES.map((t) => t.id).sort());
  });

  it("orders each group darkest to lightest by page base", () => {
    for (const g of THEME_GROUPS) {
      const lum = g.themes.map((t) => luminance(t.glass ? t.glass.gradientFrom : t.tokens["bg-base"]));
      expect(lum, g.id).toEqual([...lum].sort((a, b) => a - b));
    }
  });
});
