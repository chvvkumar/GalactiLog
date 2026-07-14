import { createSignal, createEffect, onMount, Show, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { SuggestionsBanner } from "./SuggestionsBanner";
import { GroupingEditor, type GroupEntry } from "./GroupingEditor";
import HelpPopover from "../HelpPopover";
// FilterConfig is the hand-written definition in `../../api/types`: it
// feeds useSettingsContext().saveFilters, whose signature in
// SettingsProvider.tsx is pinned to the hand-written, narrower-optional
// settings types (same precedent as store/settings.ts).
// SuggestionsResponse/DiscoveredItem/SuggestionGroup come straight back from
// apiClient responses below, so they're repointed to the generated alias
// (closes the Slice 12 SuggestionGroup deferral).
import type { FilterConfig } from "../../api/types";
import type { SuggestionsResponse, DiscoveredItem, SuggestionGroup } from "../../api/types";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { getFilterColorMap } from "../../store/settings";
import Button from "../ui/Button";

export const FiltersTab: Component = () => {
  const { isAdmin } = useAuth();
  const { settings, saveFilters } = useSettingsContext();
  const [groups, setGroups] = createSignal<GroupEntry[]>([]);
  const [discovered, setDiscovered] = createSignal<DiscoveredItem[]>([]);
  const [suggestions, setSuggestions] = createSignal<SuggestionsResponse>({ suggestions: [] });
  const [dismissed, setDismissed] = createSignal<string[][]>([]);
  const [saving, setSaving] = createSignal(false);
  const [newFilterName, setNewFilterName] = createSignal("");
  const [ungroupedColors, setUngroupedColors] = createSignal<Record<string, string>>({});

  // Convert settings filters to GroupEntry[] and ungrouped colors
  createEffect(() => {
    const s = settings();
    if (!s) return;
    const entries: GroupEntry[] = [];
    const colors: Record<string, string> = {};
    for (const [name, cfg] of Object.entries(s.filters)) {
      if (cfg.aliases.length > 0) {
        entries.push({ canonical: name, aliases: cfg.aliases, color: cfg.color });
      } else {
        // Standalone filter with just a color - treat as ungrouped with color
        colors[name] = cfg.color;
      }
    }
    setGroups(entries);
    setUngroupedColors(colors);
    setDismissed(s.dismissed_suggestions || []);
  });

  onMount(async () => {
    try {
      const [disc, sugg] = await Promise.all([
        apiClient.GET("/api/settings/discovered/{section}", { params: { path: { section: "filters" } } }).then(unwrap),
        apiClient.GET("/api/settings/suggestions/filters", {}).then(unwrap),
      ]);
      setDiscovered(disc.items);
      setSuggestions(sugg);

      // Seed ungrouped items with default colors from getFilterColorMap
      // so R/G/B/L etc. show their conventional colors even before explicit save
      const defaults = getFilterColorMap(settings());
      const grouped = new Set<string>();
      for (const g of groups()) {
        grouped.add(g.canonical);
        for (const a of g.aliases) grouped.add(a);
      }
      setUngroupedColors((prev) => {
        const merged = { ...prev };
        for (const item of disc.items) {
          if (!grouped.has(item.name) && !merged[item.name] && defaults[item.name]) {
            merged[item.name] = defaults[item.name];
          }
        }
        return merged;
      });
    } catch {
      // Non-blocking
    }
  });

  const handleMerge = (canonical: string, aliases: string[], _section?: string | null) => {
    setGroups((prev) => {
      const existingIdx = prev.findIndex((g) => g.canonical === canonical);
      if (existingIdx >= 0) {
        return prev.map((g, i) => {
          if (i !== existingIdx) return g;
          const allAliases = new Set(g.aliases);
          for (const a of aliases) allAliases.add(a);
          return { ...g, aliases: [...allAliases] };
        });
      }
      const cleaned = prev.filter((g) => !aliases.includes(g.canonical));
      return [...cleaned, { canonical, aliases, color: "#808080" }];
    });
    setSuggestions((prev) => ({
      suggestions: prev.suggestions.filter(
        (g) => !g.group.includes(canonical) || g.group.every((n) => n === canonical),
      ),
    }));
  };

  const handleDismiss = (group: SuggestionGroup) => {
    const sorted = [...group.group].sort();
    setDismissed((prev) => [...prev, sorted]);
    setSuggestions((prev) => ({
      suggestions: prev.suggestions.filter((g) => g !== group),
    }));
  };

  const addFilter = () => {
    const name = newFilterName().trim();
    if (!name || groups().some((g) => g.canonical === name)) return;
    setGroups((prev) => [...prev, { canonical: name, aliases: [], color: "#808080" }]);
    setNewFilterName("");
  };

  const handleUngroupedColorChange = (name: string, color: string) => {
    setUngroupedColors((prev) => ({ ...prev, [name]: color }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const filtersPayload: Record<string, FilterConfig> = {};
      for (const g of groups()) {
        filtersPayload[g.canonical] = {
          color: g.color || "#808080",
          aliases: g.aliases,
        };
      }
      // Include all ungrouped filters with their colors
      for (const [name, color] of Object.entries(ungroupedColors())) {
        if (!filtersPayload[name]) {
          filtersPayload[name] = { color, aliases: [] };
        }
      }
      // Also include any discovered ungrouped filters not yet in the payload
      // so their default colors get persisted on first save.
      // Skip names already covered as aliases in existing groups.
      const defaults = getFilterColorMap(settings());
      const knownNames = new Set(Object.keys(filtersPayload));
      const coveredAliases = new Set<string>();
      for (const cfg of Object.values(filtersPayload)) {
        for (const alias of cfg.aliases) coveredAliases.add(alias);
      }
      for (const item of discovered()) {
        if (!knownNames.has(item.name) && !coveredAliases.has(item.name)) {
          filtersPayload[item.name] = {
            color: ungroupedColors()[item.name] || defaults[item.name] || "#808080",
            aliases: [],
          };
        }
      }
      await saveFilters(filtersPayload);
      await apiClient.PUT("/api/settings/dismissed-suggestions", { body: dismissed() }).then(unwrap);
      showToast("Filter settings saved");
      const data = await apiClient.GET("/api/settings/suggestions/filters", {}).then(unwrap);
      setSuggestions(data);
    } catch {
      showToast("Failed to save filter settings", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="space-y-4">
      <SuggestionsBanner
        suggestions={suggestions().suggestions}
        onMerge={handleMerge}
        onDismiss={handleDismiss}
      />

      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium">Filter Groups</h3>
          <HelpPopover title="Filter Groups">
            <p>Defines canonical filter names, their aliases from FITS FILTER headers, and the display color used in badges and charts.</p>
            <p>Example: merge "Ha", "H-alpha", and "Halpha" under canonical "Ha" with a red color; every dashboard row and chart then renders those captures as the same filter.</p>
            <p>Add a new filter with the input below. Suggestions appear when GalactiLog detects likely alias pairs; accept or dismiss from the banner above.</p>
          </HelpPopover>
        </div>

        <GroupingEditor
          discovered={discovered()}
          groups={groups()}
          showColorPicker={true}
          ungroupedColors={ungroupedColors()}
          onGroupsChange={setGroups}
          onUngroupedColorChange={handleUngroupedColorChange}
        />

        <div class="flex gap-2">
          <input
            type="text"
            placeholder="New filter name"
            value={newFilterName()}
            onInput={(e) => setNewFilterName(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && addFilter()}
            class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none"
          />
          <Button onClick={addFilter}>Add Filter</Button>
        </div>
      </div>

      <Show when={isAdmin()}>
        <div class="flex justify-end">
          <Button size="sm" onClick={handleSave} disabled={saving()}>
            {saving() ? "Saving..." : "Save"}
          </Button>
        </div>
      </Show>
    </div>
  );
};
