// frontend/src/pages/SettingsPage.tsx
import { Show, Suspense, lazy, type Component } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { useAuth } from "../components/AuthProvider";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import HelpPopover from "../components/HelpPopover";

const FiltersSectionHelp: Component = () => (
  <>
    <p class="text-sm text-theme-text-secondary">
      Filters represent the optical bandpass recorded for each exposure, for example Luminance, Red, H-alpha, or OIII.
    </p>
    <p class="text-sm text-theme-text-secondary">
      Capture software often writes the same filter under different names. Filter groups merge aliases such as "Ha" and "H-alpha" under a single canonical name, assign a display color, and keep dashboard and statistics output consistent across sessions.
    </p>
  </>
);

const EquipmentGroupingSectionHelp: Component = () => (
  <>
    <p class="text-sm text-theme-text-secondary">
      Groups telescopes and cameras that appear under different strings in FITS headers into one canonical name, for example "ASI2600MM Pro" and "ZWO ASI2600MM" collapsed into a single camera entry.
    </p>
    <p class="text-sm text-theme-text-secondary">
      Canonical names drive per-rig statistics and make dashboard output consistent even when capture software writes equipment names inconsistently across nights.
    </p>
  </>
);

const FiltersTab = lazy(() => import("../components/settings/FiltersTab").then(m => ({ default: m.FiltersTab })));
const EquipmentTab = lazy(() => import("../components/settings/EquipmentTab").then(m => ({ default: m.EquipmentTab })));
const TargetManagementTab = lazy(() => import("../components/settings/TargetManagementTab").then(m => ({ default: m.TargetManagementTab })));
const UsersTab = lazy(() => import("../components/settings/UsersTab").then(m => ({ default: m.UsersTab })));
const BackupRestoreTab = lazy(() => import("../components/settings/BackupRestoreTab").then(m => ({ default: m.BackupRestoreTab })));
const ScanManager = lazy(() => import("../components/ScanManager"));
const DisplayTab = lazy(() => import("../components/DisplayTab"));
const AstroBinTab = lazy(() => import("../components/settings/AstroBinTab"));
const CustomColumnsTab = lazy(() => import("../components/CustomColumnsTab"));
const ActivityLogTab = lazy(() => import("../components/settings/ActivityLogTab"));
const MetricsTab = lazy(() => import("../components/settings/MetricsTab").then(m => ({ default: m.MetricsTab })));

const ALL_TABS = [
  { id: "scan", label: "Library" },
  { id: "equipment", label: "Equipment" },
  { id: "display", label: "Display" },
  { id: "astrobin", label: "AstroBin & NINA" },
  { id: "targets", label: "Target Management" },
  { id: "custom-columns", label: "Custom Columns" },
  { id: "backup", label: "Backup & Restore", adminOnly: true },
  { id: "users", label: "Users", adminOnly: true },
  { id: "activity-log", label: "Activity Log", adminOnly: true },
  { id: "metrics", label: "Metrics", adminOnly: true },
] as const;

type TabId = (typeof ALL_TABS)[number]["id"];

export const SettingsPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAdmin } = useAuth();
  const ctx = useSettingsContext();

  const tabs = () => ALL_TABS.filter((t) => !("adminOnly" in t && t.adminOnly) || isAdmin());
  const activeTab = () => (tabs().some((t) => t.id === searchParams.tab) ? (searchParams.tab as TabId) : "scan");

  return (
    <div class={`page-enter p-4 space-y-6 ${contentWidthClass(ctx.contentWidth())}`}>
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Settings</h1>

      {/* Tab bar */}
      <div class="flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-1.5">
        <div class="flex flex-wrap gap-1 flex-1">
          {tabs().map((tab) => (
            <button
              onClick={() => setSearchParams({ tab: tab.id, sub: undefined })}
              class={`px-3 sm:px-4 py-1.5 text-sm rounded-[var(--radius-sm)] border transition-colors duration-150 ${
                activeTab() === tab.id
                  ? "bg-theme-elevated text-theme-text-primary font-medium border-theme-border-em shadow-sm"
                  : "text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover border-transparent"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <HelpPopover align="right" title="Settings">
          <p class="text-sm text-theme-text-secondary">
            Settings configure how GalactiLog catalogs and displays your FITS data. Each tab groups one area of configuration. Open the info icon next to any section title inside a tab for details on that section.
          </p>
          <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
            <li><strong class="text-theme-text-primary">Library</strong>: scan triggers, auto-scan schedule, observer location, path and name rules, maintenance actions.</li>
            <li><strong class="text-theme-text-primary">Equipment</strong>: filter and equipment canonical names and alias merging.</li>
            <li><strong class="text-theme-text-primary">Display</strong>: theme, text size, filter badge style, timezone, content width, preview cache, metric visibility.</li>
            <li><strong class="text-theme-text-primary">AstroBin & NINA</strong>: filter ID mapping, Bortle class, and NINA/Stellarium instance configuration for coordinate forwarding.</li>
            <li><strong class="text-theme-text-primary">Target Management</strong>: duplicate candidates, unresolved names, and maintenance actions.</li>
            <li><strong class="text-theme-text-primary">Custom Columns</strong>: user-defined columns on targets, sessions, and rigs.</li>
            <li><strong class="text-theme-text-primary">Backup & Restore</strong> (admin): export and import the configuration as a versioned JSON file.</li>
            <li><strong class="text-theme-text-primary">Users</strong> (admin): manage accounts and roles.</li>
            <li><strong class="text-theme-text-primary">Metrics</strong> (admin): live Prometheus metrics with API, database, job, and process health summaries.</li>
          </ul>
        </HelpPopover>
      </div>

      {/* Tab content */}
      <Suspense fallback={<div class="text-theme-text-secondary text-sm p-4">Loading...</div>}>
        <Show when={activeTab() === "scan"}>
          <div class="tab-fade-in">
            <ScanManager />
          </div>
        </Show>
        <Show when={activeTab() === "equipment"}>
          <div class="tab-fade-in rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Filters</h2>
                <HelpPopover title="Filters">
                  <FiltersSectionHelp />
                </HelpPopover>
              </div>
              <FiltersTab />
            </div>
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Equipment Grouping</h2>
                <HelpPopover title="Equipment Grouping">
                  <EquipmentGroupingSectionHelp />
                </HelpPopover>
              </div>
              <EquipmentTab />
            </div>
          </div>
        </Show>
        <Show when={activeTab() === "display"}>
          <div class="tab-fade-in">
            <DisplayTab />
          </div>
        </Show>
        <Show when={activeTab() === "astrobin"}>
          <div class="tab-fade-in">
            <AstroBinTab />
          </div>
        </Show>
        <Show when={activeTab() === "targets"}>
          <div class="tab-fade-in">
            <TargetManagementTab />
          </div>
        </Show>
        <Show when={activeTab() === "custom-columns"}>
          <div class="tab-fade-in">
            <CustomColumnsTab />
          </div>
        </Show>
        <Show when={activeTab() === "backup" && isAdmin()}>
          <div class="tab-fade-in">
            <BackupRestoreTab />
          </div>
        </Show>
        <Show when={activeTab() === "users" && isAdmin()}>
          <div class="tab-fade-in">
            <UsersTab />
          </div>
        </Show>
        <Show when={activeTab() === "activity-log" && isAdmin()}>
          <div class="tab-fade-in">
            <ActivityLogTab />
          </div>
        </Show>
        <Show when={activeTab() === "metrics" && isAdmin()}>
          <div class="tab-fade-in">
            <MetricsTab />
          </div>
        </Show>
      </Suspense>
    </div>
  );
};
