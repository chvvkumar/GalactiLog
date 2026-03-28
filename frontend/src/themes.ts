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
    id: "deep-space",
    name: "Deep Space",
    description: "True dark theme for nighttime use",
    tokens: {
      "bg-base": "#0e0e0e",
      "bg-surface": "#1a1a1a",
      "bg-elevated": "#242424",
      "border-default": "#1f1f1f",
      "border-emphasis": "#363636",
      "text-primary": "#e6e6e6",
      "text-secondary": "#9a9a9a",
      "text-tertiary": "#6b6b6b",
      "accent": "#7c8aff",
      "accent-hover": "#9ba6ff",
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
      "badge-bg": "#2a2a3a",
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
  {
    id: "observatory",
    name: "Observatory",
    description: "Navy tones inspired by observatory control rooms",
    tokens: {
      "bg-base": "#0d1520",
      "bg-surface": "#142030",
      "bg-elevated": "#1a2940",
      "border-default": "#182840",
      "border-emphasis": "#243e5e",
      "text-primary": "#dce4ec",
      "text-secondary": "#8a9bb5",
      "text-tertiary": "#5a7090",
      "accent": "#5eb8d9",
      "accent-hover": "#7dcce8",
      "success": "#4ad49a",
      "warning": "#e8b44a",
      "error": "#e8616a",
      "info": "#6ea8e8",
      "metric-integration": "#6ea8e8",
      "metric-frames": "#4ad49a",
      "metric-hfr": "#e8b44a",
      "metric-eccentricity": "#b88ae8",
      "metric-fwhm": "#5eb8d9",
      "metric-stars": "#4ad4b4",
      "metric-guiding": "#e8616a",
      "metric-temp": "#5eb8d9",
      "metric-gain": "#7ae8a0",
      "metric-time": "#e89a8a",
      "metric-best": "#4ad49a",
      "metric-worst": "#e8616a",
      "badge-bg": "#1a2940",
      "badge-text": "#c0cee0",
      "filter-ha": "#e85858",
      "filter-oiii": "#50b0f0",
      "filter-sii": "#f0c050",
      "filter-l": "#d0d8e0",
      "filter-r": "#f06868",
      "filter-g": "#58c858",
      "filter-b": "#6888f0",
    },
  },
  {
    id: "nebula",
    name: "Nebula",
    description: "Warm dark theme with amber accents",
    tokens: {
      "bg-base": "#151210",
      "bg-surface": "#211e1a",
      "bg-elevated": "#2c2722",
      "border-default": "#2a2520",
      "border-emphasis": "#3e3630",
      "text-primary": "#e8e0d4",
      "text-secondary": "#a89888",
      "text-tertiary": "#786858",
      "accent": "#e8a838",
      "accent-hover": "#f0be58",
      "success": "#6ec870",
      "warning": "#e8883a",
      "error": "#d45050",
      "info": "#6a9ed4",
      "metric-integration": "#6a9ed4",
      "metric-frames": "#6ec870",
      "metric-hfr": "#e8a838",
      "metric-eccentricity": "#c090d4",
      "metric-fwhm": "#6ab8d4",
      "metric-stars": "#50c8a0",
      "metric-guiding": "#d45050",
      "metric-temp": "#6ab8d4",
      "metric-gain": "#90d890",
      "metric-time": "#d4908a",
      "metric-best": "#6ec870",
      "metric-worst": "#d45050",
      "badge-bg": "#2c2722",
      "badge-text": "#d0c8b8",
      "filter-ha": "#d84848",
      "filter-oiii": "#48a8e0",
      "filter-sii": "#d8a838",
      "filter-l": "#d0ccc0",
      "filter-r": "#e05858",
      "filter-g": "#58b858",
      "filter-b": "#5878e0",
    },
  },
  {
    id: "daylight",
    name: "Daylight",
    description: "Clean light theme for daytime use",
    tokens: {
      "bg-base": "#f8f6f3",
      "bg-surface": "#ffffff",
      "bg-elevated": "#ffffff",
      "border-default": "#e8e4e0",
      "border-emphasis": "#d0c8c0",
      "text-primary": "#1c1917",
      "text-secondary": "#57534e",
      "text-tertiary": "#a8a29e",
      "accent": "#4f46e5",
      "accent-hover": "#4338ca",
      "success": "#16a34a",
      "warning": "#d97706",
      "error": "#dc2626",
      "info": "#2563eb",
      "metric-integration": "#2563eb",
      "metric-frames": "#16a34a",
      "metric-hfr": "#d97706",
      "metric-eccentricity": "#9333ea",
      "metric-fwhm": "#0284c7",
      "metric-stars": "#0d9488",
      "metric-guiding": "#e11d48",
      "metric-temp": "#0284c7",
      "metric-gain": "#15803d",
      "metric-time": "#dc2626",
      "metric-best": "#16a34a",
      "metric-worst": "#dc2626",
      "badge-bg": "#f0ede8",
      "badge-text": "#57534e",
      "filter-ha": "#b83030",
      "filter-oiii": "#2878b0",
      "filter-sii": "#b08820",
      "filter-l": "#787878",
      "filter-r": "#c83838",
      "filter-g": "#288828",
      "filter-b": "#3858c0",
    },
  },
];

export const DEFAULT_THEME_ID = "deep-space";

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
