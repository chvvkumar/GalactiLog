// frontend/src/pages/SettingsPage.tsx
import { Show, type Component } from "solid-js";
import { useSearchParams } from "@solidjs/router";
import { FiltersTab } from "../components/settings/FiltersTab";
import { EquipmentTab } from "../components/settings/EquipmentTab";
import { MergesTab } from "../components/settings/MergesTab";
import { UsersTab } from "../components/settings/UsersTab";
import { BackupRestoreTab } from "../components/settings/BackupRestoreTab";
import ScanManager from "../components/ScanManager";
import DisplayTab from "../components/DisplayTab";
import AstroBinTab from "../components/settings/AstroBinTab";
import CustomColumnsTab from "../components/CustomColumnsTab";
import { useAuth } from "../components/AuthProvider";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import HelpPopover from "../components/HelpPopover";

const ALL_TABS = [
  { id: "scan", label: "Library" },
  { id: "equipment", label: "Equipment" },
  { id: "display", label: "Display" },
  { id: "astrobin", label: "AstroBin" },
  { id: "targets", label: "Target Management" },
  { id: "custom-columns", label: "Custom Columns" },
  { id: "backup", label: "Backup & Restore", adminOnly: true },
  { id: "users", label: "Users", adminOnly: true },
] as const;

type TabId = (typeof ALL_TABS)[number]["id"];

const TargetManagementTab: Component = () => {
  return <MergesTab />;
};

export const SettingsPage: Component = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isAdmin } = useAuth();
  const ctx = useSettingsContext();

  const tabs = () => ALL_TABS.filter((t) => !("adminOnly" in t && t.adminOnly) || isAdmin());
  const activeTab = () => (tabs().some((t) => t.id === searchParams.tab) ? (searchParams.tab as TabId) : "scan");

  return (
    <div class={`p-4 space-y-6 ${contentWidthClass(ctx.contentWidth())}`}>
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Settings</h1>

      {/* Tab bar */}
      <div class="flex flex-wrap items-center gap-1">
        <div class="flex flex-wrap gap-1 flex-1">
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
        <HelpPopover align="right">
          <Show when={activeTab() === "scan"}>
            <p class="text-sm text-theme-text-secondary">GalactiLog builds its catalog by scanning a directory of FITS files. Each scan reads FITS headers to extract target names, filters, timestamps, and equipment metadata.</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li><strong class="text-theme-text-primary">Library Scanning</strong> holds everything that controls what gets cataloged. <strong class="text-theme-text-primary">Auto-scan</strong> runs periodically on a configurable interval; <strong class="text-theme-text-primary">Scan Directory</strong> triggers a one-time scan.</li>
              <li><strong class="text-theme-text-primary">Path & name rules</strong> restrict which folders are walked and which file or folder names are included or excluded. Rules accept wildcard, substring, or regex patterns, and a test-a-path tool previews matches before saving.</li>
              <li>The action bar exposes <strong class="text-theme-text-primary">Save rules</strong>, <strong class="text-theme-text-primary">Revert</strong>, and <strong class="text-theme-text-primary">Apply now</strong>, plus a frame-filter selector: pick <strong class="text-theme-text-primary">Light frames only</strong> to skip calibration frames (darks, flats, bias) or <strong class="text-theme-text-primary">All frames</strong> to catalog everything.</li>
              <li>The <strong class="text-theme-text-primary">Database Overview</strong> card shows current catalog totals, on-disk storage (FITS, thumbnails, database), and name-resolution cache status (SIMBAD, SESAME, VizieR).</li>
              <li><strong class="text-theme-text-primary">Maintenance</strong> actions: <strong class="text-theme-text-primary">Re-match</strong> re-resolves all target names against SIMBAD. <strong class="text-theme-text-primary">Retry Unresolved</strong> retries only failed lookups. <strong class="text-theme-text-primary">Regenerate</strong> rebuilds thumbnails. <strong class="text-theme-text-primary">Full Rebuild</strong> re-scans all files from scratch, use sparingly.</li>
              <li><strong class="text-theme-text-primary">Capture Activity</strong> plots the number of light frames grouped by capture night for the 30 most recent nights with data.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "equipment"}>
            <p class="text-sm text-theme-text-secondary">Filters represent the optical bandpass used for each exposure (e.g., Luminance, Red, H-alpha).</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li>FITS headers often record the same filter under different names. Use <strong class="text-theme-text-primary">Filter Groups</strong> to merge aliases (e.g., "Ha" and "H-alpha") under a single canonical name.</li>
              <li>Assign colors to each filter - these colors are used throughout the dashboard, charts, and session tables.</li>
              <li>GalactiLog suggests groupings when it detects likely aliases. Accept or dismiss suggestions as they appear.</li>
            </ul>
            <p class="text-sm text-theme-text-secondary">Equipment grouping works like filter grouping: merge different FITS header strings that refer to the same camera or telescope into one canonical name.</p>
            <p class="text-sm text-theme-text-secondary">This keeps your dashboard and statistics consistent even if your capture software records equipment names differently across sessions.</p>
          </Show>
          <Show when={activeTab() === "display"}>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li><strong class="text-theme-text-primary">Theme</strong> changes the overall color scheme. <strong class="text-theme-text-primary">Text Size</strong> adjusts the base font size across the interface.</li>
              <li><strong class="text-theme-text-primary">Filter Badge Style</strong> controls how filter names appear in tables and charts (solid, outline, dot, etc.).</li>
              <li><strong class="text-theme-text-primary">Timezone</strong> sets the display timezone for all dates and timestamps shown in the interface.</li>
              <li><strong class="text-theme-text-primary">Content Width</strong> constrains the maximum page width - useful on ultra-wide monitors.</li>
              <li><strong class="text-theme-text-primary">Metric Visibility</strong> controls which data columns (HFR, guiding RMS, weather, etc.) appear on target detail pages. Disable groups you don't collect to reduce clutter.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "astrobin"}>
            <p class="text-sm text-theme-text-secondary">Map your local filter names to AstroBin equipment database IDs so that CSV exports are compatible with AstroBin's import format.</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li>Find the AstroBin ID in the URL when viewing a filter on astrobin.com (the numeric ID in the URL path).</li>
              <li><strong class="text-theme-text-primary">Bortle Class</strong> sets the sky brightness value included in AstroBin CSV exports.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "targets"}>
            <p class="text-sm text-theme-text-secondary">When different FITS headers produce slightly different target names for the same object, GalactiLog detects these as potential duplicates.</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li><strong class="text-theme-text-primary">Run Detection</strong> scans for name-based duplicates. Review <strong class="text-theme-text-primary">Suggestions</strong> and merge or dismiss each pair.</li>
              <li><strong class="text-theme-text-primary">Merged</strong> shows previously accepted merges - these can be reverted if needed.</li>
              <li><strong class="text-theme-text-primary">Unresolved Files</strong> lists FITS files whose target names could not be matched to any known object.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "custom-columns"}>
            <p class="text-sm text-theme-text-secondary">Custom columns let you add your own tracking fields (boolean checkboxes, text, or dropdowns) to targets, sessions, or rigs.</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li>Use them to track processing status, notes, equipment assignments, or any other metadata that isn't in FITS headers.</li>
              <li>All users share the same column definitions and values.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "backup" && isAdmin()}>
            <p class="text-sm text-theme-text-secondary">Backup and restore lets you export and import your GalactiLog configuration and data as a versioned JSON file.</p>
            <ul class="text-sm text-theme-text-secondary list-disc list-inside space-y-1">
              <li><strong class="text-theme-text-primary">What's included:</strong> settings, filter and equipment configurations, session notes, custom columns, mosaic definitions, user accounts, and display preferences.</li>
              <li>Backup files carry a schema version - older backups will restore cleanly on newer versions of the app.</li>
              <li><strong class="text-theme-text-primary">Merge mode</strong> adds or updates items from the backup without touching data not present in the file. <strong class="text-theme-text-primary">Replace mode</strong> clears the selected sections first, then imports from the backup.</li>
              <li>When restoring user accounts, temporary passwords are generated and shown once - save them before closing the restore dialog.</li>
            </ul>
          </Show>
          <Show when={activeTab() === "users" && isAdmin()}>
            <p class="text-sm text-theme-text-secondary">Manage user accounts for this GalactiLog instance. Admins can create, promote, demote, disable, or delete users.</p>
            <p class="text-sm text-theme-text-secondary"><strong class="text-theme-text-primary">Viewers</strong> can browse the catalog but cannot modify settings or trigger scans. <strong class="text-theme-text-primary">Admins</strong> have full access.</p>
          </Show>
        </HelpPopover>
      </div>

      {/* Tab content */}
      <Show when={activeTab() === "scan"}>
        <ScanManager />
      </Show>
      <Show when={activeTab() === "equipment"}>
        <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <h2 class="text-sm font-semibold text-theme-text-primary">Filters</h2>
            <FiltersTab />
          </div>
          <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
            <h2 class="text-sm font-semibold text-theme-text-primary">Equipment Grouping</h2>
            <EquipmentTab />
          </div>
        </div>
      </Show>
      <Show when={activeTab() === "display"}>
        <DisplayTab />
      </Show>
      <Show when={activeTab() === "astrobin"}>
        <AstroBinTab />
      </Show>
      <Show when={activeTab() === "targets"}>
        <TargetManagementTab />
      </Show>
      <Show when={activeTab() === "custom-columns"}>
        <CustomColumnsTab />
      </Show>
      <Show when={activeTab() === "backup" && isAdmin()}>
        <BackupRestoreTab />
      </Show>
      <Show when={activeTab() === "users" && isAdmin()}>
        <UsersTab />
      </Show>
    </div>
  );
};
