// frontend/src/themes.ts
// ============================================================
// SINGLE SOURCE OF TRUTH for all GalactiLog themes.
// To add a new theme: add an entry to THEMES below. Done.
// ============================================================

export interface ThemeTokens {
  // Surfaces
  "bg-base": string;
  "bg-surface": string;
  "bg-elevated": string;
  "bg-hover": string;
  "bg-input": string;
  // Borders
  "border-default": string;
  "border-emphasis": string;
  // Text
  "text-primary": string;
  "text-secondary": string;
  "text-tertiary": string;
  // Accent
  "accent": string;
  "accent-hover": string;
  // Semantic
  "success": string;
  "warning": string;
  "error": string;
  "info": string;
  // Metric colors (for data tables)
  "metric-integration": string;
  "metric-frames": string;
  "metric-hfr": string;
  "metric-eccentricity": string;
  "metric-fwhm": string;
  "metric-stars": string;
  "metric-guiding": string;
  "metric-temp": string;
  "metric-gain": string;
  "metric-time": string;
  // Best/Worst indicators
  "metric-best": string;
  "metric-worst": string;
  // Badge background (for filter badge styles that need a surface)
  "badge-bg": string;
  "badge-text": string;
  // Filter colors (adjusted per theme for contrast)
  "filter-ha": string;
  "filter-oiii": string;
  "filter-sii": string;
  "filter-l": string;
  "filter-r": string;
  "filter-g": string;
  "filter-b": string;
}

export interface ThemeMeta {
  id: string;
  name: string;
  description: string;
  tokens: ThemeTokens;
}

export const THEMES: ThemeMeta[] = [
  {
    id: "default-dark",
    name: "Default Dark",
    description: "Modern dark theme",
    tokens: {
      "bg-base": "#09090b",
      "bg-surface": "#18181b",
      "bg-elevated": "#27272a",
      "bg-hover": "#1f1f23",
      "bg-input": "#18181b",
      "border-default": "#27272a",
      "border-emphasis": "#3f3f46",
      "text-primary": "#fafafa",
      "text-secondary": "#a1a1aa",
      "text-tertiary": "#71717a",
      "accent": "#818cf8",
      "accent-hover": "#a5b4fc",
      "success": "#4ade80",
      "warning": "#fbbf24",
      "error": "#f87171",
      "info": "#60a5fa",
      "metric-integration": "#60a5fa",
      "metric-frames": "#4ade80",
      "metric-hfr": "#fbbf24",
      "metric-eccentricity": "#c084fc",
      "metric-fwhm": "#38bdf8",
      "metric-stars": "#2dd4bf",
      "metric-guiding": "#fb7185",
      "metric-temp": "#38bdf8",
      "metric-gain": "#86efac",
      "metric-time": "#fca5a5",
      "metric-best": "#4ade80",
      "metric-worst": "#f87171",
      "badge-bg": "#27272a",
      "badge-text": "#d1d5db",
      "filter-ha": "#e05555",
      "filter-oiii": "#4a9fe8",
      "filter-sii": "#e8b84a",
      "filter-l": "#d8d8d8",
      "filter-r": "#e86060",
      "filter-g": "#60c060",
      "filter-b": "#6080e8",
    },
  },
];

export const DEFAULT_THEME_ID = "default-dark";

export interface TextSizePreset {
  id: string;
  label: string;
  fontSize: string;
}

export const TEXT_SIZES: TextSizePreset[] = [
  { id: "small", label: "Small", fontSize: "13px" },
  { id: "medium", label: "Medium", fontSize: "14px" },
  { id: "large", label: "Large", fontSize: "16px" },
  { id: "x-large", label: "Extra Large", fontSize: "18px" },
];

export const DEFAULT_TEXT_SIZE = "medium";

export function getThemeById(id: string): ThemeMeta {
  return THEMES.find((t) => t.id === id) ?? THEMES[0];
}

export function applyTheme(themeId: string): void {
  const theme = getThemeById(themeId);
  const root = document.documentElement;
  for (const [token, value] of Object.entries(theme.tokens)) {
    root.style.setProperty(`--color-${token}`, value);
  }
}

export function applyTextSize(sizeId: string): void {
  const preset = TEXT_SIZES.find((s) => s.id === sizeId) ?? TEXT_SIZES[1];
  document.documentElement.style.fontSize = preset.fontSize;
}
