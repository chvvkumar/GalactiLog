import { splitProps, type JSX } from "solid-js";

export type IconButtonVariant = "default" | "danger";

const BASE = "text-theme-text-tertiary transition-colors";

const VARIANT: Record<IconButtonVariant, string> = {
  default: "hover:text-theme-text-primary",
  danger: "hover:text-theme-error",
};

/** Pure class-string builder for the borderless icon button. */
export function iconButtonClasses(
  variant: IconButtonVariant = "default",
  extra?: string,
): string {
  return [BASE, VARIANT[variant], extra].filter(Boolean).join(" ");
}

interface Props extends JSX.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: IconButtonVariant;
  class?: string;
}

export default function IconButton(props: Props) {
  const [local, rest] = splitProps(props, ["variant", "class", "type"]);
  return (
    <button
      type={local.type ?? "button"}
      {...rest}
      class={iconButtonClasses(local.variant ?? "default", local.class)}
    />
  );
}
