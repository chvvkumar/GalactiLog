# Glassmorphic Theme Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert all solid themes to glassmorphic designs and add a new Crystal light glass theme.

**Architecture:** All theme definitions live in `frontend/src/themes.ts`. Each solid theme gets a `glass` config and rgba token adjustments. Crystal (light glass) additionally requires a CSS override in `frontend/src/index.css` and a `data-theme-lightness` attribute in the `applyTheme()` function.

**Tech Stack:** SolidJS, TypeScript, Tailwind CSS v4, CSS custom properties

**Spec:** `guides/superpowers/specs/2026-04-12-glassmorphic-theme-conversion-design.md`

---

## File Map

- **Modify:** `frontend/src/themes.ts` -- add `glass` configs to 7 solid themes, add Crystal theme, update `applyTheme()` for lightness attribute
- **Modify:** `frontend/src/index.css` -- add light-glass CSS overrides for Crystal theme

---

## Task 1: Convert Default Dark theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts:250-294` (the `default-dark` theme object)

- [ ] **Step 1: Add glass config and update tokens for Default Dark**

Replace the entire `default-dark` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Default Dark theme to glassmorphic"
```

---

## Task 2: Convert Deep Neutral theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `deep-neutral` theme object)

- [ ] **Step 1: Add glass config and update tokens for Deep Neutral**

Replace the entire `deep-neutral` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Deep Neutral theme to glassmorphic"
```

---

## Task 3: Convert Slate Blue theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `slate-blue` theme object)

- [ ] **Step 1: Add glass config and update tokens for Slate Blue**

Replace the entire `slate-blue` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Slate Blue theme to glassmorphic"
```

---

## Task 4: Convert Warm Stone theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `warm-stone` theme object)

- [ ] **Step 1: Add glass config and update tokens for Warm Stone**

Replace the entire `warm-stone` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Warm Stone theme to glassmorphic"
```

---

## Task 5: Convert Soft Zinc theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `soft-zinc` theme object)

- [ ] **Step 1: Add glass config and update tokens for Soft Zinc**

Replace the entire `soft-zinc` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Soft Zinc theme to glassmorphic"
```

---

## Task 6: Convert Twilight theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `twilight-grey` theme object)

- [ ] **Step 1: Add glass config and update tokens for Twilight**

Replace the entire `twilight-grey` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Twilight theme to glassmorphic"
```

---

## Task 7: Convert Silver Mist theme to glassmorphic

**Files:**
- Modify: `frontend/src/themes.ts` (the `silver-mist` theme object)

- [ ] **Step 1: Add glass config and update tokens for Silver Mist**

Replace the entire `silver-mist` theme object with:

```typescript
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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/themes.ts
git commit -m "Convert Silver Mist theme to glassmorphic"
```

---

## Task 8: Add Crystal light glass theme and CSS overrides

**Files:**
- Modify: `frontend/src/themes.ts` -- add Crystal theme entry, update `applyTheme()` for lightness
- Modify: `frontend/src/index.css` -- add light-glass CSS overrides

This task has dependencies between the two files so it must be done sequentially.

- [ ] **Step 1: Add Crystal theme to THEMES array in themes.ts**

Add the following theme object after the `daylight` entry (before the closing `];` of the THEMES array):

```typescript
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
```

- [ ] **Step 2: Update applyTheme() to set data-theme-lightness attribute**

In the `applyTheme()` function, after the line `root.setAttribute("data-theme-style", "glass");` (inside the `if (theme.glass)` block), add a lightness attribute. The full updated `if (theme.glass)` block should be:

```typescript
  if (theme.glass) {
    root.style.setProperty("--glass-blur", theme.glass.blur);
    root.style.setProperty("--glass-saturate", theme.glass.saturate);
    root.style.setProperty("--glass-gradient-from", theme.glass.gradientFrom);
    root.style.setProperty("--glass-gradient-to", theme.glass.gradientTo);
    root.setAttribute("data-theme-style", "glass");
    const isLight = theme.id === "glass-crystal" || theme.id === "daylight";
    root.setAttribute("data-theme-lightness", isLight ? "light" : "dark");
    applyGlassOrbs(theme.glass.orbs);
  } else {
    root.style.setProperty("--glass-blur", "0px");
    root.style.setProperty("--glass-saturate", "1");
    root.style.removeProperty("--glass-gradient-from");
    root.style.removeProperty("--glass-gradient-to");
    root.setAttribute("data-theme-style", "solid");
    const isLight = theme.id === "glass-crystal" || theme.id === "daylight";
    root.setAttribute("data-theme-lightness", isLight ? "light" : "dark");
    applyGlassOrbs(undefined);
  }
```

- [ ] **Step 3: Update glass orb blend mode for light themes**

In the `applyGlassOrbs()` function, the orbs currently use `mixBlendMode: "screen"` which works for dark backgrounds but washes out on light backgrounds. Update the orb creation loop to accept whether the theme is light. 

Change the `applyGlassOrbs` function signature and the orb blend mode:

```typescript
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
```

Then update both call sites in `applyTheme()`:

In the glass branch: `applyGlassOrbs(theme.glass.orbs, theme.id === "glass-crystal");`
In the else branch: `applyGlassOrbs(undefined);` (unchanged)

- [ ] **Step 4: Add light-glass CSS overrides to index.css**

Add the following CSS after the existing `[data-theme-style="glass"] .bg-theme-input` rule (after line 170):

```css
/* Light glass themes: invert edge highlights and shadows */
[data-theme-lightness="light"][data-theme-style="glass"] .bg-theme-surface,
[data-theme-lightness="light"][data-theme-style="glass"] .bg-theme-elevated {
  border-color: rgba(255, 255, 255, 0.50);
  box-shadow:
    inset 0 1px 0 0 rgba(255, 255, 255, 0.60),
    0 8px 32px rgba(0, 0, 0, 0.06);
}

[data-theme-lightness="light"][data-theme-style="glass"] .glass-popover {
  background: color-mix(in srgb, var(--glass-gradient-from) 85%, transparent);
  border-color: rgba(255, 255, 255, 0.50);
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/themes.ts frontend/src/index.css
git commit -m "Add Crystal light glass theme with CSS overrides"
```

---

## Task 9: Update CSS fallback variables in index.css

**Files:**
- Modify: `frontend/src/index.css:8-50` (the `:root` fallback block)

Since Deep Neutral is now glassmorphic, the CSS fallback variables (which match Deep Neutral) should be updated to use its new rgba values so the page renders correctly before JS executes. However, rgba values with transparency on bg-base won't work without the glass gradient background, so the fallbacks should stay as solid colors (the current values are fine as-is since they provide a visible fallback regardless of theme).

- [ ] **Step 1: No changes needed**

The existing `:root` fallback values are solid hex colors that render correctly before `applyTheme()` runs. Glass-specific effects (backdrop-filter, orbs, gradient) only activate after JS loads. No CSS changes needed.

- [ ] **Step 2: Final full TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit any remaining changes**

If no changes were made, skip this step.

---

## Task 10: Visual verification of all themes

**Files:** None (testing only)

- [ ] **Step 1: Start the frontend dev server**

Run: `cd frontend && npm run dev`
Expected: Dev server starts on port 3000

- [ ] **Step 2: Test each converted theme visually**

Open the app in a browser. Navigate to Settings > Display. Switch through each theme and verify:

1. Glass gradient background renders (not solid black/white)
2. Glass orbs are visible as soft color blobs behind content
3. Panels have frosted glass effect (backdrop-filter blur visible)
4. Text is readable on all surfaces
5. Borders show subtle glass edge highlights
6. Input fields have reduced blur effect
7. Popovers/dropdowns render with glass effect
8. Badge backgrounds are semi-transparent

Themes to check:
- Dark (violet depth)
- Deep Neutral (near-opaque graphite)
- Slate Blue (oceanic blue)
- Warm Stone (amber warmth)
- Soft Zinc (studio matte)
- Twilight (dusk sky)
- Silver Mist (bright chrome)
- Crystal (light frosted -- white panels, light gradient, dark text)
- Daylight stays solid (no glass effects)
- Existing glass themes (Nebula Cyan, Deep Space, Void) unchanged

- [ ] **Step 3: Commit any visual fixes**

If adjustments are needed (opacity, blur, orb placement), make them and commit:

```bash
git add frontend/src/themes.ts frontend/src/index.css
git commit -m "Adjust theme values after visual testing"
```
