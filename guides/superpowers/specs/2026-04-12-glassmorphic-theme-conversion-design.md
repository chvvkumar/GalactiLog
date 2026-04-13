# Glassmorphic Theme Conversion

Convert all solid themes to glassmorphic and add a new light glass theme (Crystal).

## Scope

**File modified:** `frontend/src/themes.ts` (single source of truth)

**Themes converted in-place (keep existing IDs):**

| Theme ID | Name | Strategy |
|---|---|---|
| `default-dark` | Dark | Redesign freely, violet-tinted dark glass |
| `deep-neutral` | Deep Neutral | Preserve identity, add minimal glass |
| `slate-blue` | Slate Blue | Redesign freely, oceanic dark glass |
| `warm-stone` | Warm Stone | Preserve identity, smoked amber glass |
| `soft-zinc` | Soft Zinc | Preserve identity, studio matte glass |
| `twilight-grey` | Twilight | Preserve identity, dusk sky glass |
| `silver-mist` | Silver Mist | Redesign freely, luminous smoke glass |

**New theme added:**

| Theme ID | Name | Strategy |
|---|---|---|
| `glass-crystal` | Crystal | New light glassmorphic (order 115) |

**Unchanged:**
- `glass-nebula-cyan`, `glass-deep-space`, `glass-void` (already glassmorphic)
- `daylight` (kept as sole solid light theme)

## Conversion Rules

Each converted theme receives:
1. A `glass` config object (blur, saturate, gradientFrom, gradientTo, orbs)
2. Token adjustments: `bg-base` becomes `transparent`, surface/elevated/hover/input tokens get rgba with alpha for translucency
3. Border tokens switch to rgba white (dark themes) or rgba black (light theme) for glass edge rendering
4. Badge tokens get rgba with appropriate alpha

All other tokens (text, accent, semantic, metric, filter colors) stay the same unless readability requires adjustment.

## Theme Specifications

### Default Dark (Redesign)

Personality: refined premium dark mode with subtle violet warmth.

Glass config:
- blur: 16px
- saturate: 1.4
- gradientFrom: #08080f
- gradientTo: #12101e
- orbs:
  - muted violet: rgba(100, 80, 200, 0.30), x: -8%, y: -5%, size: 45%
  - deep blue: rgba(30, 40, 100, 0.25), x: 65%, y: 15%, size: 38%
  - subtle magenta: rgba(120, 40, 100, 0.20), x: 20%, y: 60%, size: 42%

Token changes:
- bg-base: transparent
- bg-surface: rgba(20, 20, 28, 0.40)
- bg-elevated: rgba(32, 30, 42, 0.45)
- bg-hover: rgba(255, 255, 255, 0.06)
- bg-input: rgba(16, 16, 22, 0.55)
- border-default: rgba(255, 255, 255, 0.10)
- border-emphasis: rgba(255, 255, 255, 0.16)
- badge-bg: rgba(32, 30, 42, 0.55)
- badge-text: #d1d5db (unchanged)

All other tokens (text, accent #818cf8, semantic, metric, filter) unchanged.

### Deep Neutral (Preserve)

Personality: monochrome darkroom, glass effect is felt more than seen.

Glass config:
- blur: 10px
- saturate: 1.0
- gradientFrom: #0a0a0a
- gradientTo: #141414
- orbs:
  - neutral grey: rgba(80, 80, 80, 0.25), x: -5%, y: -10%, size: 45%
  - warm grey: rgba(90, 85, 75, 0.20), x: 60%, y: 50%, size: 42%

Token changes:
- bg-base: transparent
- bg-surface: rgba(26, 26, 26, 0.75)
- bg-elevated: rgba(36, 36, 36, 0.80)
- bg-hover: rgba(255, 255, 255, 0.05)
- bg-input: rgba(22, 22, 22, 0.80)
- border-default: rgba(255, 255, 255, 0.08)
- border-emphasis: rgba(255, 255, 255, 0.14)
- badge-bg: rgba(36, 36, 36, 0.80)
- badge-text: #d4d4d4 (unchanged)

All other tokens unchanged.

### Slate Blue (Redesign)

Personality: deep ocean atmosphere, rich blue depth.

Glass config:
- blur: 18px
- saturate: 1.5
- gradientFrom: #060d1a
- gradientTo: #0c1830
- orbs:
  - steel blue: rgba(40, 70, 140, 0.35), x: -5%, y: -10%, size: 44%
  - teal-blue: rgba(20, 60, 100, 0.25), x: 60%, y: 10%, size: 38%
  - slate-indigo: rgba(50, 45, 120, 0.30), x: 15%, y: 55%, size: 46%

Token changes:
- bg-base: transparent
- bg-surface: rgba(16, 26, 48, 0.32)
- bg-elevated: rgba(24, 36, 60, 0.38)
- bg-hover: rgba(255, 255, 255, 0.06)
- bg-input: rgba(12, 20, 40, 0.55)
- border-default: rgba(130, 170, 255, 0.10)
- border-emphasis: rgba(130, 170, 255, 0.18)
- badge-bg: rgba(24, 36, 60, 0.55)
- badge-text: #d1d8e5 (unchanged)

All other tokens unchanged.

### Warm Stone (Preserve)

Personality: campfire warmth behind frosted glass.

Glass config:
- blur: 12px
- saturate: 1.2
- gradientFrom: #0e0c08
- gradientTo: #181410
- orbs:
  - amber-brown: rgba(140, 100, 40, 0.30), x: -5%, y: -10%, size: 44%
  - muted sienna: rgba(120, 70, 40, 0.25), x: 60%, y: 15%, size: 40%
  - faint olive: rgba(80, 90, 40, 0.20), x: 15%, y: 58%, size: 45%

Token changes:
- bg-base: transparent
- bg-surface: rgba(36, 32, 24, 0.65)
- bg-elevated: rgba(48, 43, 34, 0.70)
- bg-hover: rgba(255, 255, 255, 0.05)
- bg-input: rgba(30, 27, 22, 0.75)
- border-default: rgba(255, 240, 200, 0.10)
- border-emphasis: rgba(255, 240, 200, 0.16)
- badge-bg: rgba(48, 43, 34, 0.70)
- badge-text: #d4cec4 (unchanged)

All other tokens unchanged.

### Soft Zinc (Preserve)

Personality: recording studio behind frosted panels, restrained and precise.

Glass config:
- blur: 12px
- saturate: 1.1
- gradientFrom: #0c0c10
- gradientTo: #151518
- orbs:
  - zinc-violet: rgba(80, 70, 120, 0.25), x: -5%, y: -10%, size: 44%
  - cool grey: rgba(60, 60, 80, 0.20), x: 60%, y: 50%, size: 42%

Token changes:
- bg-base: transparent
- bg-surface: rgba(34, 34, 40, 0.70)
- bg-elevated: rgba(44, 44, 52, 0.75)
- bg-hover: rgba(255, 255, 255, 0.05)
- bg-input: rgba(28, 28, 34, 0.75)
- border-default: rgba(255, 255, 255, 0.08)
- border-emphasis: rgba(255, 255, 255, 0.15)
- badge-bg: rgba(44, 44, 52, 0.75)
- badge-text: #d1d5db (unchanged)

All other tokens unchanged.

### Twilight (Preserve)

Personality: dusk sky through glass, gentle color.

Glass config:
- blur: 14px
- saturate: 1.3
- gradientFrom: #161820
- gradientTo: #1e2230
- orbs:
  - cool slate-blue: rgba(60, 70, 120, 0.30), x: -5%, y: -10%, size: 44%
  - muted lavender: rgba(90, 70, 130, 0.25), x: 60%, y: 10%, size: 40%
  - steel: rgba(70, 80, 100, 0.20), x: 15%, y: 55%, size: 45%

Token changes:
- bg-base: transparent
- bg-surface: rgba(48, 52, 60, 0.55)
- bg-elevated: rgba(58, 62, 72, 0.60)
- bg-hover: rgba(255, 255, 255, 0.06)
- bg-input: rgba(42, 46, 54, 0.65)
- border-default: rgba(255, 255, 255, 0.10)
- border-emphasis: rgba(255, 255, 255, 0.16)
- badge-bg: rgba(58, 62, 72, 0.60)
- badge-text: #dcdee2 (unchanged)

All other tokens unchanged.

### Silver Mist (Redesign)

Personality: luminous frosted chrome, bright for a dark glass, airy.

Glass config:
- blur: 14px
- saturate: 1.2
- gradientFrom: #1a1e28
- gradientTo: #242836
- orbs:
  - cool grey-blue: rgba(80, 100, 150, 0.30), x: -5%, y: -10%, size: 44%
  - silver-slate: rgba(100, 110, 140, 0.25), x: 60%, y: 50%, size: 42%

Token changes:
- bg-base: transparent
- bg-surface: rgba(60, 66, 80, 0.50)
- bg-elevated: rgba(72, 78, 92, 0.55)
- bg-hover: rgba(255, 255, 255, 0.07)
- bg-input: rgba(52, 56, 68, 0.60)
- border-default: rgba(255, 255, 255, 0.12)
- border-emphasis: rgba(255, 255, 255, 0.18)
- badge-bg: rgba(72, 78, 92, 0.55)
- badge-text: #e0e2e8 (unchanged)

All other tokens unchanged.

### Crystal (New Light Glass)

Personality: morning frost, clean bright glass.

Theme metadata:
- id: glass-crystal
- name: Crystal
- description: Light frosted glass with soft blue-white warmth
- order: 115

Glass config:
- blur: 16px
- saturate: 1.3
- gradientFrom: #e8ecf4
- gradientTo: #dce4f0
- orbs:
  - pale blue: rgba(100, 140, 220, 0.20), x: -5%, y: -10%, size: 45%
  - light lavender: rgba(140, 120, 200, 0.15), x: 60%, y: 10%, size: 40%
  - faint rose: rgba(200, 140, 160, 0.10), x: 15%, y: 55%, size: 45%

Tokens (full set, based on Daylight palette adjusted for glass):
- bg-base: transparent
- bg-surface: rgba(255, 255, 255, 0.60)
- bg-elevated: rgba(255, 255, 255, 0.50)
- bg-hover: rgba(0, 0, 0, 0.04)
- bg-input: rgba(255, 255, 255, 0.70)
- border-default: rgba(0, 0, 0, 0.08)
- border-emphasis: rgba(0, 0, 0, 0.14)
- text-primary: #1a1c20
- text-secondary: #4a5060
- text-tertiary: #788098
- accent: #4f6ae8
- accent-hover: #3a56d8
- success: #18a050
- warning: #c08800
- error: #d03838
- info: #2878d0
- All metric tokens: same as Daylight
- All filter tokens: same as Daylight
- badge-bg: rgba(255, 255, 255, 0.55)
- badge-text: #2a2e38

## CSS Considerations

The existing `[data-theme-style="glass"]` selectors use white-on-dark assumptions for `border-color` and `box-shadow`. Crystal is a light glass theme, so the CSS in `index.css` may need a light-glass override:

```css
[data-theme-style="glass"][data-theme-lightness="light"] .bg-theme-surface,
[data-theme-style="glass"][data-theme-lightness="light"] .bg-theme-elevated {
  box-shadow:
    inset 0 1px 0 0 rgba(255, 255, 255, 0.40),
    0 8px 32px rgba(0, 0, 0, 0.08);
}
```

This requires setting `data-theme-lightness="light"` in `applyTheme()` for Crystal. Implementation detail to be finalized in the plan.

Alternative: since Crystal's border/shadow tokens are already set via CSS custom properties, the existing glass selectors may produce acceptable results without a lightness attribute. This should be verified visually during implementation.

## Ordering

Final theme list order:
1. Nebula Cyan (10)
2. Deep Space (20)
3. Void (30)
4. Dark (40)
5. Deep Neutral (50)
6. Slate Blue (60)
7. Warm Stone (70)
8. Soft Zinc (80)
9. Twilight (90)
10. Silver Mist (100)
11. Daylight (110)
12. Crystal (115)

## Out of Scope

- No changes to `index.css` glass selectors (unless Crystal requires it)
- No changes to `SettingsProvider.tsx`, `DisplayTab.tsx`, or `tailwind.config.js`
- No changes to filter badge glass styles in `filterStyles.ts`
- Metric, filter, semantic, and text tokens stay the same per theme (unless readability requires adjustment during implementation)
