import { createSignal, createResource, createMemo, For } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { api } from "../../api/client";
import HelpPopover from "../HelpPopover";

export default function AstroBinTab() {
  const ctx = useSettingsContext();

  const [discovered] = createResource(() =>
    api.getDiscovered("filters").then((r) => r.items)
  );

  // Build list: filter groups (canonical names) + ungrouped discovered filters
  const allFilterNames = createMemo(() => {
    const filters = ctx.settings()?.filters || {};
    const names = new Set<string>();
    // All aliases mapped to their group name
    const aliasToGroup = new Map<string, string>();
    for (const [group, config] of Object.entries(filters)) {
      names.add(group);
      aliasToGroup.set(group.toLowerCase(), group);
      for (const alias of config.aliases || []) {
        aliasToGroup.set(alias.toLowerCase(), group);
      }
    }
    // Add discovered filters only if not part of any group
    for (const item of discovered() || []) {
      if (!aliasToGroup.has(item.name.toLowerCase())) {
        names.add(item.name);
      }
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  });

  return (
    <div class="space-y-4">
      {/* Filter ID Mapping */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium">Filter ID Mapping</h3>
          <HelpPopover title="Filter ID Mapping">
            <p>Maps each local filter name to the AstroBin equipment database ID used in AstroBin CSV imports. Without a mapping, the filter column in the export stays blank for that filter.</p>
            <p>The AstroBin filter ID is the numeric path segment in the URL when viewing the filter on AstroBin.</p>
            <p>Example: Chroma LRGB L lives at app.astrobin.com/equipment/explorer/filter/4649/... so its AstroBin ID is 4649.</p>
          </HelpPopover>
        </div>
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

      {/* Bortle Class */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium">Bortle Class</h3>
          <HelpPopover title="Bortle Class">
            <p>Bortle dark-sky scale value from 1 (excellent dark site) to 9 (inner-city sky). Written into every row of the AstroBin CSV export so uploaded acquisitions carry the site-brightness context.</p>
            <p>Example: set Bortle 4 for a rural-transition site, or Bortle 8 for typical city observing.</p>
          </HelpPopover>
        </div>
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
  );
}
