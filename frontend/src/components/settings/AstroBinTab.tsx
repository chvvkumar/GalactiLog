import { createSignal, createResource, createMemo, For } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { api } from "../../api/client";

export default function AstroBinTab() {
  const ctx = useSettingsContext();

  const [discovered] = createResource(() =>
    api.getDiscovered("filters").then((r) => r.items)
  );

  // Merge configured canonical filter names with discovered raw filter names
  const allFilterNames = createMemo(() => {
    const names = new Set<string>();
    // Configured canonical filters
    for (const name of Object.keys(ctx.settings()?.filters || {})) {
      names.add(name);
    }
    // Discovered raw filters from image data
    for (const item of discovered() || []) {
      names.add(item.name);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  });

  return (
    <div class="space-y-4">
      {/* Filter ID Mapping */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">Filter ID Mapping</h3>
        <p class="text-xs text-theme-text-secondary">
          Map your filters to AstroBin equipment database IDs for CSV import.
          Find IDs in the URL when viewing a filter on AstroBin (e.g., app.astrobin.com/equipment/explorer/filter/<strong>4388</strong>/...).
        </p>
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
        <h3 class="text-theme-text-primary font-medium">Bortle Class</h3>
        <p class="text-xs text-theme-text-secondary">
          Sky brightness classification used in AstroBin CSV exports.
        </p>
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
