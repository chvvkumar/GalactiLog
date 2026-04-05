import type { DisplaySettings, ColumnVisibility } from "../types";

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

export function isColumnVisible(
  visibility: ColumnVisibility | undefined,
  table: keyof ColumnVisibility,
  kind: "builtin" | "custom",
  key: string,
): boolean {
  if (!visibility) return true; // default: all visible
  const tableVis = visibility[table];
  if (!tableVis) return true;
  const section = tableVis[kind];
  if (!section || !(key in section)) return true; // default visible if not set
  return section[key];
}
