import { Component, For, Show, createMemo } from "solid-js";
import type { TargetAggregation, SessionSummary } from "../types";
import TargetRow from "./TargetRow";
import ColumnPicker from "./ColumnPicker";
import { useSettingsContext } from "./SettingsProvider";
import { isColumnVisible } from "../utils/displaySettings";
import { timezoneLabel } from "../utils/dateTime";
import { useDashboardFilters, type SortKey } from "./DashboardFilterProvider";
import {
  type MetricBaseline,
  type QualityBand,
  madZ,
  bandForZ,
} from "../utils/frameQuality";

// Anomaly badge metadata attached to a target row. `null` band -> render nothing.
export interface TargetAnomaly {
  band: QualityBand;
  title: string;
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Build a robust MAD baseline from the per-session medians supplied. The
// median-of-medians and MAD give a filter-agnostic reference for the metric
// across every session currently shown on the dashboard.
function baselineFrom(values: (number | null)[]): MetricBaseline {
  const xs = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (xs.length === 0) return { median: null, mad: null, n: 0 };
  const med = median(xs);
  const mad = median(xs.map((x) => Math.abs(x - med)));
  return { median: med, mad, n: xs.length };
}

// Pick the session used to characterize a target's recent quality: the most
// recent session that carries at least one quality median (sharpness or
// roundness). Falls back to the newest session, or null when there are none.
function recentQualitySession(t: TargetAggregation): SessionSummary | null {
  const sorted = [...t.sessions].sort((a, b) => b.session_date.localeCompare(a.session_date));
  for (const s of sorted) {
    if (s.median_hfr != null || s.median_eccentricity != null) return s;
  }
  return sorted[0] ?? null;
}

const BAND_RANK: Record<QualityBand, number> = { better: 0, neutral: 1, watch: 2, reject: 3 };

// Evaluate a target's recent session against the dashboard-wide baselines.
// Both HFR and eccentricity are higher-is-worse; the badge takes the worse of
// the two bands. Returns null for neutral/better (no badge rendered).
function anomalyFor(
  t: TargetAggregation,
  hfrRef: MetricBaseline,
  eccRef: MetricBaseline,
): TargetAnomaly | null {
  const s = recentQualitySession(t);
  if (!s) return null;

  const zHfr = madZ(s.median_hfr, hfrRef);
  const zEcc = madZ(s.median_eccentricity, eccRef);
  const bHfr = bandForZ(zHfr);
  const bEcc = bandForZ(zEcc);

  const worst: QualityBand = BAND_RANK[bHfr] >= BAND_RANK[bEcc] ? bHfr : bEcc;
  if (worst !== "watch" && worst !== "reject") return null;

  const parts: string[] = [];
  if (zHfr != null && bHfr === worst) parts.push(`HFR ${zHfr.toFixed(1)}σ above typical`);
  if (zEcc != null && bEcc === worst) parts.push(`eccentricity ${zEcc.toFixed(1)}σ above typical`);
  const detail = parts.length ? parts.join(", ") : "elevated relative to other sessions";
  const verb = worst === "reject" ? "stands out sharply" : "to watch";
  return { band: worst, title: `Recent session ${verb}: ${detail}` };
}

function getLastSession(t: TargetAggregation): string {
  if (t.sessions.length === 0) return "";
  return [...t.sessions].sort((a, b) => b.session_date.localeCompare(a.session_date))[0].session_date;
}

function getDisplayName(t: TargetAggregation): string {
  return t.aliases[0] || t.primary_name;
}

const TargetTable: Component<{ targets: TargetAggregation[] }> = (props) => {
  const ctx = useSettingsContext();
  const tzLabel = () => timezoneLabel(ctx.timezone());
  const { sortKey, sortDir, toggleSort } = useDashboardFilters();

  const UNCATEGORIZED_ID = "obj:__uncategorized__";

  // Client-side sort only for "equipment" (no backend support);
  // other sort keys are handled server-side, so just pass through.
  const sortedTargets = createMemo(() => {
    const key = sortKey();
    const dir = sortDir();
    if (key !== "equipment") return props.targets;

    const sorted = [...props.targets].sort((a, b) => {
      if (a.target_id === UNCATEGORIZED_ID) return 1;
      if (b.target_id === UNCATEGORIZED_ID) return -1;
      const cmp = a.equipment.join(" ").localeCompare(b.equipment.join(" "));
      return dir === "asc" ? cmp : -cmp;
    });
    return sorted;
  });

  // Dashboard-wide quality reference: median-of-session-medians + MAD for HFR
  // and eccentricity across every target currently shown. Both are roughly
  // filter-agnostic, unlike star count / ADU / SNR which SessionSummary mixes
  // across filters. madZ self-guards when n < MIN_GROUP, so a sparse page
  // yields no badges rather than noise.
  const qualityRefs = createMemo(() => {
    const hfr: (number | null)[] = [];
    const ecc: (number | null)[] = [];
    for (const t of props.targets) {
      for (const s of t.sessions) {
        hfr.push(s.median_hfr);
        ecc.push(s.median_eccentricity);
      }
    }
    return { hfr: baselineFrom(hfr), ecc: baselineFrom(ecc) };
  });

  const anomalyFn = createMemo(() => {
    const refs = qualityRefs();
    return (t: TargetAggregation) => anomalyFor(t, refs.hfr, refs.ecc);
  });

  const arrow = (key: SortKey) => {
    if (sortKey() !== key) return " \u2195";
    return sortDir() === "asc" ? " \u2191" : " \u2193";
  };

  const headerClass = (key: SortKey, align: "left" | "right" = "left") =>
    `text-${align} py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary cursor-pointer select-none hover:text-theme-text-primary transition-colors whitespace-nowrap${sortKey() === key ? " border-b-2 border-theme-accent" : ""}`;
  const plainHeaderClass = "text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap";

  const vis = () => ctx.columnVisibility();
  const targetCustomColumns = () => (ctx.customColumns() ?? []).filter(c => c.applies_to === "target");

  function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
    const v = vis() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} }, mosaic_table: { builtin: {}, custom: {} } };
    const updated = structuredClone(v);
    if (!updated.dashboard) updated.dashboard = { builtin: {}, custom: {} };
    if (!updated.dashboard[kind]) updated.dashboard[kind] = {};
    updated.dashboard[kind][key] = visible;
    ctx.saveColumnVisibility(updated);
  }

  return (
    <table class="w-full text-sm border-collapse">
      <thead>
        <tr
          class="sticky top-0 border-b border-theme-border-em z-10 text-theme-text-tertiary text-label uppercase tracking-wider hidden md:table-row"
          style={{
            // Opaque header bar that does NOT use .bg-theme-surface, so the glass
            // backdrop-filter rule never applies and the row is not re-composited
            // on every scroll frame. In glass themes the gradient base is fully
            // opaque; solid themes fall back to the surface token.
            "background-color": "var(--glass-gradient-from, var(--color-bg-surface))",
          }}
        >
          <th class={headerClass("name")} onClick={() => toggleSort("name")}>
            Target Name{arrow("name")}
          </th>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "designation")}>
            <th class={plainHeaderClass}>Designation</th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "palette")}>
            <th class={plainHeaderClass}>Palette</th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "integration")}>
            <th class={headerClass("integration", "right")} onClick={() => toggleSort("integration")}>
              Integration Time{arrow("integration")}
            </th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "equipment")}>
            <th class={headerClass("equipment")} onClick={() => toggleSort("equipment")}>
              Equipment Profile{arrow("equipment")}
            </th>
          </Show>
          <Show when={isColumnVisible(vis(), "dashboard", "builtin", "last_session")}>
            <th class={headerClass("lastSession", "right")} onClick={() => toggleSort("lastSession")}>
              Last Session ({tzLabel()}){arrow("lastSession")}
            </th>
          </Show>
          <For each={targetCustomColumns()}>
            {(col) => (
              <Show when={isColumnVisible(vis(), "dashboard", "custom", col.slug)}>
                <th class="py-2 px-3 text-right text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap">{col.name}</th>
              </Show>
            )}
          </For>
          <th class={plainHeaderClass}>
            <ColumnPicker
              table="dashboard"
              builtinColumns={[
                { key: "name", label: "Target Name", alwaysVisible: true },
                { key: "designation", label: "Designation" },
                { key: "palette", label: "Palette" },
                { key: "integration", label: "Integration Time" },
                { key: "equipment", label: "Equipment Profile" },
                { key: "last_session", label: "Last Session" },
              ]}
              customColumns={targetCustomColumns()}
              visibility={vis()}
              onToggle={handleColumnToggle}
            />
          </th>
        </tr>
      </thead>
      <tbody>
        <For each={sortedTargets()}>
          {(target) => (
            <TargetRow target={target} anomaly={anomalyFn()(target)} />
          )}
        </For>
      </tbody>
    </table>
  );
};

export default TargetTable;
