import { createSignal, createMemo, For, Show, type Component } from "solid-js";
import type { DiscoveredItem } from "../../types";

export interface GroupEntry {
  canonical: string;
  aliases: string[];
  color?: string; // only used for filters
}

interface Props {
  /** All raw names discovered from the DB with frame counts */
  discovered: DiscoveredItem[];
  /** Current groups (canonical + aliases) */
  groups: GroupEntry[];
  /** Whether to show color pickers (filters mode) */
  showColorPicker?: boolean;
  /** Colors for ungrouped items (keyed by name) — only used when showColorPicker is true */
  ungroupedColors?: Record<string, string>;
  /** Called when user modifies groups locally */
  onGroupsChange: (groups: GroupEntry[]) => void;
  /** Called when user changes color on an ungrouped item */
  onUngroupedColorChange?: (name: string, color: string) => void;
}

export const GroupingEditor: Component<Props> = (props) => {
  const [checked, setChecked] = createSignal<Set<string>>(new Set());

  /** Names that are part of any group (as canonical or alias) */
  const groupedNames = createMemo(() => {
    const names = new Set<string>();
    for (const g of props.groups) {
      names.add(g.canonical);
      for (const a of g.aliases) names.add(a);
    }
    return names;
  });

  /** Discovered items not in any group */
  const ungrouped = createMemo(() =>
    props.discovered.filter((d) => !groupedNames().has(d.name))
  );

  const toggleCheck = (name: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const checkedCount = createMemo(() => checked().size);

  /** Create a new group from checked items */
  const groupSelected = () => {
    const names = [...checked()];
    if (names.length < 2) return;

    // Pre-select canonical: highest frame count among checked items
    const counts = new Map(props.discovered.map((d) => [d.name, d.count]));
    names.sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0));
    const canonical = names[0];
    const aliases = names.slice(1);

    const newGroup: GroupEntry = { canonical, aliases };
    props.onGroupsChange([...props.groups, newGroup]);
    setChecked(new Set<string>());
  };

  /** Add checked items to an existing group */
  const addToGroup = (groupIndex: number) => {
    const names = [...checked()];
    if (names.length === 0) return;

    const updated = props.groups.map((g, i) => {
      if (i !== groupIndex) return g;
      const existingAliases = new Set(g.aliases);
      for (const name of names) existingAliases.add(name);
      return { ...g, aliases: [...existingAliases] };
    });
    props.onGroupsChange(updated);
    setChecked(new Set<string>());
  };

  /** Remove an alias from a group (moves back to ungrouped) */
  const removeAlias = (groupIndex: number, alias: string) => {
    const updated = props.groups.map((g, i) => {
      if (i !== groupIndex) return g;
      return { ...g, aliases: g.aliases.filter((a) => a !== alias) };
    });
    // Remove group if it has no aliases left
    const filtered = updated.filter((g, i) => {
      if (i !== groupIndex) return true;
      return g.aliases.length > 0;
    });
    props.onGroupsChange(filtered);
  };

  /** Update the color of a group's canonical name */
  const updateColor = (groupIndex: number, color: string) => {
    const updated = props.groups.map((g, i) => {
      if (i !== groupIndex) return g;
      return { ...g, color };
    });
    props.onGroupsChange(updated);
  };

  return (
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Left column — Ungrouped */}
      <div class="space-y-3">
        <h3 class="text-sm text-theme-text-secondary font-medium uppercase tracking-wide">
          Ungrouped ({ungrouped().length})
        </h3>
        <div class="space-y-1 max-h-[400px] overflow-y-auto">
          <For each={ungrouped()}>
            {(item) => (
              <label class="flex items-center gap-2 px-3 py-1.5 bg-theme-base/50 rounded cursor-pointer hover:bg-theme-base/70 transition-colors">
                <input
                  type="checkbox"
                  checked={checked().has(item.name)}
                  onChange={() => toggleCheck(item.name)}
                  class="rounded border-theme-border bg-theme-base text-theme-accent focus:ring-theme-accent"
                />
                <Show when={props.showColorPicker}>
                  <input
                    type="color"
                    value={props.ungroupedColors?.[item.name] || "#808080"}
                    onInput={(e) => {
                      e.stopPropagation();
                      props.onUngroupedColorChange?.(item.name, e.currentTarget.value);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    class="w-5 h-5 rounded cursor-pointer border-0 bg-transparent flex-shrink-0"
                  />
                </Show>
                <span class="text-sm text-theme-text-primary flex-1 truncate">{item.name}</span>
                <span class="text-xs text-theme-text-secondary">{item.count} frames</span>
              </label>
            )}
          </For>
          <Show when={ungrouped().length === 0}>
            <p class="text-sm text-theme-text-secondary italic px-3 py-2">All items are grouped</p>
          </Show>
        </div>
        <div class="flex gap-2">
          <button
            onClick={groupSelected}
            disabled={checkedCount() < 2}
            class="px-3 py-1.5 bg-theme-accent text-white text-sm rounded hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed transition-opacity"
          >
            Group Selected ({checkedCount()})
          </button>
          <Show when={checkedCount() > 0 && props.groups.length > 0}>
            <div class="relative group">
              <button class="px-3 py-1.5 border border-theme-border text-theme-text-secondary text-sm rounded hover:border-theme-accent hover:text-theme-text-primary transition-colors">
                Add to...
              </button>
              <div class="absolute left-0 top-full pt-1 bg-transparent hidden group-hover:block min-w-[180px] z-10">
                <div class="bg-theme-surface border border-theme-border rounded shadow-lg">
                <For each={props.groups}>
                  {(g, i) => (
                    <button
                      onClick={() => addToGroup(i())}
                      class="block w-full text-left px-3 py-1.5 text-sm text-theme-text-secondary hover:bg-theme-base/50 hover:text-theme-text-primary"
                    >
                      {g.canonical}
                    </button>
                  )}
                </For>
                </div>
              </div>
            </div>
          </Show>
        </div>
      </div>

      {/* Right column — Groups */}
      <div class="space-y-3">
        <h3 class="text-sm text-theme-text-secondary font-medium uppercase tracking-wide">
          Groups ({props.groups.length})
        </h3>
        <div class="space-y-2 max-h-[400px] overflow-y-auto">
          <For each={props.groups}>
            {(group, i) => (
              <div class="bg-theme-base/50 rounded px-3 py-2 space-y-1">
                <div class="flex items-center gap-2">
                  <Show when={props.showColorPicker}>
                    <input
                      type="color"
                      value={group.color || "#808080"}
                      onInput={(e) => updateColor(i(), e.currentTarget.value)}
                      class="w-6 h-6 rounded cursor-pointer border-0 bg-transparent"
                    />
                  </Show>
                  <span class="text-sm text-theme-text-primary font-medium">{group.canonical}</span>
                </div>
                <div class="flex flex-wrap gap-1">
                  <For each={group.aliases}>
                    {(alias) => (
                      <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-theme-elevated rounded text-xs text-theme-text-secondary">
                        {alias}
                        <button
                          onClick={() => removeAlias(i(), alias)}
                          class="text-theme-text-tertiary hover:text-theme-error"
                        >
                          x
                        </button>
                      </span>
                    )}
                  </For>
                </div>
              </div>
            )}
          </For>
          <Show when={props.groups.length === 0}>
            <p class="text-sm text-theme-text-secondary italic px-3 py-2">No groups yet — select items on the left to create one</p>
          </Show>
        </div>
      </div>
    </div>
  );
};
