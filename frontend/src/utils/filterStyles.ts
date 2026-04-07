// frontend/src/utils/filterStyles.ts

export type FilterBadgeStyle =
  | "solid"
  | "muted"
  | "frosted-glass"
  | "outlined"
  | "text-only"
  | "indicator-dots"
  | "underline"
  | "tint-border"
  | "tint-border-bright";

export const FILTER_STYLE_OPTIONS: { value: FilterBadgeStyle; label: string }[] = [
  { value: "solid", label: "Solid" },
  { value: "muted", label: "Muted Backgrounds" },
  { value: "frosted-glass", label: "Frosted Glass" },
  { value: "outlined", label: "Outlined (Hollow)" },
  { value: "text-only", label: "Colored Text Only (Default)" },
  { value: "indicator-dots", label: "Indicator Dots" },
  { value: "underline", label: "Underline Accents" },
  { value: "tint-border", label: "Subtle Tint & Border" },
  { value: "tint-border-bright", label: "Subtle Tint & Border (Bright)" },
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


function getThemeVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim() || fallback;
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
      return {
        style: {
          "background-color": hexToRgba(hexColor, 0.12),
          "border": `1px solid ${hexToRgba(hexColor, 0.25)}`,
          "backdrop-filter": "blur(8px) saturate(1.4)",
          "-webkit-backdrop-filter": "blur(8px) saturate(1.4)",
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
    default:
      // Backwards compat: unknown style (e.g. renamed "muted-bright") falls back to frosted-glass
      return getFilterBadgeStyle("frosted-glass", hexColor);
  }
}
