// frontend/src/pages/SettingsPage.tsx
import { Show, type Component } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { FiltersTab } from "../components/settings/FiltersTab";
import { EquipmentTab } from "../components/settings/EquipmentTab";
import { MergesTab } from "../components/settings/MergesTab";
import { MosaicsTab } from "../components/settings/MosaicsTab";
import { UsersTab } from "../components/settings/UsersTab";
import ScanManager from "../components/ScanManager";
import DisplayTab from "../components/DisplayTab";
import { useAuth } from "../components/AuthProvider";

const ALL_TABS = [
  { id: "scan", label: "Scan & Ingest" },
  { id: "filters", label: "Filters" },
  { id: "equipment", label: "Equipment" },
  { id: "display", label: "Display" },
  { id: "targets", label: "Target Management" },
  { id: "users", label: "Users", adminOnly: true },
] as const;

type TabId = (typeof ALL_TABS)[number]["id"];

const TargetManagementTab: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const subTab = () => (searchParams.sub === "mosaics" ? "mosaics" : "merges") as "merges" | "mosaics";

  return (
    <div class="space-y-4">
      <div class="flex gap-2">
        <button
          onClick={() => setSearchParams({ tab: "targets", sub: "merges" })}
          class={`px-3 py-1.5 text-sm rounded-[var(--radius-sm)] transition-colors ${
            subTab() === "merges"
              ? "bg-theme-elevated text-theme-text-primary font-medium"
              : "border border-theme-border text-theme-text-secondary hover:text-theme-text-primary"
          }`}
        >
          Merges
        </button>
        <button
          onClick={() => setSearchParams({ tab: "targets", sub: "mosaics" })}
          class={`px-3 py-1.5 text-sm rounded-[var(--radius-sm)] transition-colors ${
            subTab() === "mosaics"
              ? "bg-theme-elevated text-theme-text-primary font-medium"
              : "border border-theme-border text-theme-text-secondary hover:text-theme-text-primary"
          }`}
        >
          Mosaics
        </button>
      </div>
      <Show when={subTab() === "merges"}>
        <MergesTab />
      </Show>
      <Show when={subTab() === "mosaics"}>
        <MosaicsTab />
      </Show>
    </div>
  );
};

export const SettingsPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAdmin } = useAuth();

  const tabs = () => ALL_TABS.filter((t) => !("adminOnly" in t && t.adminOnly) || isAdmin());
  const activeTab = () => (tabs().some((t) => t.id === searchParams.tab) ? (searchParams.tab as TabId) : "scan");

  return (
    <div class={`p-4 mx-auto space-y-6 ${activeTab() === "targets" ? "max-w-6xl" : "max-w-4xl"}`}>
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Settings</h1>

      {/* Tab bar */}
      <div class="flex flex-wrap gap-1">
        {tabs().map((tab) => (
          <button
            onClick={() => setSearchParams({ tab: tab.id, sub: undefined })}
            class={`px-3 sm:px-4 py-2 text-sm transition-colors duration-150 ${
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
      <Show when={activeTab() === "targets"}>
        <TargetManagementTab />
      </Show>
      <Show when={activeTab() === "users" && isAdmin()}>
        <UsersTab />
      </Show>
    </div>
  );
};
