import { createSignal, createEffect, onMount, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { showToast } from "../Toast";
import { SuggestionsBanner } from "./SuggestionsBanner";
import { GroupingEditor, type GroupEntry } from "./GroupingEditor";
import type { EquipmentConfig, SuggestionsResponse, DiscoveredItem, SuggestionGroup } from "../../types";
import { api } from "../../api/client";

export const EquipmentTab: Component = () => {
  const { settings, saveEquipment } = useSettingsContext();
  const [cameraGroups, setCameraGroups] = createSignal<GroupEntry[]>([]);
  const [telescopeGroups, setTelescopeGroups] = createSignal<GroupEntry[]>([]);
  const [discoveredCameras, setDiscoveredCameras] = createSignal<DiscoveredItem[]>([]);
  const [discoveredTelescopes, setDiscoveredTelescopes] = createSignal<DiscoveredItem[]>([]);
  const [suggestions, setSuggestions] = createSignal<SuggestionsResponse>({ suggestions: [] });
  const [dismissed, setDismissed] = createSignal<string[][]>([]);
  const [saving, setSaving] = createSignal(false);

  createEffect(() => {
    const s = settings();
    if (!s) return;
    setCameraGroups(
      Object.entries(s.equipment.cameras).map(([name, conf]) => ({
        canonical: name,
        aliases: conf.aliases,
      }))
    );
    setTelescopeGroups(
      Object.entries(s.equipment.telescopes).map(([name, conf]) => ({
        canonical: name,
        aliases: conf.aliases,
      }))
    );
    setDismissed(s.dismissed_suggestions || []);
  });

  onMount(async () => {
    try {
      const [cams, tels, sugg] = await Promise.all([
        api.getDiscovered("cameras"),
        api.getDiscovered("telescopes"),
        api.getEquipmentSuggestions(),
      ]);
      setDiscoveredCameras(cams.items);
      setDiscoveredTelescopes(tels.items);
      setSuggestions(sugg);
    } catch {
      // Non-blocking
    }
  });

  const handleMerge = (canonical: string, aliases: string[], section?: string) => {
    const setter = section === "telescopes" ? setTelescopeGroups : setCameraGroups;
    setter((prev) => {
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
      return [...cleaned, { canonical, aliases }];
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

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: EquipmentConfig = {
        cameras: Object.fromEntries(
          cameraGroups().map((g) => [g.canonical, { aliases: g.aliases }])
        ),
        telescopes: Object.fromEntries(
          telescopeGroups().map((g) => [g.canonical, { aliases: g.aliases }])
        ),
      };
      await saveEquipment(payload);
      await api.updateDismissedSuggestions(dismissed());
      showToast("Equipment settings saved");
      const data = await api.getEquipmentSuggestions();
      setSuggestions(data);
    } catch {
      showToast("Failed to save equipment settings", "error");
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
        <h3 class="text-theme-text-primary font-medium">Cameras</h3>
        <GroupingEditor
          discovered={discoveredCameras()}
          groups={cameraGroups()}
          onGroupsChange={setCameraGroups}
        />
      </div>

      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">Telescopes</h3>
        <GroupingEditor
          discovered={discoveredTelescopes()}
          groups={telescopeGroups()}
          onGroupsChange={setTelescopeGroups}
        />
      </div>

      <div class="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving()}
          class="px-3 py-1.5 bg-theme-accent text-white rounded text-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {saving() ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
};
