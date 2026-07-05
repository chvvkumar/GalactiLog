import { Show, type Component, type JSX } from "solid-js";

interface CollapsibleHeaderProps {
  title: string;
  expanded: () => boolean;
  onToggle: () => void;
  // Rendered inside the title, after the title text (e.g. a count or "has content" badge).
  suffix?: JSX.Element;
  // Rendered between the title and the chevron (e.g. a "Saving..." indicator).
  trailing?: JSX.Element;
}

// Collapsible section header: an uppercase title with an accent rule and a
// chevron that flips when expanded. Used for the several expandable panels
// on the target detail page (Merge History, Sky View, Notes, Graphs).
const CollapsibleHeader: Component<CollapsibleHeaderProps> = (props) => {
  return (
    <button class="flex items-center gap-2 py-2 cursor-pointer group" onClick={props.onToggle}>
      <h3 class="text-xs font-semibold uppercase tracking-wider text-theme-text-secondary border-l-2 border-theme-accent pl-2 group-hover:text-theme-text-primary transition-colors">
        {props.title}
        {props.suffix}
      </h3>
      <Show when={props.trailing}>
        <div class="flex items-center gap-2">
          {props.trailing}
        </div>
      </Show>
      <svg
        class={`w-3.5 h-3.5 transition-transform duration-200 text-theme-text-tertiary ${props.expanded() ? "rotate-180" : ""}`}
        viewBox="0 0 20 20"
        fill="currentColor"
      >
        <path
          fill-rule="evenodd"
          d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
          clip-rule="evenodd"
        />
      </svg>
    </button>
  );
};

export default CollapsibleHeader;
