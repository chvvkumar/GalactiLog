import { Component, For, Show } from "solid-js";
import { useSettingsContext } from "./SettingsProvider";
import { getFilterBadgeStyle } from "../utils/filterStyles";

// Canonical filter category for a given filter name.
// Maps all common naming variations to one of the 7 standard categories,
// or returns null for non-standard filters (IR, Duoband, etc.)
function canonicalCategory(name: string): string | null {
  const n = name.toLowerCase().replace(/[_\-\s]/g, "");
  // Luminance
  if (n === "l" || n === "lum" || n === "luminance" || n === "luminosity" || n === "clear") return "L";
  // Red
  if (n === "r" || n === "red") return "R";
  // Green
  if (n === "g" || n === "green") return "G";
  // Blue
  if (n === "b" || n === "blue") return "B";
  // Sulfur II — check before Ha to avoid "sho" false matches
  if (n === "sii" || n === "s2" || n === "s" || n === "sulfur" || n === "sulphur"
    || n === "sulfurii" || n === "sulphurii") return "SII";
  // Hydrogen alpha
  if (n === "ha" || n === "h" || n === "halpha" || n === "hydrogenalpha"
    || n === "hydrogen" || n === "h alpha" || n === "656nm" || n === "656") return "Ha";
  // Oxygen III
  if (n === "oiii" || n === "o3" || n === "o" || n === "oxygen" || n === "oxygeniii"
    || n === "500nm" || n === "501nm") return "OIII";
  return null;
}

// Sort order: L R G B S H O, then everything else alphabetically
const FILTER_ORDER: Record<string, number> = {
  L: 0, R: 1, G: 2, B: 3, SII: 4, Ha: 5, OIII: 6,
};

const SHORT_LABEL: Record<string, string> = {
  Ha: "H",
  OIII: "O",
  SII: "S",
  L: "L",
  R: "R",
  G: "G",
  B: "B",
  OSC: "OSC",
  IR: "IR",
  Duoband: "Duo",
  "L-Ultimate": "L-Ult",
  "L-Extreme": "L-Ext",
  "L-Pro": "L-Pro",
  Ultimate: "Ult",
  Extreme: "Ext",
};

function filterSortKey(name: string): number {
  if (FILTER_ORDER[name] !== undefined) return FILTER_ORDER[name];
  const cat = canonicalCategory(name);
  if (cat && FILTER_ORDER[cat] !== undefined) return FILTER_ORDER[cat];
  return 100; // non-standard filters sort after LRGBSHO
}

import { formatIntegration } from "../utils/format";

const FilterBadges: Component<{ distribution: Record<string, number>; compact?: boolean; nowrap?: boolean }> = (props) => {
  const { filterColorMap, filterAliasMap, filterBadgeStyle } = useSettingsContext();

  function getColor(name: string): string {
    const colorMap = filterColorMap();
    const aliasMap = filterAliasMap();
    const canonical = aliasMap[name] || name;
    if (colorMap[canonical]) return colorMap[canonical];
    const cat = canonicalCategory(name);
    if (cat && colorMap[cat]) return colorMap[cat];
    return "#666666";
  }

  const entries = () =>
    Object.entries(props.distribution).sort(([a], [b]) => {
      const orderA = filterSortKey(a);
      const orderB = filterSortKey(b);
      if (orderA !== orderB) return orderA - orderB;
      return a.localeCompare(b); // alphabetical tiebreak for non-standard filters
    });

  return (
    <div class={`flex gap-1.5 ${props.nowrap ? "flex-nowrap" : "flex-wrap"}`}>
      <For each={entries()}>
        {([name, seconds]) => {
          const badgeStyle = () => getFilterBadgeStyle(filterBadgeStyle(), getColor(name));
          return (
            <Show
              when={props.compact}
              fallback={
                <span class="px-2 py-0.5 rounded-full text-label font-medium inline-flex items-center gap-1" style={badgeStyle().style}>
                  <Show when={badgeStyle().dot}>
                    <span class="w-1.5 h-1.5 rounded-full inline-block" style={{ "background-color": badgeStyle().dot }} />
                  </Show>
                  {name}&middot;{formatIntegration(seconds)}
                </span>
              }
            >
              <span
                class="h-6 rounded text-caption font-bold flex items-center justify-center gap-0.5"
                style={badgeStyle().style}
                classList={{ "w-6": (SHORT_LABEL[name] || name).length <= 1 && !badgeStyle().dot, "px-1.5": (SHORT_LABEL[name] || name).length > 1 || !!badgeStyle().dot }}
                title={name}
              >
                <Show when={badgeStyle().dot}>
                  <span class="w-1.5 h-1.5 rounded-full inline-block flex-shrink-0" style={{ "background-color": badgeStyle().dot }} />
                </Show>
                {SHORT_LABEL[name] || name}
              </span>
            </Show>
          );
        }}
      </For>
    </div>
  );
};

export default FilterBadges;
