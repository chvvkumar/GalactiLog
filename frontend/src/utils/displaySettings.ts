import type { DisplaySettings } from "../types";

export function isFieldVisible(
  display: DisplaySettings | undefined,
  group: keyof DisplaySettings,
  field: string
): boolean {
  if (!display) {
    return group === "quality" || group === "guiding";
  }
  const g = display[group];
  if (!g) return false;
  return g.enabled && (g.fields[field] ?? true);
}
