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

export interface GlassConfig {
  blur: string;
  saturate: string;
  gradientFrom: string;
  gradientTo: string;
}

export interface ThemeMeta {
  id: string;
  name: string;
  description: string;
  tokens: ThemeTokens;
  glass?: GlassConfig;
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
  {
    id: "glass-nebula",
    name: "Nebula Glass",
    description: "Deep space glassmorphism",
    glass: {
      blur: "14px",
      saturate: "1.8",
      gradientFrom: "#0a0618",
      gradientTo: "#0c1225",
    },
    tokens: {
      "bg-base": "#08040f",
      "bg-surface": "rgba(18, 10, 42, 0.55)",
      "bg-elevated": "rgba(30, 18, 62, 0.65)",
      "bg-hover": "rgba(25, 14, 52, 0.45)",
      "bg-input": "rgba(12, 6, 28, 0.75)",
      "border-default": "rgba(120, 80, 200, 0.2)",
      "border-emphasis": "rgba(140, 100, 220, 0.35)",
      "text-primary": "#f0edf5",
      "text-secondary": "#a89cc0",
      "text-tertiary": "#7a6b96",
      "accent": "#a78bfa",
      "accent-hover": "#c4b5fd",
      "success": "#4ade80",
      "warning": "#fbbf24",
      "error": "#f87171",
      "info": "#60a5fa",
      "metric-integration": "#7cacf8",
      "metric-frames": "#4ade80",
      "metric-hfr": "#fbbf24",
      "metric-eccentricity": "#d8b4fe",
      "metric-fwhm": "#67c8f5",
      "metric-stars": "#2dd4bf",
      "metric-guiding": "#fb7185",
      "metric-temp": "#67c8f5",
      "metric-gain": "#86efac",
      "metric-time": "#fca5a5",
      "metric-best": "#4ade80",
      "metric-worst": "#f87171",
      "badge-bg": "rgba(30, 18, 62, 0.6)",
      "badge-text": "#d1d0e0",
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
    id: "glass-aurora",
    name: "Aurora Glass",
    description: "Northern lights glassmorphism",
    glass: {
      blur: "14px",
      saturate: "1.8",
      gradientFrom: "#040d0a",
      gradientTo: "#0a1520",
    },
    tokens: {
      "bg-base": "#030a07",
      "bg-surface": "rgba(8, 28, 20, 0.55)",
      "bg-elevated": "rgba(12, 42, 30, 0.65)",
      "bg-hover": "rgba(10, 35, 24, 0.45)",
      "bg-input": "rgba(6, 20, 14, 0.75)",
      "border-default": "rgba(52, 211, 153, 0.18)",
      "border-emphasis": "rgba(52, 211, 153, 0.32)",
      "text-primary": "#ecf5f0",
      "text-secondary": "#94b8a6",
      "text-tertiary": "#628574",
      "accent": "#34d399",
      "accent-hover": "#6ee7b7",
      "success": "#4ade80",
      "warning": "#fbbf24",
      "error": "#f87171",
      "info": "#60a5fa",
      "metric-integration": "#60a5fa",
      "metric-frames": "#4ade80",
      "metric-hfr": "#fbbf24",
      "metric-eccentricity": "#c084fc",
      "metric-fwhm": "#38bdf8",
      "metric-stars": "#5eead4",
      "metric-guiding": "#fb7185",
      "metric-temp": "#38bdf8",
      "metric-gain": "#86efac",
      "metric-time": "#fca5a5",
      "metric-best": "#4ade80",
      "metric-worst": "#f87171",
      "badge-bg": "rgba(12, 42, 30, 0.6)",
      "badge-text": "#c8e0d4",
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
    id: "glass-nebula-cyan",
    name: "Nebula Cyan",
    description: "Holographic star-chart glassmorphism",
    glass: {
      blur: "14px",
      saturate: "1.8",
      gradientFrom: "#020617",
      gradientTo: "#0c1a2e",
    },
    tokens: {
      "bg-base": "#020617",
      "bg-surface": "rgba(30, 41, 59, 0.40)",
      "bg-elevated": "rgba(40, 52, 72, 0.50)",
      "bg-hover": "rgba(255, 255, 255, 0.05)",
      "bg-input": "rgba(15, 23, 42, 0.70)",
      "border-default": "rgba(255, 255, 255, 0.10)",
      "border-emphasis": "rgba(255, 255, 255, 0.18)",
      "text-primary": "#f8fafc",
      "text-secondary": "#cbd5e1",
      "text-tertiary": "#94a3b8",
      "accent": "#38bdf8",
      "accent-hover": "#7dd3fc",
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
      "badge-bg": "rgba(30, 41, 59, 0.50)",
      "badge-text": "#e2e8f0",
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
    id: "glass-stellar",
    name: "Stellar Glass",
    description: "Warm cosmic glassmorphism",
    glass: {
      blur: "14px",
      saturate: "1.8",
      gradientFrom: "#120a04",
      gradientTo: "#1a0810",
    },
    tokens: {
      "bg-base": "#0c0804",
      "bg-surface": "rgba(32, 18, 8, 0.55)",
      "bg-elevated": "rgba(48, 28, 12, 0.65)",
      "bg-hover": "rgba(40, 22, 10, 0.45)",
      "bg-input": "rgba(22, 12, 6, 0.75)",
      "border-default": "rgba(251, 191, 36, 0.18)",
      "border-emphasis": "rgba(251, 191, 36, 0.32)",
      "text-primary": "#f5f0e8",
      "text-secondary": "#bba882",
      "text-tertiary": "#8a7654",
      "accent": "#f59e0b",
      "accent-hover": "#fbbf24",
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
      "badge-bg": "rgba(48, 28, 12, 0.6)",
      "badge-text": "#e0d4c0",
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
  if (theme.glass) {
    root.style.setProperty("--glass-blur", theme.glass.blur);
    root.style.setProperty("--glass-saturate", theme.glass.saturate);
    root.style.setProperty("--glass-gradient-from", theme.glass.gradientFrom);
    root.style.setProperty("--glass-gradient-to", theme.glass.gradientTo);
    root.setAttribute("data-theme-style", "glass");
  } else {
    root.style.setProperty("--glass-blur", "0px");
    root.style.setProperty("--glass-saturate", "1");
    root.style.removeProperty("--glass-gradient-from");
    root.style.removeProperty("--glass-gradient-to");
    root.setAttribute("data-theme-style", "solid");
  }
}

export function applyTextSize(sizeId: string): void {
  const preset = TEXT_SIZES.find((s) => s.id === sizeId) ?? TEXT_SIZES[1];
  document.documentElement.style.fontSize = preset.fontSize;
}
