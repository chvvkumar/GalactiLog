import { createSignal, createEffect, onMount, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import { SuggestionsBanner } from "./SuggestionsBanner";
import { GroupingEditor, type GroupEntry } from "./GroupingEditor";
import type { FilterConfig, SuggestionsResponse, DiscoveredItem, SuggestionGroup } from "../../types";
import { api } from "../../api/client";

export const FiltersTab: Component = () => {
  const { settings, saveFilters } = useSettingsContext();
  const [groups, setGroups] = createSignal<GroupEntry[]>([]);
  const [discovered, setDiscovered] = createSignal<DiscoveredItem[]>([]);
  const [suggestions, setSuggestions] = createSignal<SuggestionsResponse>({ suggestions: [] });
  const [dismissed, setDismissed] = createSignal<string[][]>([]);
  const [saving, setSaving] = createSignal(false);
  const [newFilterName, setNewFilterName] = createSignal("");

  // Convert settings filters to GroupEntry[]
  createEffect(() => {
    const s = settings();
    if (!s) return;
    const entries: GroupEntry[] = Object.entries(s.filters).map(([name, cfg]) => ({
      canonical: name,
      aliases: cfg.aliases,
      color: cfg.color,
    }));
    setGroups(entries);
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
    <div class="space-y-6">
      <SuggestionsBanner
        suggestions={suggestions().suggestions}
        onMerge={handleMerge}
        onDismiss={handleDismiss}
      />

      <GroupingEditor
        discovered={discovered()}
        groups={groups()}
        showColorPicker={true}
        onGroupsChange={setGroups}
      />

      {/* Add filter */}
      <div class="flex gap-2">
        <input
          type="text"
          placeholder="New filter name"
          value={newFilterName()}
          onInput={(e) => setNewFilterName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === "Enter" && addFilter()}
          class="px-3 py-2 bg-theme-base border border-theme-border rounded text-sm text-theme-text-primary focus:outline-none focus:border-theme-accent"
        />
        <button
          onClick={addFilter}
          class="px-3 py-2 border border-theme-border text-theme-text-secondary rounded text-sm hover:border-theme-accent hover:text-theme-text-primary transition-colors"
        >
          Add Filter
        </button>
      </div>

      <button
        onClick={handleSave}
        disabled={saving()}
        class="px-4 py-2 bg-theme-accent text-white rounded text-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
      >
        {saving() ? "Saving..." : "Save"}
      </button>
    </div>
  );
};
