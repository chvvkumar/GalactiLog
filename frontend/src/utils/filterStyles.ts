// frontend/src/utils/filterStyles.ts

// Canonical filter category for a given filter name.
// Maps all common naming variations to one of the 7 standard categories,
// or returns null for non-standard filters (IR, Duoband, etc.)
export function canonicalFilterCategory(name: string): string | null {
  const n = name.toLowerCase().replace(/[_\-\s]/g, "");
  // Luminance
  if (n === "l" || n === "lum" || n === "luminance" || n === "luminosity" || n === "clear") return "L";
  // Red
  if (n === "r" || n === "red") return "R";
  // Green
  if (n === "g" || n === "green") return "G";
  // Blue
  if (n === "b" || n === "blue") return "B";
  // Sulfur II - check before Ha to avoid "sho" false matches
  if (n === "sii" || n === "s2" || n === "s" || n === "sulfur" || n === "sulphur"
    || n === "sulfurii" || n === "sulphurii") return "SII";
  // Hydrogen alpha
  if (n === "ha" || n === "h" || n === "halpha" || n === "hydrogenalpha"
    || n === "hydrogen" || n === "h alpha" || n === "656nm" || n === "656") return "Ha";
  // Oxygen III
  if (n === "oiii" || n === "o3" || n === "o" || n === "oxygen" || n === "oxygeniii"
    || n === "500nm" || n === "501nm") return "OIII";
  return null;
}

// Single default gray used whenever a filter name has no color-map, alias-map,
// or canonicalCategory hit (AUD-024).
const DEFAULT_FILTER_COLOR = "#666666";

// Shared filter -> color resolution, used everywhere a filter name needs a
// display color (badges, charts, toggles) so the same filter always renders
// the same color regardless of page (AUD-024).
export function getFilterColor(
  name: string,
  colorMap: Record<string, string>,
  aliasMap: Record<string, string>,
): string {
  const canonical = aliasMap[name] || name;
  if (colorMap[canonical]) return colorMap[canonical];
  if (colorMap[name]) return colorMap[name];
  const cat = canonicalFilterCategory(name);
  if (cat && colorMap[cat]) return colorMap[cat];
  return DEFAULT_FILTER_COLOR;
}

export type FilterBadgeStyle =
  | "solid"
  | "muted"
  | "frosted-glass"
  | "outlined"
  | "text-only"
  | "indicator-dots"
  | "underline"
  | "tint-border"
  | "tint-border-bright"
  | "frost"
  | "thin-glass"
  | "led"
  | "brushed"
  | "hairline"
  | "ticket"
  | "ghost";

// "indicator-dots" and "underline" still render for stored settings but are
// no longer offered in the picker.
export const FILTER_STYLE_OPTIONS: { value: FilterBadgeStyle; label: string }[] = [
  { value: "solid", label: "Solid" },
  { value: "muted", label: "Muted Backgrounds" },
  { value: "frosted-glass", label: "Frosted Glass" },
  { value: "frost", label: "Frost (Light Haze)" },
  { value: "thin-glass", label: "Thin Glass" },
  { value: "outlined", label: "Outlined (Hollow)" },
  { value: "hairline", label: "Hairline Ring" },
  { value: "text-only", label: "Colored Text Only (Default)" },
  { value: "ghost", label: "Ghost Cap" },
  { value: "ticket", label: "Ticket Stub" },
  { value: "tint-border", label: "Subtle Tint & Border" },
  { value: "tint-border-bright", label: "Subtle Tint & Border (Bright)" },
  { value: "led", label: "LED Backlit" },
  { value: "brushed", label: "Brushed Metal" },
];

export interface FilterBadgeStyleResult {
  /** Inline CSS properties to spread onto the element */
  style: Record<string, string>;
  /** When present, render a 6px colored dot before the label */
  dot?: string;
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ];
}

function hexToRgba(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}


// Cache CSS-var reads at module scope so each badge does not trigger a
// getComputedStyle(document.documentElement) layout read per render.
// Invalidated whenever the active theme changes (see invalidateThemeVarCache).
const themeVarCache = new Map<string, string>();

export function invalidateThemeVarCache(): void {
  themeVarCache.clear();
}

function getThemeVar(name: string, fallback: string): string {
  const cached = themeVarCache.get(name);
  if (cached !== undefined) return cached || fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(`--color-${name}`)
    .trim();
  themeVarCache.set(name, value);
  return value || fallback;
}

export function getFilterBadgeStyle(
  styleName: FilterBadgeStyle,
  hexColor: string,
): FilterBadgeStyleResult {
  const badgeBg = () => getThemeVar("badge-bg", "#2a2a3a");
  const badgeText = () => getThemeVar("badge-text", "#d1d5db");
  switch (styleName) {
    case "solid":
      return {
        style: {
          "background-color": hexColor,
          color: "black",
        },
      };
    case "muted":
      return {
        style: {
          "background-color": hexToRgba(hexColor, 0.15),
          color: hexColor,
        },
      };
    case "frosted-glass":
      // Frosted glass look WITHOUT backdrop-filter (was the dominant scroll-jank
      // source: ~600 composite layers on the dashboard). A frosted pill over the
      // dark page reads as a slightly lighter, tinted opaque surface, so layer a
      // neutral translucent base under a faint color tint and keep the edge
      // highlight + soft shadow. No per-element compositing required.
      return {
        style: {
          "background-image": `linear-gradient(${hexToRgba(hexColor, 0.18)}, ${hexToRgba(hexColor, 0.18)})`,
          "background-color": "rgba(40, 44, 58, 0.85)",
          "border": `1px solid ${hexToRgba(hexColor, 0.25)}`,
          "box-shadow": `inset 0 1px 0 0 rgba(255,255,255,0.06), 0 2px 8px ${hexToRgba(hexColor, 0.15)}`,
          color: hexColor,
        },
      };
    case "outlined":
      return {
        style: {
          "background-color": "transparent",
          border: `1.5px solid ${hexColor}`,
          color: hexColor,
        },
      };
    case "text-only":
      return {
        style: {
          "background-color": badgeBg(),
          color: hexColor,
        },
      };
    case "indicator-dots":
      return {
        style: {
          "background-color": badgeBg(),
          color: badgeText(),
        },
        dot: hexColor,
      };
    case "underline":
      return {
        style: {
          "background-color": badgeBg(),
          color: badgeText(),
          "border-bottom": `2px solid ${hexColor}`,
        },
      };
    case "tint-border":
      return {
        style: {
          "background-color": hexToRgba(hexColor, 0.1),
          border: `1px solid ${hexToRgba(hexColor, 0.3)}`,
          color: hexColor,
        },
      };
    case "tint-border-bright":
      return {
        style: {
          "background-color": hexToRgba(hexColor, 0.55),
          border: `1px solid ${hexToRgba(hexColor, 0.65)}`,
          color: "black",
        },
      };
    // The seven styles below came from the 2026-08-26 badge study. Glass
    // variants deliberately omit backdrop-filter (see frosted-glass above).
    case "frost":
      return {
        style: {
          "background-image": "linear-gradient(180deg, rgba(255,255,255,0.2), rgba(255,255,255,0.04) 55%, rgba(255,255,255,0))",
          "background-color": hexToRgba(hexColor, 0.3),
          border: `1px solid ${hexToRgba(hexColor, 0.5)}`,
          "box-shadow": "inset 0 1px 0 rgba(255,255,255,0.35), 0 1px 2px rgba(0,0,0,0.4)",
          "text-shadow": "0 1px 1px rgba(0,0,0,0.35)",
          color: badgeText(),
        },
      };
    case "thin-glass":
      return {
        style: {
          "background-image": "linear-gradient(180deg, rgba(255,255,255,0.14), rgba(255,255,255,0) 50%)",
          "background-color": hexToRgba(hexColor, 0.09),
          border: `1px solid ${hexToRgba(hexColor, 0.55)}`,
          "box-shadow": `inset 0 0 0 1px rgba(255,255,255,0.06), inset 0 0 8px ${hexToRgba(hexColor, 0.45)}, 0 0 6px ${hexToRgba(hexColor, 0.18)}`,
          color: `color-mix(in srgb, ${hexColor} 55%, ${badgeText()})`,
        },
      };
    case "led":
      return {
        style: {
          "background-image": "linear-gradient(180deg, rgba(0,0,0,0.45), rgba(0,0,0,0.7))",
          "box-shadow": `inset 0 1px 0 rgba(255,255,255,0.08), inset 0 0 0 1px rgba(0,0,0,0.6), inset 0 -3px 4px -2px ${hexToRgba(hexColor, 0.55)}, 0 0 0 1px ${hexToRgba(hexColor, 0.3)}, 0 1px 5px ${hexToRgba(hexColor, 0.4)}`,
          "text-shadow": `0 0 3px ${hexToRgba(hexColor, 0.7)}`,
          filter: "brightness(1.4)",
          color: hexColor,
        },
      };
    case "brushed":
      return {
        style: {
          "background-image": `repeating-linear-gradient(0deg, rgba(255,255,255,0.07) 0 1px, rgba(0,0,0,0) 1px 2px), linear-gradient(180deg, rgba(255,255,255,0.15), rgba(255,255,255,0) 50%, rgba(0,0,0,0.18)), linear-gradient(${hexToRgba(hexColor, 0.28)}, ${hexToRgba(hexColor, 0.28)})`,
          "background-color": badgeBg(),
          "box-shadow": `inset 0 1px 0 rgba(255,255,255,0.28), inset 0 0 0 1px ${hexToRgba(hexColor, 0.45)}, 0 1px 2px rgba(0,0,0,0.5)`,
          "text-shadow": "0 1px 1px rgba(0,0,0,0.7)",
          color: badgeText(),
        },
      };
    case "hairline":
      return {
        style: {
          "background-color": "transparent",
          "box-shadow": `inset 0 0 0 0.5px ${hexToRgba(hexColor, 0.6)}`,
          color: hexColor,
        },
      };
    case "ticket":
      return {
        style: {
          "background-color": hexToRgba(hexColor, 0.05),
          outline: `1px dashed ${hexToRgba(hexColor, 0.55)}`,
          "outline-offset": "-1px",
          "font-family": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          "letter-spacing": "0.04em",
          color: hexColor,
        },
      };
    case "ghost":
      // The colored first glyph is a ::first-letter rule in index.css keyed on
      // this --ghost custom property ([style*="--ghost:"]), so no consumer has
      // to add a class. ::first-letter needs a block container, which that
      // rule also provides.
      return {
        style: {
          "--ghost": hexColor,
          "background-color": "transparent",
          color: `color-mix(in srgb, ${badgeText()} 62%, transparent)`,
        },
      };
    default:
      // Backwards compat: unknown style (e.g. renamed "muted-bright") falls back to frosted-glass
      return getFilterBadgeStyle("frosted-glass", hexColor);
  }
}
