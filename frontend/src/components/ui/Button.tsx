import { splitProps, type JSX } from "solid-js";

export type ButtonVariant = "primary" | "secondary" | "danger" | "warning";
export type ButtonSize = "sm" | "md";

const BASE =
  "rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";

const SIZE: Record<ButtonSize, string> = {
  sm: "px-3 py-1",
  md: "px-4 py-1.5",
};

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-theme-accent/15 text-theme-accent border border-theme-accent/30 hover:bg-theme-accent/25",
  secondary:
    "bg-theme-surface text-theme-text-primary border border-theme-border hover:bg-theme-hover",
  danger:
    "bg-theme-error/15 text-theme-error border border-theme-error/30 hover:bg-theme-error/25",
  warning:
    "bg-theme-warning/15 text-theme-warning border border-theme-warning/30 hover:bg-theme-warning/25",
};

/**
 * Pure class-string builder for the button primitive. Exported so it can be
 * unit-tested without DOM rendering and borrowed by call sites that must remain
 * a native <button> (e.g. inside third-party wrappers).
 */
export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  extra?: string,
): string {
  return [BASE, SIZE[size], VARIANT[variant], extra].filter(Boolean).join(" ");
}

interface Props extends JSX.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  class?: string;
}

export default function Button(props: Props) {
  const [local, rest] = splitProps(props, ["variant", "size", "class", "type"]);
  return (
    <button
      type={local.type ?? "button"}
      {...rest}
      class={buttonClasses(local.variant ?? "primary", local.size ?? "md", local.class)}
    />
  );
}
