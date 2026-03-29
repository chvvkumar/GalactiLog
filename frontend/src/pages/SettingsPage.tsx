// frontend/src/pages/SettingsPage.tsx
import { Show, type Component } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { GeneralTab } from "../components/settings/GeneralTab";
import { FiltersTab } from "../components/settings/FiltersTab";
import { EquipmentTab } from "../components/settings/EquipmentTab";
import { MergesTab } from "../components/settings/MergesTab";
import ScanManager from "../components/ScanManager";
import DisplayTab from "../components/DisplayTab";

const TABS = [
  { id: "general", label: "General" },
  { id: "scan", label: "Scan & Ingest" },
  { id: "filters", label: "Filters" },
  { id: "equipment", label: "Equipment" },
  { id: "display", label: "Display" },
  { id: "merges", label: "Target Merges" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export const SettingsPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = () => (TABS.some((t) => t.id === searchParams.tab) ? (searchParams.tab as TabId) : "general");

  return (
    <div class="p-4 max-w-4xl mx-auto space-y-6">
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Settings</h1>

      {/* Tab bar */}
      <div class="flex gap-1">
        {TABS.map((tab) => (
          <button
            onClick={() => setSearchParams({ tab: tab.id })}
            class={`px-4 py-2 text-sm transition-colors duration-150 ${
              activeTab() === tab.id
                ? "bg-theme-elevated text-theme-text-primary rounded-[var(--radius-sm)] font-medium"
                : "text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover rounded-[var(--radius-sm)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <Show when={activeTab() === "general"}>
        <GeneralTab />
      </Show>
      <Show when={activeTab() === "scan"}>
        <ScanManager />
      </Show>
      <Show when={activeTab() === "filters"}>
        <FiltersTab />
      </Show>
      <Show when={activeTab() === "equipment"}>
        <EquipmentTab />
      </Show>
      <Show when={activeTab() === "display"}>
        <DisplayTab />
      </Show>
      <Show when={activeTab() === "merges"}>
        <MergesTab />
      </Show>
    </div>
  );
};
