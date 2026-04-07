import { createSignal, createEffect, onMount, Show, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { SuggestionsBanner } from "./SuggestionsBanner";
import { GroupingEditor, type GroupEntry } from "./GroupingEditor";
import type { FilterConfig, SuggestionsResponse, DiscoveredItem, SuggestionGroup } from "../../types";
import { api } from "../../api/client";

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
        // Standalone filter with just a color — treat as ungrouped with color
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
        api.getDiscovered("filters"),
        api.getFilterSuggestions(),
      ]);
      setDiscovered(disc.items);
      setSuggestions(sugg);
    } catch {
      // Non-blocking
    }
  });

  const handleMerge = (canonical: string, aliases: string[], _section?: string) => {
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
      // Include ungrouped filters that have custom colors
      for (const [name, color] of Object.entries(ungroupedColors())) {
        if (!filtersPayload[name]) {
          filtersPayload[name] = { color, aliases: [] };
        }
      }
      await saveFilters(filtersPayload);
      await api.updateDismissedSuggestions(dismissed());
      showToast("Filter settings saved");
      const data = await api.getFilterSuggestions();
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
        <h3 class="text-theme-text-primary font-medium">Filter Groups</h3>

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
          <button
            onClick={addFilter}
            class="px-3 py-1.5 border border-theme-border text-theme-text-secondary rounded text-sm hover:border-theme-accent hover:text-theme-text-primary transition-colors"
          >
            Add Filter
          </button>
        </div>
      </div>

      <Show when={isAdmin()}>
        <div class="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving()}
            class="px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 disabled:opacity-50 transition-colors"
          >
            {saving() ? "Saving..." : "Save"}
          </button>
        </div>
      </Show>
    </div>
  );
};
