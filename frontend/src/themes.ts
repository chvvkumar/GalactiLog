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

export interface GlassOrb {
  color: string;   // e.g. "rgba(79,70,229,0.30)"
  x: string;       // CSS position, e.g. "-5%"
  y: string;
  size: string;    // e.g. "40%"
}

export interface GlassConfig {
  blur: string;
  saturate: string;
  gradientFrom: string;
  gradientTo: string;
  orbs?: GlassOrb[];
}

export interface ThemeMeta {
  id: string;
  name: string;
  description: string;
  order: number;
  tokens: ThemeTokens;
  glass?: GlassConfig;
}

export const THEMES: ThemeMeta[] = [
  // ── Glass themes (darkest) ──
  {
    id: "glass-nebula-cyan",
    name: "Nebula Cyan",
    description: "Holographic star-chart glassmorphism",
    order: 10,
    glass: {
      blur: "14px",
      saturate: "1.8",
      gradientFrom: "#020617",
      gradientTo: "#0c1a2e",
      orbs: [
        { color: "rgba(79, 70, 229, 0.40)", x: "-5%", y: "-10%", size: "45%" },
        { color: "rgba(22, 78, 99, 0.35)",  x: "65%", y: "10%",  size: "40%" },
        { color: "rgba(88, 28, 135, 0.35)", x: "10%", y: "55%",  size: "50%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(15, 23, 42, 0.35)",
      "bg-elevated": "rgba(30, 41, 59, 0.40)",
      "bg-hover": "rgba(255, 255, 255, 0.06)",
      "bg-input": "rgba(15, 23, 42, 0.55)",
      "border-default": "rgba(255, 255, 255, 0.12)",
      "border-emphasis": "rgba(255, 255, 255, 0.18)",
      "text-primary": "#f8fafc",
      "text-secondary": "#cbd5e1",
      "text-tertiary": "#9cb0c8",
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
    id: "glass-deep-space",
    name: "Deep Space",
    description: "True glassmorphic with frosted translucent panels",
    order: 20,
    glass: {
      blur: "20px",
      saturate: "1.6",
      gradientFrom: "#060b18",
      gradientTo: "#0a1628",
      orbs: [
        { color: "rgba(30, 58, 138, 0.35)",  x: "-5%", y: "-10%", size: "42%" },
        { color: "rgba(15, 40, 80, 0.30)",   x: "60%", y: "5%",   size: "38%" },
        { color: "rgba(49, 46, 129, 0.30)",  x: "15%", y: "55%",  size: "48%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(16, 28, 56, 0.30)",
      "bg-elevated": "rgba(22, 38, 72, 0.38)",
      "bg-hover": "rgba(30, 48, 88, 0.25)",
      "bg-input": "rgba(10, 18, 40, 0.55)",
      "border-default": "rgba(100, 160, 255, 0.12)",
      "border-emphasis": "rgba(100, 160, 255, 0.20)",
      "text-primary": "#f0f4ff",
      "text-secondary": "#8aa4cc",
      "text-tertiary": "#7a96b8",
      "accent": "#22d3ee",
      "accent-hover": "#67e8f9",
      "success": "#34d399",
      "warning": "#fbbf24",
      "error": "#f87171",
      "info": "#38bdf8",
      "metric-integration": "#38bdf8",
      "metric-frames": "#34d399",
      "metric-hfr": "#fbbf24",
      "metric-eccentricity": "#a78bfa",
      "metric-fwhm": "#22d3ee",
      "metric-stars": "#2dd4bf",
      "metric-guiding": "#fb7185",
      "metric-temp": "#38bdf8",
      "metric-gain": "#6ee7b7",
      "metric-time": "#fca5a5",
      "metric-best": "#34d399",
      "metric-worst": "#f87171",
      "badge-bg": "rgba(16, 28, 56, 0.60)",
      "badge-text": "#c8d8f0",
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
    id: "glass-void",
    name: "Void",
    description: "Dark glass with muted slate and indigo depth",
    order: 30,
    glass: {
      blur: "12px",
      saturate: "1.0",
      gradientFrom: "#0a0c14",
      gradientTo: "#0f1320",
      orbs: [
        { color: "rgba(30, 41, 59, 0.40)",  x: "-5%", y: "-10%", size: "45%" },
        { color: "rgba(15, 23, 42, 0.45)",  x: "60%", y: "50%",  size: "50%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(16, 18, 25, 0.85)",
      "bg-elevated": "rgba(24, 27, 38, 0.90)",
      "bg-hover": "rgba(30, 34, 48, 0.70)",
      "bg-input": "rgba(12, 14, 20, 0.90)",
      "border-default": "rgba(255, 255, 255, 0.08)",
      "border-emphasis": "rgba(255, 255, 255, 0.15)",
      "text-primary": "#e2e8f0",
      "text-secondary": "#94a3b8",
      "text-tertiary": "#7a8ba4",
      "accent": "#7aa2f7",
      "accent-hover": "#9dbcff",
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
      "badge-bg": "rgba(24, 27, 38, 0.85)",
      "badge-text": "#cbd5e1",
      "filter-ha": "#e05555",
      "filter-oiii": "#4a9fe8",
      "filter-sii": "#e8b84a",
      "filter-l": "#d8d8d8",
      "filter-r": "#e86060",
      "filter-g": "#60c060",
      "filter-b": "#6080e8",
    },
  },
  // ── Solid themes (dark → light) ──
  {
    id: "default-dark",
    name: "Dark",
    description: "Refined dark glass with subtle violet depth",
    order: 40,
    glass: {
      blur: "16px",
      saturate: "1.4",
      gradientFrom: "#08080f",
      gradientTo: "#12101e",
      orbs: [
        { color: "rgba(100, 80, 200, 0.30)", x: "-8%", y: "-5%", size: "45%" },
        { color: "rgba(30, 40, 100, 0.25)",  x: "65%", y: "15%", size: "38%" },
        { color: "rgba(120, 40, 100, 0.20)", x: "20%", y: "60%", size: "42%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(20, 20, 28, 0.40)",
      "bg-elevated": "rgba(32, 30, 42, 0.45)",
      "bg-hover": "rgba(255, 255, 255, 0.06)",
      "bg-input": "rgba(16, 16, 22, 0.55)",
      "border-default": "rgba(255, 255, 255, 0.10)",
      "border-emphasis": "rgba(255, 255, 255, 0.16)",
      "text-primary": "#fafafa",
      "text-secondary": "#a1a1aa",
      "text-tertiary": "#8a8a93",
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
      "badge-bg": "rgba(32, 30, 42, 0.55)",
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
    id: "deep-neutral",
    name: "Deep Neutral",
    description: "Ultra-dark graphite glass, nearly opaque",
    order: 50,
    glass: {
      blur: "10px",
      saturate: "1.0",
      gradientFrom: "#0a0a0a",
      gradientTo: "#141414",
      orbs: [
        { color: "rgba(80, 80, 80, 0.25)",  x: "-5%", y: "-10%", size: "45%" },
        { color: "rgba(90, 85, 75, 0.20)",  x: "60%", y: "50%",  size: "42%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(26, 26, 26, 0.75)",
      "bg-elevated": "rgba(36, 36, 36, 0.80)",
      "bg-hover": "rgba(255, 255, 255, 0.05)",
      "bg-input": "rgba(22, 22, 22, 0.80)",
      "border-default": "rgba(255, 255, 255, 0.08)",
      "border-emphasis": "rgba(255, 255, 255, 0.14)",
      "text-primary": "#f0f0f0",
      "text-secondary": "#999999",
      "text-tertiary": "#888888",
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
      "badge-bg": "rgba(36, 36, 36, 0.80)",
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
  {
    id: "slate-blue",
    name: "Slate Blue",
    description: "Deep oceanic glass with rich blue depth",
    order: 60,
    glass: {
      blur: "18px",
      saturate: "1.5",
      gradientFrom: "#060d1a",
      gradientTo: "#0c1830",
      orbs: [
        { color: "rgba(40, 70, 140, 0.35)",  x: "-5%", y: "-10%", size: "44%" },
        { color: "rgba(20, 60, 100, 0.25)",  x: "60%", y: "10%",  size: "38%" },
        { color: "rgba(50, 45, 120, 0.30)",  x: "15%", y: "55%",  size: "46%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(16, 26, 48, 0.32)",
      "bg-elevated": "rgba(24, 36, 60, 0.38)",
      "bg-hover": "rgba(255, 255, 255, 0.06)",
      "bg-input": "rgba(12, 20, 40, 0.55)",
      "border-default": "rgba(130, 170, 255, 0.10)",
      "border-emphasis": "rgba(130, 170, 255, 0.18)",
      "text-primary": "#eef2f7",
      "text-secondary": "#8c9ab5",
      "text-tertiary": "#7b8da6",
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
      "badge-bg": "rgba(24, 36, 60, 0.55)",
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
    description: "Smoked amber glass with earthy warmth",
    order: 70,
    glass: {
      blur: "12px",
      saturate: "1.2",
      gradientFrom: "#0e0c08",
      gradientTo: "#181410",
      orbs: [
        { color: "rgba(140, 100, 40, 0.30)", x: "-5%", y: "-10%", size: "44%" },
        { color: "rgba(120, 70, 40, 0.25)",  x: "60%", y: "15%",  size: "40%" },
        { color: "rgba(80, 90, 40, 0.20)",   x: "15%", y: "58%",  size: "45%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(36, 32, 24, 0.65)",
      "bg-elevated": "rgba(48, 43, 34, 0.70)",
      "bg-hover": "rgba(255, 255, 255, 0.05)",
      "bg-input": "rgba(30, 27, 22, 0.75)",
      "border-default": "rgba(255, 240, 200, 0.10)",
      "border-emphasis": "rgba(255, 240, 200, 0.16)",
      "text-primary": "#eae6e0",
      "text-secondary": "#a09888",
      "text-tertiary": "#8d8474",
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
      "badge-bg": "rgba(48, 43, 34, 0.70)",
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
    id: "soft-zinc",
    name: "Soft Zinc",
    description: "Studio matte glass with restrained violet",
    order: 80,
    glass: {
      blur: "12px",
      saturate: "1.1",
      gradientFrom: "#0c0c10",
      gradientTo: "#151518",
      orbs: [
        { color: "rgba(80, 70, 120, 0.25)",  x: "-5%", y: "-10%", size: "44%" },
        { color: "rgba(60, 60, 80, 0.20)",   x: "60%", y: "50%",  size: "42%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(34, 34, 40, 0.70)",
      "bg-elevated": "rgba(44, 44, 52, 0.75)",
      "bg-hover": "rgba(255, 255, 255, 0.05)",
      "bg-input": "rgba(28, 28, 34, 0.75)",
      "border-default": "rgba(255, 255, 255, 0.08)",
      "border-emphasis": "rgba(255, 255, 255, 0.15)",
      "text-primary": "#e8e8ec",
      "text-secondary": "#9898a0",
      "text-tertiary": "#858596",
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
      "badge-bg": "rgba(44, 44, 52, 0.75)",
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
    id: "twilight-grey",
    name: "Twilight",
    description: "Dusk sky glass with cool slate depth",
    order: 90,
    glass: {
      blur: "14px",
      saturate: "1.3",
      gradientFrom: "#161820",
      gradientTo: "#1e2230",
      orbs: [
        { color: "rgba(60, 70, 120, 0.30)",  x: "-5%", y: "-10%", size: "44%" },
        { color: "rgba(90, 70, 130, 0.25)",  x: "60%", y: "10%",  size: "40%" },
        { color: "rgba(70, 80, 100, 0.20)",  x: "15%", y: "55%",  size: "45%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(48, 52, 60, 0.55)",
      "bg-elevated": "rgba(58, 62, 72, 0.60)",
      "bg-hover": "rgba(255, 255, 255, 0.06)",
      "bg-input": "rgba(42, 46, 54, 0.65)",
      "border-default": "rgba(255, 255, 255, 0.10)",
      "border-emphasis": "rgba(255, 255, 255, 0.16)",
      "text-primary": "#f0f1f3",
      "text-secondary": "#b0b4bc",
      "text-tertiary": "#808590",
      "accent": "#7c8df0",
      "accent-hover": "#9aa6f8",
      "success": "#4ade80",
      "warning": "#fbbf24",
      "error": "#f87171",
      "info": "#60a5fa",
      "metric-integration": "#5b9cf0",
      "metric-frames": "#3ec974",
      "metric-hfr": "#f0b020",
      "metric-eccentricity": "#b47cf0",
      "metric-fwhm": "#38b0e8",
      "metric-stars": "#28c4a8",
      "metric-guiding": "#f07080",
      "metric-temp": "#38b0e8",
      "metric-gain": "#6ee09c",
      "metric-time": "#f09898",
      "metric-best": "#4ade80",
      "metric-worst": "#f87171",
      "badge-bg": "rgba(58, 62, 72, 0.60)",
      "badge-text": "#dcdee2",
      "filter-ha": "#d84848",
      "filter-oiii": "#4090d8",
      "filter-sii": "#d8a840",
      "filter-l": "#d0d0d0",
      "filter-r": "#d85050",
      "filter-g": "#50b050",
      "filter-b": "#5878d8",
    },
  },
  {
    id: "silver-mist",
    name: "Silver Mist",
    description: "Luminous frosted chrome with soft blue accent",
    order: 100,
    glass: {
      blur: "14px",
      saturate: "1.2",
      gradientFrom: "#1a1e28",
      gradientTo: "#242836",
      orbs: [
        { color: "rgba(80, 100, 150, 0.30)",  x: "-5%", y: "-10%", size: "44%" },
        { color: "rgba(100, 110, 140, 0.25)", x: "60%", y: "50%",  size: "42%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(60, 66, 80, 0.50)",
      "bg-elevated": "rgba(72, 78, 92, 0.55)",
      "bg-hover": "rgba(255, 255, 255, 0.07)",
      "bg-input": "rgba(52, 56, 68, 0.60)",
      "border-default": "rgba(255, 255, 255, 0.12)",
      "border-emphasis": "rgba(255, 255, 255, 0.18)",
      "text-primary": "#f2f3f5",
      "text-secondary": "#bcc0ca",
      "text-tertiary": "#8c92a0",
      "accent": "#6ea8dc",
      "accent-hover": "#90c0ec",
      "success": "#50d880",
      "warning": "#f0b830",
      "error": "#e86060",
      "info": "#6ea8dc",
      "metric-integration": "#6ea8dc",
      "metric-frames": "#50d880",
      "metric-hfr": "#f0b830",
      "metric-eccentricity": "#b080e0",
      "metric-fwhm": "#40b8e0",
      "metric-stars": "#30c8b0",
      "metric-guiding": "#e07080",
      "metric-temp": "#40b8e0",
      "metric-gain": "#70e098",
      "metric-time": "#e89898",
      "metric-best": "#50d880",
      "metric-worst": "#e86060",
      "badge-bg": "rgba(72, 78, 92, 0.55)",
      "badge-text": "#e0e2e8",
      "filter-ha": "#d04848",
      "filter-oiii": "#4088d0",
      "filter-sii": "#d0a038",
      "filter-l": "#c8c8c8",
      "filter-r": "#d04848",
      "filter-g": "#48a848",
      "filter-b": "#5070d0",
    },
  },
  {
    id: "daylight",
    name: "Daylight",
    description: "Clean light theme for daytime use",
    order: 110,
    tokens: {
      "bg-base": "#f4f5f7",
      "bg-surface": "#ffffff",
      "bg-elevated": "#e8eaee",
      "bg-hover": "#eceef2",
      "bg-input": "#ffffff",
      "border-default": "#d0d4dc",
      "border-emphasis": "#b8bcc8",
      "text-primary": "#1a1c20",
      "text-secondary": "#4a5060",
      "text-tertiary": "#788098",
      "accent": "#4f6ae8",
      "accent-hover": "#3a56d8",
      "success": "#18a050",
      "warning": "#c08800",
      "error": "#d03838",
      "info": "#2878d0",
      "metric-integration": "#2878d0",
      "metric-frames": "#18a050",
      "metric-hfr": "#c08800",
      "metric-eccentricity": "#8050c0",
      "metric-fwhm": "#1890c0",
      "metric-stars": "#18a088",
      "metric-guiding": "#c83850",
      "metric-temp": "#1890c0",
      "metric-gain": "#20a860",
      "metric-time": "#c05050",
      "metric-best": "#18a050",
      "metric-worst": "#d03838",
      "badge-bg": "#e4e6ec",
      "badge-text": "#2a2e38",
      "filter-ha": "#c03030",
      "filter-oiii": "#2870c0",
      "filter-sii": "#b89020",
      "filter-l": "#606060",
      "filter-r": "#c03838",
      "filter-g": "#308030",
      "filter-b": "#3858c0",
    },
  },
  {
    id: "glass-crystal",
    name: "Crystal",
    description: "Light frosted glass with soft blue-white warmth",
    order: 115,
    glass: {
      blur: "16px",
      saturate: "1.3",
      gradientFrom: "#e8ecf4",
      gradientTo: "#dce4f0",
      orbs: [
        { color: "rgba(100, 140, 220, 0.20)", x: "-5%", y: "-10%", size: "45%" },
        { color: "rgba(140, 120, 200, 0.15)", x: "60%", y: "10%",  size: "40%" },
        { color: "rgba(200, 140, 160, 0.10)", x: "15%", y: "55%",  size: "45%" },
      ],
    },
    tokens: {
      "bg-base": "transparent",
      "bg-surface": "rgba(255, 255, 255, 0.60)",
      "bg-elevated": "rgba(255, 255, 255, 0.50)",
      "bg-hover": "rgba(0, 0, 0, 0.04)",
      "bg-input": "rgba(255, 255, 255, 0.70)",
      "border-default": "rgba(0, 0, 0, 0.08)",
      "border-emphasis": "rgba(0, 0, 0, 0.14)",
      "text-primary": "#1a1c20",
      "text-secondary": "#4a5060",
      "text-tertiary": "#788098",
      "accent": "#4f6ae8",
      "accent-hover": "#3a56d8",
      "success": "#18a050",
      "warning": "#c08800",
      "error": "#d03838",
      "info": "#2878d0",
      "metric-integration": "#2878d0",
      "metric-frames": "#18a050",
      "metric-hfr": "#c08800",
      "metric-eccentricity": "#8050c0",
      "metric-fwhm": "#1890c0",
      "metric-stars": "#18a088",
      "metric-guiding": "#c83850",
      "metric-temp": "#1890c0",
      "metric-gain": "#20a860",
      "metric-time": "#c05050",
      "metric-best": "#18a050",
      "metric-worst": "#d03838",
      "badge-bg": "rgba(255, 255, 255, 0.55)",
      "badge-text": "#2a2e38",
      "filter-ha": "#c03030",
      "filter-oiii": "#2870c0",
      "filter-sii": "#b89020",
      "filter-l": "#606060",
      "filter-r": "#c03838",
      "filter-g": "#308030",
      "filter-b": "#3858c0",
    },
  },
];

export const THEMES_SORTED = [...THEMES].sort((a, b) => a.order - b.order);

export const DEFAULT_THEME_ID = "glass-void";

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

export const DEFAULT_TEXT_SIZE = "large";

export function getThemeById(id: string): ThemeMeta {
  return THEMES.find((t) => t.id === id) ?? THEMES[0];
}

const GLASS_ORBS_ID = "gl-glass-orbs";

function applyGlassOrbs(orbs: GlassOrb[] | undefined, lightTheme = false): void {
  const existing = document.getElementById(GLASS_ORBS_ID);
  if (!orbs || orbs.length === 0) {
    existing?.remove();
    return;
  }
  const container = existing ?? document.createElement("div");
  container.id = GLASS_ORBS_ID;
  container.innerHTML = "";
  Object.assign(container.style, {
    position: "fixed",
    inset: "0",
    overflow: "hidden",
    pointerEvents: "none",
    zIndex: "0",
  });
  for (const orb of orbs) {
    const el = document.createElement("div");
    Object.assign(el.style, {
      position: "absolute",
      left: orb.x,
      top: orb.y,
      width: orb.size,
      height: orb.size,
      background: orb.color,
      borderRadius: "50%",
      filter: "blur(120px)",
      mixBlendMode: lightTheme ? "multiply" : "screen",
    });
    container.appendChild(el);
  }
  if (!existing) {
    document.body.prepend(container);
  }
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
    const isLight = theme.id === "glass-crystal" || theme.id === "daylight";
    root.setAttribute("data-theme-lightness", isLight ? "light" : "dark");
    applyGlassOrbs(theme.glass.orbs, isLight);
  } else {
    root.style.setProperty("--glass-blur", "0px");
    root.style.setProperty("--glass-saturate", "1");
    root.style.removeProperty("--glass-gradient-from");
    root.style.removeProperty("--glass-gradient-to");
    root.setAttribute("data-theme-style", "solid");
    const isLight = theme.id === "daylight";
    root.setAttribute("data-theme-lightness", isLight ? "light" : "dark");
    applyGlassOrbs(undefined);
  }
}

export function applyTextSize(sizeId: string): void {
  const preset = TEXT_SIZES.find((s) => s.id === sizeId) ?? TEXT_SIZES[1];
  document.documentElement.style.fontSize = preset.fontSize;
}
