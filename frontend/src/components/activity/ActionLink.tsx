import { Show, type Component } from "solid-js";
import { A } from "@solidjs/router";
import { buttonClasses } from "../ui/Button";
import type { ActivityEvent } from "../../api/types";

export interface ActivityAction {
  label: string;
  href: string;
}

/**
 * `details.action` from the activity contract: `{label, href}` where href is
 * an in-app relative path. The generated schema types `details` as an open
 * record, so the shape is narrowed here rather than by the API types.
 */
export function eventAction(event: {
  details?: Record<string, unknown> | null;
}): ActivityAction | null {
  const action = event.details?.action as ActivityAction | undefined;
  if (!action || typeof action !== "object") return null;
  if (typeof action.label !== "string" || action.label === "") return null;
  // In-app paths only. `//host` is protocol-relative and `javascript:`/`data:`
  // URLs would execute, so anything not starting with a single "/" is dropped.
  const { href } = action;
  if (typeof href !== "string" || !href.startsWith("/") || href.startsWith("//")) return null;
  return action;
}

/** Renders the event's action as a router link, or nothing when absent. */
const ActivityActionLink: Component<{
  event: ActivityEvent;
  class?: string;
  onNavigate?: () => void;
}> = (props) => (
  <Show when={eventAction(props.event)}>
    {(action) => (
      <A
        href={action().href}
        class={buttonClasses(
          "secondary",
          "sm",
          `inline-block align-middle whitespace-nowrap ${props.class ?? ""}`,
        )}
        onClick={(e) => {
          e.stopPropagation();
          props.onNavigate?.();
        }}
      >
        {action().label}
      </A>
    )}
  </Show>
);

export default ActivityActionLink;
