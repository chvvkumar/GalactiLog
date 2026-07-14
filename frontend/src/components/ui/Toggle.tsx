import { splitProps, type JSX } from "solid-js";

const BASE =
  "px-2 py-0.5 rounded text-caption font-medium border transition-colors cursor-pointer";

/**
 * Pure inline-style builder replicating MetricTogglePills' per-metric coloring.
 * Returns null when no color is supplied (caller uses accent token classes then).
 */
export function toggleStyle(
  active: boolean,
  color?: string,
): JSX.CSSProperties | null {
  if (!color) return null;
  // A 6-digit hex literal can take a direct alpha suffix (`#rrggbb22`), but
  // CSS variable strings like `var(--color-info)` cannot, so mix them instead.
  const isHex = /^#[0-9a-fA-F]{6}$/.test(color);
  const activeBg = isHex
    ? `${color}22`
    : `color-mix(in srgb, ${color} 13%, transparent)`;
  return {
    "border-color": active ? color : "var(--color-border-default)",
    "background-color": active ? activeBg : "var(--color-bg-elevated)",
    color: active ? color : "var(--color-text-tertiary)",
  };
}

/** Pure class-string builder for the toggle pill. */
export function toggleClasses(
  active: boolean,
  hasColor: boolean,
  extra?: string,
): string {
  let state = "";
  if (!hasColor) {
    state = active
      ? "border-theme-accent bg-theme-accent/20 text-theme-accent"
      : "border-theme-border bg-theme-elevated text-theme-text-tertiary hover:text-theme-text-primary";
  }
  return [BASE, state, extra].filter(Boolean).join(" ");
}

interface Props extends JSX.ButtonHTMLAttributes<HTMLButtonElement> {
  active: boolean;
  color?: string;
  class?: string;
}

export default function Toggle(props: Props) {
  const [local, rest] = splitProps(props, ["active", "color", "class", "type"]);
  return (
    <button
      type={local.type ?? "button"}
      {...rest}
      class={toggleClasses(local.active, !!local.color, local.class)}
      style={toggleStyle(local.active, local.color) ?? undefined}
    />
  );
}
