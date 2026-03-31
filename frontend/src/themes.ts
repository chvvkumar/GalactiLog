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
    name: "Dark",
    description: "Modern dark theme",
    tokens: {
      "bg-base": "#09090b",
      "bg-surface": "#18181b",
      "bg-elevated": "#27272a",
      "bg-hover": "#1f1f23",
      "bg-input": "#18181b",
      "border-default": "#27272a",
      "border-emphasis": "#333338",
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
      "border-emphasis": "rgba(255, 255, 255, 0.14)",
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
      "border-emphasis": "rgba(251, 191, 36, 0.24)",
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
  {
    id: "soft-zinc",
    name: "Soft Zinc",
    description: "Matte studio-grade dark grey",
    tokens: {
      "bg-base": "#1a1a1f",
      "bg-surface": "#252529",
      "bg-elevated": "#303036",
      "bg-hover": "#2a2a30",
      "bg-input": "#202025",
      "border-default": "#2c2c32",
      "border-emphasis": "#333338",
      "text-primary": "#e8e8ec",
      "text-secondary": "#9898a0",
      "text-tertiary": "#68687a",
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
      "badge-bg": "#303036",
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
    id: "slate-blue",
    name: "Slate Blue",
    description: "Deep slate with muted blue tint",
    tokens: {
      "bg-base": "#111827",
      "bg-surface": "#1a2235",
      "bg-elevated": "#243044",
      "bg-hover": "#1e2840",
      "bg-input": "#151d30",
      "border-default": "#1f2937",
      "border-emphasis": "#263040",
      "text-primary": "#eef2f7",
      "text-secondary": "#8c9ab5",
      "text-tertiary": "#5d6e8a",
      "accent": "#60a5fa",
      "accent-hover": "#93c5fd",
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
      "badge-bg": "#243044",
      "badge-text": "#d1d8e5",
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
    id: "warm-stone",
    name: "Warm Stone",
    description: "Dark graphite with earthy undertones",
    tokens: {
      "bg-base": "#1a1714",
      "bg-surface": "#242018",
      "bg-elevated": "#302b22",
      "bg-hover": "#2a2520",
      "bg-input": "#1e1b16",
      "border-default": "#282420",
      "border-emphasis": "#302c24",
      "text-primary": "#eae6e0",
      "text-secondary": "#a09888",
      "text-tertiary": "#706858",
      "accent": "#d4a76a",
      "accent-hover": "#e4c08a",
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
      "badge-bg": "#302b22",
      "badge-text": "#d4cec4",
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
    id: "deep-neutral",
    name: "Deep Neutral",
    description: "Ultra-dark pure graphite grey",
    tokens: {
      "bg-base": "#121212",
      "bg-surface": "#1a1a1a",
      "bg-elevated": "#242424",
      "bg-hover": "#1e1e1e",
      "bg-input": "#161616",
      "border-default": "#1e1e1e",
      "border-emphasis": "#252525",
      "text-primary": "#f0f0f0",
      "text-secondary": "#999999",
      "text-tertiary": "#666666",
      "accent": "#60a5fa",
      "accent-hover": "#93c5fd",
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
      "badge-bg": "#242424",
      "badge-text": "#d4d4d4",
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

export const DEFAULT_THEME_ID = "deep-neutral";

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
