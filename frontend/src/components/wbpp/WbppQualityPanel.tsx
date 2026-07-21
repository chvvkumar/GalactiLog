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
  ECC_PRESETS,
  METRIC_DEFS,
  cellZ,
  emptyConstraintFor,
  formatMetric,
  type ConstraintOp,
  type FrameVerdict,
  type MetricKey,
  type QualityConfig,
  type RawConstraint,
} from "../../lib/wbppQualityFilter";
import { bandForZ, bandToCellClass } from "../../utils/frameQuality";
import HelpPopover from "../HelpPopover";
import { ClickableFilePath } from "../ClickableFilePath";
import type { PreviewFile, PreviewMetaEntry } from "../FilePreviewModal";
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
  { key: "verdict", label: "Verdict", align: "center" },
  { key: "filter", label: "Filter", align: "center" },
  ...METRIC_ORDER.map((m): ColumnDef => ({ key: m, label: SHORT_LABEL[m], align: "right" })),
  { key: "file", label: "File", align: "left" },
  { key: "session", label: "Session", align: "right" },
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

// Spinner buttons are suppressed: at 20px tall they render as sub-10px click
// targets, and thresholds are typed values, not stepped ones. Arrow keys and
// scroll still step by the input's `step`.
const CHIP_INPUT_CLASS =
  "h-5 px-1 text-tiny tabular-nums text-right bg-theme-input border border-theme-border " +
  "rounded-[var(--radius-sm)] text-theme-text-primary outline-none focus:border-theme-accent " +
  "[appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none " +
  "[&::-webkit-inner-spin-button]:appearance-none";

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

  const addConstraint = (metric: MetricKey) =>
    setConstraints([...props.config.constraints, emptyConstraintFor(metric)]);

  const patchConstraint = (metric: MetricKey, delta: Partial<RawConstraint>) =>
    setConstraints(
      props.config.constraints.map((c) => (c.metric === metric ? { ...c, ...delta } : c)),
    );

  // The x button disables rather than deletes: the chip drops back to a ghost
  // that still shows its value, and re-clicking re-enables without resetting.
  const disableConstraint = (metric: MetricKey) => patchConstraint(metric, { enabled: false });

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

  const cellClass = (v: FrameVerdict, metric: MetricKey): string => {
    const detail = props.sessionDetails[v.sessionDate];
    if (!detail) return "text-theme-text-primary";
    return bandToCellClass(bandForZ(cellZ(detail, v.frame, metric, props.config.baseline)));
  };

  const arrow = (key: SortKey) => (sortKey() === key ? (sortAsc() ? "▲" : "▼") : null);

  // The preview modal's metadata strip mirrors this row's cells: verdict,
  // filter, the five metrics with the same band coloring and failure marks,
  // then the session date. The modal's own neutral text is used where the
  // table would fall back to its default color.
  const stripClass = (cls: string): string | undefined =>
    cls === "text-theme-text-primary" ? undefined : cls;

  const metaFor = (v: FrameVerdict): PreviewMetaEntry[] => {
    const kept = effectiveKeep(v);
    const verdictEntry: PreviewMetaEntry = kept
      ? { label: "Verdict", value: "Copy", class: "text-theme-success", title: "Copy" }
      : v.reason === "unmeasured"
        ? {
            label: "Verdict",
            value: "Unmeasured",
            class: "text-theme-warning",
            title: "Unmeasured: none of the constrained metrics recorded",
          }
        : {
            label: "Verdict",
            value: "Exclude",
            class: "text-theme-error",
            title: `Exclude: ${v.failures.map((f) => f.text).join(", ")}`,
          };
    const metricEntries = METRIC_ORDER.map((metric): PreviewMetaEntry => {
      const raw = metricValue(v.frame, metric);
      const failure = props.enabled ? v.failures.find((f) => f.metric === metric) : undefined;
      return {
        label: SHORT_LABEL[metric],
        value: raw != null ? formatMetric(metric, raw) : "—",
        class: failure ? "text-theme-error font-medium" : stripClass(cellClass(v, metric)),
        marked: !!failure,
        title: failure?.text,
      };
    });
    return [
      verdictEntry,
      { label: "Filter", value: v.frame.filter_used ?? "—" },
      ...metricEntries,
      { label: "Session", value: v.sessionDate },
    ];
  };

  // Same order as the rendered rows, so a row's index addresses its own entry
  // and ←/→ in the modal walks the table in its current sort.
  const previewFiles = createMemo<PreviewFile[]>(() =>
    sortedVerdicts().map((v) => ({
      imageId: v.frame.image_id,
      filePath: v.frame.file_path,
      thumbnailUrl: v.frame.thumbnail_url,
      meta: metaFor(v),
    })),
  );

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
          <HelpPopover label="About quality filters" title="Quality filters">
            <p>
              Each chip is an absolute threshold. A frame is excluded when any enabled
              chip with a value rejects it. A chip without a value filters nothing. A
              frame missing a metric is not judged on that metric; a frame missing all
              constrained metrics is counted as unmeasured, not excluded.
            </p>
            <p>
              Eccentricity presets: 0.55 keeps stars that read round (axis ratio 0.84),
              0.65 marks the edge of visible elongation (0.76), 0.75 admits clearly
              elongated stars (0.66) and suits salvaging poor nights.
            </p>
            <p>
              Cell colors compare each frame to the selected baseline (this session or
              the rig catalog) and are informational; only the chips decide the verdict.
            </p>
          </HelpPopover>

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
                            that value rather than starting over. A held chip
                            with no value yet shows nothing extra. */}
                        <Show when={c()?.value != null ? c() : undefined}>
                          {(held) => (
                            <span class="tabular-nums opacity-70">
                              {OP_GLYPH[held().op]} {formatMetric(metric, held().value!)}
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
                          aria-label={`${SHORT_LABEL[metric]} comparison`}
                          class="h-5 text-tiny bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-theme-text-secondary cursor-pointer"
                          value={active().op}
                          onChange={(e) =>
                            patchConstraint(metric, { op: e.currentTarget.value as ConstraintOp })
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
                          placeholder="value"
                          value={active().value ?? ""}
                          onInput={(e) => {
                            // An emptied input reverts the chip to valueless
                            // (gates nothing) rather than pinning the last
                            // number the user was trying to delete.
                            const text = e.currentTarget.value.trim();
                            if (text === "") {
                              if (active().value != null) patchConstraint(metric, { value: null });
                              return;
                            }
                            const n = parseFloat(text);
                            if (Number.isFinite(n) && n !== active().value)
                              patchConstraint(metric, { value: n });
                          }}
                          onChange={(e) => {
                            const text = e.currentTarget.value.trim();
                            if (text !== "" && !Number.isFinite(parseFloat(text)))
                              e.currentTarget.value =
                                active().value != null ? String(active().value) : "";
                          }}
                        />
                        {/* Eccentricity is the one metric with absolute,
                            rig-independent meaning, so it gets quick-fill
                            presets; see ECC_PRESETS for the rationale. */}
                        <Show when={metric === "ecc"}>
                          <For each={ECC_PRESETS}>
                            {(p) => (
                              <button
                                type="button"
                                title={`${p.label}: ecc ≤ ${p.value}`}
                                class="h-5 px-1.5 text-tiny tabular-nums rounded-[var(--radius-sm)] border cursor-pointer"
                                classList={{
                                  "border-theme-accent/60 bg-theme-accent/20 text-theme-accent":
                                    active().value === p.value && active().op === "lte",
                                  "border-theme-border bg-theme-input text-theme-text-tertiary hover:text-theme-text-primary":
                                    !(active().value === p.value && active().op === "lte"),
                                }}
                                onClick={() => patchConstraint(metric, { value: p.value, op: "lte" })}
                              >
                                {p.value}
                              </button>
                            )}
                          </For>
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
                  {
                    value: "session" as const,
                    label: "This session",
                    title:
                      "Cell colors grade each frame against its own session's statistics only.",
                  },
                  {
                    value: "rig" as const,
                    label: "Overall",
                    title:
                      "Cell colors grade each frame against this rig's full catalog history, not just these sessions.",
                  },
                ]}
              >
                {(b, i) => (
                  <button
                    type="button"
                    title={b.title}
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
          <div class="max-h-[36rem] overflow-y-auto border border-t-0 border-theme-border rounded-b-[var(--radius-md)] bg-theme-elevated">
            <table class="w-full text-tiny whitespace-nowrap">
              <thead>
                <tr>
                  <For each={COLUMNS}>
                    {(col) => (
                      <th
                        class={`sticky top-0 z-20 bg-theme-elevated py-1.5 px-1.5 font-normal cursor-pointer select-none shadow-[inset_0_-1px_0_var(--color-border-default)] ${ALIGN_CLASS[col.align]}`}
                        classList={{
                          // Metric headers carry extra right padding matching
                          // the glyph slot in their cells, so the header label
                          // right-aligns with the digits, not with the slot.
                          "pr-[1.125rem]": METRIC_ORDER.includes(col.key as MetricKey),
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
                  {(v, i) => (
                    <tr class="border-b border-theme-border/30 last:border-b-0">
                      {/* Icon-only verdict: the glyph says THAT a frame is
                          dropped; the marked metric cells say which gates
                          fired. Hover carries the full failure sentences.
                          With the filter off every row reads Copy. */}
                      <td class="py-0.5 px-1.5 text-center">
                        <span
                          class={`inline-block text-[10px] leading-none cursor-default ${
                            effectiveKeep(v)
                              ? "text-theme-success"
                              : v.reason === "unmeasured"
                                ? "text-theme-warning"
                                : "text-theme-error"
                          }`}
                          title={
                            effectiveKeep(v)
                              ? "Copy"
                              : v.reason === "unmeasured"
                                ? "Unmeasured: none of the constrained metrics recorded"
                                : `Exclude: ${v.failures.map((f) => f.text).join(", ")}`
                          }
                        >
                          {effectiveKeep(v) ? "●" : v.reason === "unmeasured" ? "◐" : "✕"}
                        </span>
                      </td>
                      <td class="py-0.5 px-1.5 text-theme-text-primary text-center">
                        {v.frame.filter_used ?? "—"}
                      </td>
                      <For each={METRIC_ORDER}>
                        {(metric) => {
                          const raw = () => metricValue(v.frame, metric);
                          const failure = () =>
                            props.enabled
                              ? v.failures.find((f) => f.metric === metric)
                              : undefined;
                          // Every metric cell renders the same fixed-width
                          // trailing slot, glyph or not, so the digits keep one
                          // right edge across kept and excluded rows.
                          return (
                            <td
                              class={`py-0.5 px-1.5 text-right tabular-nums ${
                                failure() ? "text-theme-error font-medium" : cellClass(v, metric)
                              }`}
                              title={failure()?.text}
                            >
                              {raw() != null ? formatMetric(metric, raw()!) : "—"}
                              <span class="inline-block w-3 pl-0.5 text-left align-middle text-[9px] leading-none">
                                {failure() ? "✕" : ""}
                              </span>
                            </td>
                          );
                        }}
                      </For>
                      {/* The file column absorbs whatever width the fitted
                          columns leave over, so the table still fills the
                          panel without stretching the data columns. */}
                      <td class="w-full max-w-0 py-0.5 px-1.5">
                        <ClickableFilePath
                          imageId={v.frame.image_id}
                          filePath={v.frame.file_path}
                          thumbnailUrl={v.frame.thumbnail_url}
                          display={v.frame.file_name}
                          files={previewFiles()}
                          index={i()}
                          class="max-w-full font-mono align-middle"
                        />
                      </td>
                      <td class="py-0.5 px-1.5 text-right text-theme-text-tertiary tabular-nums">
                        {v.sessionDate}
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
        Filters apply to light frames only. All other files are copied unchanged.{" "}
        <span class="text-theme-error">✕</span> marks the value that excluded a frame; hover it
        for the threshold.
      </p>
    </div>
  );
}
