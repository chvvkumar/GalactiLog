import { createSignal, type JSX, type Component } from "solid-js";

interface SettingsHelpSectionProps {
  tabId: string;
  children: JSX.Element;
}

const SettingsHelpSection: Component<SettingsHelpSectionProps> = (props) => {
  const storageKey = () => `settings_help_${props.tabId}`;

  const getInitial = (): boolean => {
    try {
      return localStorage.getItem(`settings_help_${props.tabId}`) === "true";
    } catch {
      return false;
    }
  };

  const [expanded, setExpanded] = createSignal(getInitial());

  const isExpanded = () => expanded();

  const toggle = () => {
    const next = !isExpanded();
    setExpanded(next);
    try {
      localStorage.setItem(storageKey(), String(next));
    } catch {
      // localStorage unavailable
    }
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)]">
      <button
        type="button"
        onClick={toggle}
        class="w-full flex items-center gap-2 p-4 text-left cursor-pointer select-none"
      >
        {/* Info icon */}
        <svg
          class="w-5 h-5 flex-shrink-0 text-theme-text-secondary"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fill-rule="evenodd"
            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
            clip-rule="evenodd"
          />
        </svg>

        <span class="text-sm font-medium text-theme-text-secondary flex-1">
          About this section
        </span>

        {/* Chevron */}
        <svg
          class={`w-4 h-4 text-theme-text-secondary transition-transform duration-200 ${
            isExpanded() ? "rotate-180" : ""
          }`}
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

      <div
        class={`grid transition-[grid-template-rows] duration-200 ${
          isExpanded() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div class="overflow-hidden">
          <div class="px-4 pb-4 space-y-2">
            {props.children}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsHelpSection;
