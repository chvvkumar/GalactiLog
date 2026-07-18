// Quality-filter panel for the WBPP export modal.
//
// Controlled: owns no config state. The parent computes the verdicts (it needs
// the exclude set for the generate payload and the footer byte math anyway) and
// hands them down along with the session cache the preview table grades
// against. Every edit here calls onConfigChange with a complete next config.
//
// Layout is a chips toolbar fused to the preview table: one row holding the
// enable checkbox, five metric chips (ghost "+ HFR" when inactive, inline
// pill-editor when active), the kept/skipped tally, and the baseline segmented
// control; the sortable frame table hangs directly beneath it.

import { For, Show, createMemo, createSignal, type JSX } from "solid-js";
import {
  DEFAULT_SESSION_K,
  METRIC_DEFS,
  bandForThreshold,
  cellZ,
  defaultConstraintFor,
  formatMetric,
  sessionThresholdRows,
  thresholdBandToCellClass,
  type ConstraintOp,
  type FrameVerdict,
  type MetricKey,
  type QualityConfig,
  type RawConstraint,
  type ThresholdScope,
} from "../../lib/wbppQualityFilter";
import { bandForZ, bandToCellClass } from "../../utils/frameQuality";
import WbppQualityHelp from "./WbppQualityHelp";
import type { FrameRecord, SessionDetail } from "../../api/types";

export interface WbppQualityPanelProps {
  enabled: boolean;
  onEnabledChange: (on: boolean) => void;
  config: QualityConfig;
  onConfigChange: (next: QualityConfig) => void;
  verdicts: FrameVerdict[];
  loading: boolean;
  // Keyed by session date; supplies the baselines the cell coloring grades
  // against. The parent's cache is sparse and populates lazily, so a date may
  // be absent -- an absent detail renders its row uncolored.
  sessionDetails: Record<string, SessionDetail>;
}

// Chip order is the table's metric-column order; both read from this one list
// so the toolbar and the table can never disagree about what exists.
const METRIC_ORDER: MetricKey[] = ["hfr", "ecc", "fwhm", "stars", "rms"];

// Chips and column headers use the compact names; METRIC_DEFS labels are the
// long forms ("Eccentricity", "Detected stars") and would not fit a pill.
const SHORT_LABEL: Record<MetricKey, string> = {
  hfr: "HFR",
  ecc: "Ecc",
  fwhm: "FWHM",
  stars: "Stars",
  rms: "RMS",
};

const OP_GLYPH: Record<ConstraintOp, string> = { lte: "≤", gte: "≥" };

type SortKey = "file" | "session" | "filter" | "verdict" | MetricKey;

interface ColumnDef {
  key: SortKey;
  label: string;
  align: "left" | "center" | "right";
}

const COLUMNS: ColumnDef[] = [
  { key: "file", label: "File", align: "left" },
  { key: "session", label: "Session", align: "left" },
  { key: "filter", label: "Filter", align: "center" },
  ...METRIC_ORDER.map((m): ColumnDef => ({ key: m, label: SHORT_LABEL[m], align: "right" })),
  { key: "verdict", label: "Verdict", align: "right" },
];

const ALIGN_CLASS: Record<ColumnDef["align"], string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

const GHOST_CHIP_CLASS =
  "inline-flex items-center gap-1 h-6 px-2.5 rounded-full border border-dashed border-theme-border " +
  "text-tiny text-theme-text-tertiary hover:border-theme-text-tertiary hover:text-theme-text-secondary " +
  "cursor-pointer whitespace-nowrap";

const ACTIVE_CHIP_CLASS =
  "inline-flex items-center gap-1.5 h-6 pl-2.5 pr-1 rounded-full border border-theme-accent/40 " +
  "bg-theme-accent/15 text-tiny text-theme-text-primary whitespace-nowrap";

const CHIP_INPUT_CLASS =
  "h-5 px-1 text-tiny tabular-nums text-right bg-theme-input border border-theme-border " +
  "rounded-[var(--radius-sm)] text-theme-text-primary outline-none focus:border-theme-accent";

function metricValue(frame: FrameRecord, metric: MetricKey): number | null {
  const raw = frame[METRIC_DEFS[metric].field];
  return typeof raw === "number" ? raw : null;
}

export default function WbppQualityPanel(props: WbppQualityPanelProps): JSX.Element {
  // null means "no user choice yet": chronological by frame timestamp, the
  // order the night actually happened in.
  const [sortKey, setSortKey] = createSignal<SortKey | null>(null);
  const [sortAsc, setSortAsc] = createSignal(true);

  const toggleSort = (key: SortKey) => {
    if (sortKey() === key) setSortAsc(!sortAsc());
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const constraintFor = (metric: MetricKey): RawConstraint | undefined =>
    props.config.constraints.find((c) => c.metric === metric);

  const setConstraints = (constraints: RawConstraint[]) =>
    props.onConfigChange({ ...props.config, constraints });

  // The selected session dates, recovered from the verdicts the parent computed
  // over exactly those dates. sessionDetails is a sparse cache that may hold
  // more sessions than are selected, so it cannot be the source.
  const selectedDates = createMemo(() => [...new Set(props.verdicts.map((v) => v.sessionDate))]);

  const addConstraint = (metric: MetricKey) =>
    setConstraints([
      ...props.config.constraints,
      defaultConstraintFor(metric, props.sessionDetails, selectedDates(), props.config),
    ]);

  const patchConstraint = (metric: MetricKey, delta: Partial<RawConstraint>) =>
    setConstraints(
      props.config.constraints.map((c) => (c.metric === metric ? { ...c, ...delta } : c)),
    );

  // The x button disables rather than deletes: the chip drops back to a ghost
  // that still shows its value, and re-clicking re-enables without resetting.
  const disableConstraint = (metric: MetricKey) => patchConstraint(metric, { enabled: false });

  // A typed value is a manual absolute: the per-filter seeds and their
  // provenance stop applying, or the narrower group thresholds would silently
  // keep overruling the number the user just entered. Same for a flipped op.
  const overrideValue = (metric: MetricKey, value: number) =>
    patchConstraint(metric, { value, groupValues: undefined, seed: undefined });
  const overrideOp = (metric: MetricKey, op: ConstraintOp) =>
    patchConstraint(metric, { op, groupValues: undefined, seed: undefined });

  // Switching to per-session locks the comparison to the metric's polarity
  // (the derived median +/- k*MAD threshold is only meaningful in that
  // direction) and gives k its default; switching back restores the chip's
  // absolute-value behavior with whatever value/seeds it still holds.
  const setScope = (metric: MetricKey, scope: ThresholdScope) => {
    if (scope === "session") {
      const op: ConstraintOp = METRIC_DEFS[metric].betterWhen === "high" ? "gte" : "lte";
      patchConstraint(metric, {
        scope,
        op,
        k: constraintFor(metric)?.k ?? DEFAULT_SESSION_K,
      });
    } else {
      patchConstraint(metric, { scope });
    }
  };

  // Global-mode auto-seeded constraints, for the provenance badges.
  const seededConstraints = () =>
    props.config.constraints.filter(
      (c) => c.enabled && (c.scope ?? "global") === "global" && c.seed,
    );

  // Per-session constraints, for the per-night threshold rows.
  const sessionScopedConstraints = () =>
    props.config.constraints.filter((c) => c.enabled && c.scope === "session");

  // With the master toggle off every frame copies, so the table and the tally
  // must say so rather than keep grading against a filter that is not running.
  const effectiveKeep = (v: FrameVerdict): boolean => !props.enabled || v.keep;

  const keptCount = () => props.verdicts.filter(effectiveKeep).length;
  const skippedCount = () => props.verdicts.length - keptCount();

  const chronological = (a: FrameVerdict, b: FrameVerdict) =>
    a.frame.timestamp < b.frame.timestamp ? -1 : a.frame.timestamp > b.frame.timestamp ? 1 : 0;

  const sortedVerdicts = createMemo(() => {
    const rows = [...props.verdicts];
    const key = sortKey();
    if (key === null) return rows.sort(chronological);
    const dir = sortAsc() ? 1 : -1;

    const compare = (a: FrameVerdict, b: FrameVerdict): number => {
      switch (key) {
        case "file":
          return a.frame.file_name.localeCompare(b.frame.file_name) * dir;
        case "session":
          return a.sessionDate.localeCompare(b.sessionDate) * dir;
        case "filter":
          return (a.frame.filter_used ?? "").localeCompare(b.frame.filter_used ?? "") * dir;
        case "verdict": {
          // Groups, not values: Exclude first (flipped when descending),
          // chronological within each group so the excluded frames read as
          // the night unfolded.
          const rank = (v: FrameVerdict) => (effectiveKeep(v) ? 1 : 0);
          const byGroup = (rank(a) - rank(b)) * dir;
          return byGroup !== 0 ? byGroup : chronological(a, b);
        }
        default: {
          // Metric column. Missing values sink to the bottom in either
          // direction: a frame with no measurement is not "smallest".
          const av = metricValue(a.frame, key);
          const bv = metricValue(b.frame, key);
          if (av == null && bv == null) return chronological(a, b);
          if (av == null) return 1;
          if (bv == null) return -1;
          return (av - bv) * dir;
        }
      }
    };
    return rows.sort((a, b) => {
      const c = compare(a, b);
      return c !== 0 ? c : chronological(a, b);
    });
  });

  /**
   * Cell color speaks the chip's language: a metric with an ACTIVE constraint
   * is colored relative to the threshold that actually judges this frame
   * (its own group's, and in per-session mode its own night's) -- red exactly
   * when that gate excludes it, amber when it passes within the watch margin.
   * Metrics without an active constraint keep the baseline MAD-band coloring
   * the session table uses; there is no gate to disagree with.
   */
  const cellClass = (v: FrameVerdict, metric: MetricKey): string => {
    const detail = props.sessionDetails[v.sessionDate];
    const c = constraintFor(metric);
    if (props.enabled && c?.enabled) {
      const raw = metricValue(v.frame, metric);
      if (raw == null) return "text-theme-text-primary";
      return thresholdBandToCellClass(
        bandForThreshold(c, raw, { detail, groupKey: v.groupKey }),
      );
    }
    if (!detail) return "text-theme-text-primary";
    return bandToCellClass(bandForZ(cellZ(detail, v.frame, metric, props.config.baseline)));
  };

  const arrow = (key: SortKey) => (sortKey() === key ? (sortAsc() ? "▲" : "▼") : null);

  return (
    <div class="space-y-2">
      {/* Toolbar: enable checkbox, metric chips, kept/skipped tally, baseline.
          Fused to the table below via the shared border and split radius. */}
      <div>
        <div class="flex items-center flex-wrap gap-2 px-2.5 py-2 bg-theme-elevated border border-theme-border rounded-t-[var(--radius-md)]">
          <label class="flex items-center gap-2 cursor-pointer shrink-0">
            <input
              type="checkbox"
              class="w-3.5 h-3.5 rounded-[var(--radius-sm)] border-theme-border cursor-pointer"
              checked={props.enabled}
              onChange={(e) => props.onEnabledChange(e.currentTarget.checked)}
            />
            <span class="text-xs text-theme-text-primary">Enable filters</span>
          </label>

          {/* Help glyph sits with the header, outside the inert wrapper so the
              guide stays reachable even while the filter is off. */}
          <WbppQualityHelp />

          {/* Everything except the master checkbox goes inert while the filter
              is off; the checkbox stays live so it can turn things back on. */}
          <div
            class="flex items-center flex-wrap gap-2 flex-1 min-w-0"
            classList={{ "opacity-50 pointer-events-none": !props.enabled }}
          >
            <For each={METRIC_ORDER}>
              {(metric) => {
                const c = () => constraintFor(metric);
                return (
                  <Show
                    when={c()?.enabled ? c() : undefined}
                    fallback={
                      <button
                        type="button"
                        class={GHOST_CHIP_CLASS}
                        onClick={() =>
                          c() ? patchConstraint(metric, { enabled: true }) : addConstraint(metric)
                        }
                      >
                        <span class="opacity-70">+</span>
                        <span>{SHORT_LABEL[metric]}</span>
                        {/* A disabled constraint keeps its value; showing it on
                            the ghost is what tells the user a click restores
                            that value rather than starting over. */}
                        <Show when={c()}>
                          {(held) => (
                            <span class="tabular-nums opacity-70">
                              {OP_GLYPH[held().op]} {formatMetric(metric, held().value)}
                            </span>
                          )}
                        </Show>
                      </button>
                    }
                  >
                    {(active) => (
                      <span class={ACTIVE_CHIP_CLASS}>
                        <span class="font-medium text-theme-accent">
                          {SHORT_LABEL[metric]}
                        </span>
                        <select
                          aria-label={`${SHORT_LABEL[metric]} threshold scope`}
                          title="Global: one absolute threshold. Per-session: each night derives its own threshold from its own frames (median + k·1.4826·MAD, per filter)."
                          class="h-5 text-tiny bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-theme-text-secondary cursor-pointer"
                          value={active().scope ?? "global"}
                          onChange={(e) =>
                            setScope(metric, e.currentTarget.value as ThresholdScope)
                          }
                        >
                          <option value="global">Global</option>
                          <option value="session">Per-session</option>
                        </select>
                        <Show
                          when={(active().scope ?? "global") === "global"}
                          fallback={
                            <>
                              {/* Per-session: the one control is k, the sigma
                                  multiplier every night's threshold derives
                                  from. The absolute values live in the rows
                                  under the toolbar. */}
                              <span class="text-theme-text-tertiary">k</span>
                              <input
                                type="number"
                                aria-label={`${SHORT_LABEL[metric]} sigma multiplier`}
                                title="Each session's threshold = its own median + k · 1.4826 · MAD (per filter). Lower k cuts harder."
                                class={`${CHIP_INPUT_CLASS} w-12`}
                                step={0.1}
                                min={0.1}
                                value={active().k ?? DEFAULT_SESSION_K}
                                onInput={(e) => {
                                  const n = parseFloat(e.currentTarget.value);
                                  if (Number.isFinite(n) && n > 0 && n !== active().k)
                                    patchConstraint(metric, { k: n });
                                }}
                                onChange={(e) => {
                                  if (!Number.isFinite(parseFloat(e.currentTarget.value)))
                                    e.currentTarget.value = String(active().k ?? DEFAULT_SESSION_K);
                                }}
                              />
                            </>
                          }
                        >
                          <select
                            aria-label={`${SHORT_LABEL[metric]} comparison`}
                            class="h-5 text-tiny bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-theme-text-secondary cursor-pointer"
                            value={active().op}
                            onChange={(e) =>
                              overrideOp(metric, e.currentTarget.value as ConstraintOp)
                            }
                          >
                            <option value="lte">≤</option>
                            <option value="gte">≥</option>
                          </select>
                          <input
                            type="number"
                            aria-label={`${SHORT_LABEL[metric]} threshold`}
                            class={`${CHIP_INPUT_CLASS} w-16`}
                            step={10 ** -METRIC_DEFS[metric].decimals}
                            value={active().value}
                            onInput={(e) => {
                              const n = parseFloat(e.currentTarget.value);
                              if (Number.isFinite(n) && n !== active().value)
                                overrideValue(metric, n);
                            }}
                            onChange={(e) => {
                              if (!Number.isFinite(parseFloat(e.currentTarget.value)))
                                e.currentTarget.value = String(active().value);
                            }}
                          />
                        </Show>
                        <button
                          type="button"
                          aria-label={`Disable ${SHORT_LABEL[metric]} constraint`}
                          class="w-4 h-4 inline-flex items-center justify-center rounded-full text-theme-text-tertiary hover:text-theme-error hover:bg-theme-error/15 cursor-pointer"
                          onClick={() => disableConstraint(metric)}
                        >
                          ×
                        </button>
                      </span>
                    )}
                  </Show>
                );
              }}
            </For>

            {/* Right-aligned pair: live tally, then the baseline control. */}
            <span class="ml-auto inline-flex items-baseline gap-1.5 bg-theme-input border border-theme-border rounded-full px-3 py-0.5 text-tiny text-theme-text-tertiary whitespace-nowrap">
              <span class="tabular-nums font-semibold text-theme-success">{keptCount()}</span>
              <span>kept</span>
              <span class="text-theme-border">/</span>
              <span class="tabular-nums font-semibold text-theme-error">{skippedCount()}</span>
              <span>skipped</span>
              <span class="text-theme-text-secondary">
                of <span class="tabular-nums">{props.verdicts.length}</span>
              </span>
            </span>

            <div class="inline-flex border border-theme-border rounded-[var(--radius-sm)] overflow-hidden shrink-0">
              <For
                each={[
                  { value: "session" as const, label: "This session" },
                  { value: "rig" as const, label: "Rig (catalog)" },
                ]}
              >
                {(b, i) => (
                  <button
                    type="button"
                    class="h-6 px-2.5 text-tiny cursor-pointer"
                    classList={{
                      "bg-theme-accent/20 text-theme-accent font-medium":
                        props.config.baseline === b.value,
                      "bg-theme-input text-theme-text-tertiary hover:text-theme-text-primary":
                        props.config.baseline !== b.value,
                      "border-l border-theme-border": i() > 0,
                    }}
                    onClick={() => props.onConfigChange({ ...props.config, baseline: b.value })}
                  >
                    {b.label}
                  </button>
                )}
              </For>
            </div>
          </div>
        </div>

        {/* Disclosure strip, fused between toolbar and table: seed provenance
            for auto-seeded global chips (which filter/night supplied the
            number), and one row per night+filter for per-session chips. */}
        <Show
          when={
            props.enabled && (seededConstraints().length > 0 || sessionScopedConstraints().length > 0)
          }
        >
          <div class="border border-t-0 border-theme-border bg-theme-elevated px-2.5 py-1.5 space-y-1">
            <For each={seededConstraints()}>
              {(c) => (
                <p class="text-tiny text-theme-text-tertiary">
                  <span class="font-medium text-theme-text-secondary">{SHORT_LABEL[c.metric]}</span>
                  {" seeded from "}
                  <span class="text-theme-text-secondary">{c.seed!.filter}</span>
                  {" · "}
                  <span class="tabular-nums">{c.seed!.date ?? "rig catalog"}</span>
                  {" · n="}
                  <span class="tabular-nums">{c.seed!.n}</span>
                  <Show when={c.seed!.pooledFilters.length > 0}>
                    <span
                      class="text-theme-warning"
                      title="These filters have fewer than 8 baseline frames, so they use the pooled threshold instead of their own."
                    >
                      {" · pooled: "}
                      {c.seed!.pooledFilters.join(", ")}
                    </span>
                  </Show>
                </p>
              )}
            </For>
            <For each={sessionScopedConstraints()}>
              {(c) => (
                <div class="flex items-baseline flex-wrap gap-x-3 gap-y-0.5 text-tiny">
                  <span class="font-medium text-theme-text-secondary">
                    {SHORT_LABEL[c.metric]} per session
                  </span>
                  <For each={sessionThresholdRows(c, props.sessionDetails, selectedDates())}>
                    {(row) => (
                      <span
                        class="tabular-nums whitespace-nowrap"
                        classList={{
                          "text-theme-warning": row.fallback,
                          "text-theme-text-tertiary": !row.fallback,
                        }}
                        title={
                          row.fallback
                            ? `${row.date} ${row.filter}: fewer than 8 measured frames in this group, so the pooled global threshold applies.`
                            : `${row.date} ${row.filter}: threshold derived from this night's own frames.`
                        }
                      >
                        {row.date.slice(5)} {row.filter} {OP_GLYPH[c.op]}
                        {formatMetric(c.metric, row.threshold)}
                        {row.fallback ? "*" : ""} · n={row.n} · keep {row.keep} / cut {row.cut}
                      </span>
                    )}
                  </For>
                </div>
              )}
            </For>
          </div>
        </Show>

        {/* Preview table, fused under the toolbar. The wrap is the scroller so
            the sticky header pins inside it; the thead cells carry a solid
            elevated background plus an inset shadow instead of a border-bottom,
            because collapsed borders scroll away from sticky cells. */}
        <Show
          when={props.verdicts.length > 0}
          fallback={
            <div class="border border-t-0 border-theme-border rounded-b-[var(--radius-md)] bg-theme-elevated px-3 py-2">
              <p class="text-tiny text-theme-text-tertiary">
                {props.loading ? "Loading session frames…" : "No light frames in the selected sessions."}
              </p>
            </div>
          }
        >
          <div class="max-h-[22rem] overflow-y-auto border border-t-0 border-theme-border rounded-b-[var(--radius-md)] bg-theme-elevated">
            <table class="w-full text-tiny whitespace-nowrap">
              <thead>
                <tr>
                  <For each={COLUMNS}>
                    {(col) => (
                      <th
                        class={`sticky top-0 z-20 bg-theme-elevated py-1.5 px-1.5 font-normal cursor-pointer select-none shadow-[inset_0_-1px_0_var(--color-border-default)] ${ALIGN_CLASS[col.align]}`}
                        classList={{
                          "text-theme-text-primary": sortKey() === col.key,
                          "text-theme-text-tertiary hover:text-theme-text-secondary":
                            sortKey() !== col.key,
                        }}
                        onClick={() => toggleSort(col.key)}
                      >
                        {col.label}
                        <Show when={arrow(col.key)}>
                          {(a) => <span class="ml-0.5 text-theme-accent text-[9px]">{a()}</span>}
                        </Show>
                      </th>
                    )}
                  </For>
                </tr>
              </thead>
              <tbody>
                <For each={sortedVerdicts()}>
                  {(v) => (
                    <tr class="border-b border-theme-border/30 last:border-b-0">
                      <td class="py-0.5 px-1.5 text-theme-text-secondary font-mono truncate max-w-[14rem]">
                        {v.frame.file_name}
                      </td>
                      <td class="py-0.5 px-1.5 text-theme-text-tertiary tabular-nums">
                        {v.sessionDate}
                      </td>
                      <td class="py-0.5 px-1.5 text-theme-text-primary text-center">
                        {v.frame.filter_used ?? "—"}
                      </td>
                      <For each={METRIC_ORDER}>
                        {(metric) => {
                          const raw = () => metricValue(v.frame, metric);
                          return (
                            <td
                              class={`py-0.5 px-1.5 text-right tabular-nums ${cellClass(v, metric)}`}
                            >
                              {raw() != null ? formatMetric(metric, raw()!) : "—"}
                            </td>
                          );
                        }}
                      </For>
                      {/* The pill says THAT a frame is dropped; the reason
                          beside it says which gate fired and by how much.
                          With the filter off every row reads Copy. */}
                      <td class="py-0.5 px-1.5 text-right">
                        <Show when={props.enabled && !v.keep && v.failedBy}>
                          <span class="mr-1.5 font-mono text-theme-text-tertiary">{v.failedBy}</span>
                        </Show>
                        <span
                          class={`px-1.5 py-0.5 rounded-full text-tiny font-medium ${
                            effectiveKeep(v)
                              ? "bg-theme-success/15 text-theme-success"
                              : v.reason === "unmeasured"
                                ? "bg-theme-warning/15 text-theme-warning"
                                : "bg-theme-error/15 text-theme-error"
                          }`}
                        >
                          {effectiveKeep(v)
                            ? "Copy"
                            : v.reason === "unmeasured"
                              ? "Unmeasured"
                              : "Exclude"}
                        </span>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
        </Show>
      </div>

      <p class="text-tiny text-theme-text-tertiary">
        Filters apply to light frames only. All other files are copied unchanged.
      </p>
    </div>
  );
}
