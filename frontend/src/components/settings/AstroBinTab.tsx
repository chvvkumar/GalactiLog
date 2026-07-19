import { createSignal, createResource, createMemo, For } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import HelpPopover from "../HelpPopover";

interface Instance {
  name: string;
  url: string;
  enabled: boolean;
}

const WBPP_DEFAULT_EXCLUSIONS = [
  "WBPP", "PixInsight", "finals", "WORK_AREA",
  "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
];

function PixInsightExportSection() {
  const ctx = useSettingsContext();
  const general = () => ctx.settings()?.general;

  const save = (patch: Record<string, unknown>) => {
    const current = general();
    if (!current) return;
    ctx.saveGeneral({ ...current, ...patch });
  };

  const exclusionsValue = () =>
    (general()?.wbpp_exclusions ?? WBPP_DEFAULT_EXCLUSIONS).join("\n");

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex items-center gap-2">
        <h3 class="text-theme-text-primary font-medium">PixInsight Export</h3>
        <HelpPopover title="PixInsight Export">
          <p>The "Export For Stacking" action produces a copy script (PowerShell .ps1 on Windows, or shell .sh on Linux/macOS) for a target. For each selected session it locates that session's source folder on disk, then the script copies those folders into a single staging folder on the PixInsight machine. Excluded folder patterns are skipped during the copy. After the script finishes, open PixInsight WeightedBatchPreprocessing (WBPP) and use "Add Directory" on the staging root to load the frames. The action stages files for manual import; it does not run WBPP or build a WBPP process.</p>
          <p>The fields below are the defaults applied when you open the export modal. You can override any of them per export in the modal.</p>
          <p>Library root: the folder on the machine running PixInsight that mirrors the server's FITS data root. Stored container paths are rewritten relative to this root.</p>
          <p>Staging path: where session folders are copied to. Leave blank to use &lt;library root&gt;/_WBPP_staging/&lt;target&gt;.</p>
          <p>Excluded folder patterns skip processing-output folders so they are not re-ingested by WBPP.</p>
          <p>The export's quality filter ("Skip low-quality light frames") is configured in the modal itself and saved from there, so its mode, threshold, baseline and raw constraints carry over to your next export. It is not repeated here because it is tuned against the frame preview beside it.</p>
        </HelpPopover>
      </div>

      <div class="space-y-3">
        <div>
          <label class="text-xs text-theme-text-secondary block mb-1">Library root (on the PixInsight machine)</label>
          <input
            type="text"
            class="w-full text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary"
            placeholder="e.g. Z:\Astro or /mnt/astro"
            value={general()?.wbpp_library_root ?? ""}
            onChange={(e) => save({ wbpp_library_root: e.currentTarget.value.trim() || null })}
          />
        </div>

        <div>
          <label class="text-xs text-theme-text-secondary block mb-1">Script type</label>
          <select
            class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary"
            value={general()?.wbpp_default_os ?? "auto"}
            onChange={(e) => {
              const v = e.currentTarget.value;
              save({ wbpp_default_os: v === "auto" ? null : v });
            }}
          >
            <option value="auto">Auto-detect from library root</option>
            <option value="windows">Windows (PowerShell .ps1)</option>
            <option value="posix">Linux / macOS (shell .sh)</option>
          </select>
        </div>

        <div>
          <label class="text-xs text-theme-text-secondary block mb-1">Staging path (optional)</label>
          <input
            type="text"
            class="w-full text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary"
            placeholder="Default: <library root>/_WBPP_staging/<target>"
            value={general()?.wbpp_staging_path ?? ""}
            onChange={(e) => save({ wbpp_staging_path: e.currentTarget.value.trim() || null })}
          />
        </div>

        <div>
          <label class="text-xs text-theme-text-secondary block mb-1">Excluded folder patterns (one per line)</label>
          <textarea
            class="w-full text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary font-mono"
            rows={5}
            value={exclusionsValue()}
            onChange={(e) =>
              save({
                wbpp_exclusions: e.currentTarget.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter((s) => s.length > 0),
              })
            }
          />
        </div>
      </div>
    </div>
  );
}

function InstanceList(props: {
  label: string;
  helpText: string;
  instances: Instance[];
  onChange: (instances: Instance[]) => void;
}) {
  const update = (index: number, field: keyof Instance, value: string | boolean) => {
    const next = props.instances.map((inst, i) =>
      i === index ? { ...inst, [field]: value } : inst
    );
    props.onChange(next);
  };

  const remove = (index: number) => {
    props.onChange(props.instances.filter((_, i) => i !== index));
  };

  const add = () => {
    props.onChange([...props.instances, { name: "", url: "", enabled: true }]);
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
      <div class="flex items-center gap-2">
        <h3 class="text-theme-text-primary font-medium">{props.label}</h3>
        <HelpPopover title={props.label}>
          <p>{props.helpText}</p>
        </HelpPopover>
      </div>
      <div class="space-y-2">
        <For each={props.instances}>
          {(inst, index) => (
            <div class="flex items-center gap-2">
              <input
                type="text"
                class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 w-28 text-theme-text-primary"
                placeholder="Name"
                value={inst.name}
                onChange={(e) => update(index(), "name", e.currentTarget.value)}
              />
              <input
                type="text"
                class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 flex-1 text-theme-text-primary"
                placeholder="http://host:port"
                value={inst.url}
                onChange={(e) => update(index(), "url", e.currentTarget.value)}
              />
              <label class="flex items-center gap-1 text-xs text-theme-text-secondary cursor-pointer">
                <input
                  type="checkbox"
                  checked={inst.enabled}
                  onChange={(e) => update(index(), "enabled", e.currentTarget.checked)}
                  class="accent-theme-accent"
                />
                On
              </label>
              <button
                class="text-xs text-theme-text-tertiary hover:text-red-400 transition-colors cursor-pointer px-1"
                onClick={() => remove(index())}
                title="Remove instance"
              >
                x
              </button>
            </div>
          )}
        </For>
      </div>
      <button
        class="text-xs text-theme-accent hover:text-theme-accent-hover transition-colors cursor-pointer"
        onClick={add}
      >
        + Add instance
      </button>
    </div>
  );
}

export default function AstroBinTab() {
  const ctx = useSettingsContext();

  const [discovered] = createResource(() =>
    apiClient
      .GET("/api/settings/discovered/{section}", { params: { path: { section: "filters" } } })
      .then(unwrap)
      .then((r) => r.items)
  );

  const allFilterNames = createMemo(() => {
    const filters = ctx.settings()?.filters || {};
    const names = new Set<string>();
    const aliasToGroup = new Map<string, string>();
    for (const [group, config] of Object.entries(filters)) {
      names.add(group);
      aliasToGroup.set(group.toLowerCase(), group);
      for (const alias of config.aliases || []) {
        aliasToGroup.set(alias.toLowerCase(), group);
      }
    }
    for (const item of discovered() || []) {
      if (!aliasToGroup.has(item.name.toLowerCase())) {
        names.add(item.name);
      }
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  });

  const saveInstances = (field: "nina_instances" | "stellarium_instances", instances: Instance[]) => {
    const current = ctx.settings()?.general;
    if (!current) return;
    ctx.saveGeneral({ ...current, [field]: instances });
  };

  return (
    <div class="flex gap-6">
      {/* Left column: AstroBin config */}
      <div class="flex-1 space-y-4">
        {/* AstroBin */}
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
          <div class="flex items-center gap-2">
            <h3 class="text-theme-text-primary font-medium">AstroBin</h3>
            <HelpPopover title="AstroBin">
              <p>Settings written into the AstroBin CSV export used to upload acquisition sessions to AstroBin.</p>
              <p>Filter ID mapping: maps each local filter name to the AstroBin equipment database ID. Without a mapping, the filter column in the export stays blank for that filter. The AstroBin filter ID is the numeric path segment in the URL when viewing the filter on AstroBin. Example: Chroma LRGB L lives at app.astrobin.com/equipment/explorer/filter/4649/... so its AstroBin ID is 4649.</p>
              <p>Bortle class: dark-sky scale value from 1 (excellent dark site) to 9 (inner-city sky). Written into every row of the export so uploaded acquisitions carry the site-brightness context. Example: set Bortle 4 for a rural-transition site, or Bortle 8 for typical city observing.</p>
            </HelpPopover>
          </div>

          <div>
            <label class="text-xs text-theme-text-secondary block mb-2">Filter ID mapping</label>
            <div class="space-y-2">
              <For each={allFilterNames()}>
                {(filterName) => (
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-theme-text-primary w-24">{filterName}</span>
                    <input
                      type="number"
                      class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 w-32 text-theme-text-primary"
                      placeholder="AstroBin ID"
                      value={ctx.settings()?.general.astrobin_filter_ids?.[filterName] ?? ""}
                      onChange={(e) => {
                        const val = e.currentTarget.value ? Number(e.currentTarget.value) : undefined;
                        const current = ctx.settings()?.general;
                        if (!current) return;
                        const ids = { ...current.astrobin_filter_ids };
                        if (val) ids[filterName] = val;
                        else delete ids[filterName];
                        ctx.saveGeneral({ ...current, astrobin_filter_ids: ids });
                      }}
                    />
                  </div>
                )}
              </For>
            </div>
          </div>

          <div class="pt-2 border-t border-theme-border">
            <label class="text-xs text-theme-text-secondary block mb-2">Bortle class</label>
            <div class="flex items-center gap-3">
              <span class="text-xs text-theme-text-primary w-24">Bortle Class</span>
              <input
                type="number"
                min="1"
                max="9"
                class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 w-20 text-theme-text-primary"
                placeholder="1-9"
                value={ctx.settings()?.general.astrobin_bortle ?? ""}
                onChange={(e) => {
                  const val = e.currentTarget.value ? Number(e.currentTarget.value) : undefined;
                  const current = ctx.settings()?.general;
                  if (!current) return;
                  ctx.saveGeneral({ ...current, astrobin_bortle: val });
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Right column: NINA & Stellarium instances */}
      <div class="flex-1 space-y-4">
        <InstanceList
          label="NINA Instances"
          helpText="Configure NINA instances. Each enabled instance with a URL will appear as a button on session cards, sending the target's coordinates to NINA's framing assistant. URL format: http://host:1888"
          instances={ctx.settings()?.general.nina_instances ?? []}
          onChange={(instances) => saveInstances("nina_instances", instances)}
        />
        <InstanceList
          label="Stellarium Instances"
          helpText="Configure Stellarium Remote Control plugin instances. Each enabled instance with a URL will appear as a button on session cards, sending the target's coordinates to Stellarium for visualization. URL format: http://host:8090"
          instances={ctx.settings()?.general.stellarium_instances ?? []}
          onChange={(instances) => saveInstances("stellarium_instances", instances)}
        />
        <PixInsightExportSection />
      </div>
    </div>
  );
}
