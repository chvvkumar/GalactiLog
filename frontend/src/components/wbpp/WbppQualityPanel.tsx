// Quality-filter panel for the WBPP export modal.
//
// Controlled: owns no config state. The parent computes the verdicts (it needs
// the exclude set for the generate payload and the footer byte math anyway) and
// hands them down, along with the session cache and display settings the preview
// table needs. Every edit here calls onConfigChange with the full next config.
//
// Default-collapsed: when the filter is off, only the checkbox row renders. The
// common case (filter off) costs one row.

import { For, Show, type JSX } from "solid-js";
import {
  HIGHER_IS_BETTER,
  METRIC_COLUMNS,
  RAW_METRICS,
  RAW_METRIC_LABELS,
  cellZ,
  type BaselineMode,
  type FilterMode,
  type FrameVerdict,
  type RawConstraint,
  type RawMetric,
} from "../../lib/wbppQualityFilter";
import { bandForZ, bandToCellClass } from "../../utils/frameQuality";
import { isFieldVisible } from "../../utils/displaySettings";
import type { DisplaySettings, FrameRecord, SessionDetail } from "../../api/types";
import HelpPopover from "../HelpPopover";
import Toggle from "../ui/Toggle";

export interface QualityConfig {
  mode: FilterMode;
  scoreThreshold: number;
  rawConstraints: RawConstraint[];
  baseline: BaselineMode;
}

export interface WbppQualityPanelProps {
  enabled: boolean;
  onEnabledChange: (on: boolean) => void;
  config: QualityConfig;
  onConfigChange: (next: QualityConfig) => void;
  verdicts: FrameVerdict[];
  totals: { total: number; copy: number; fail: number; unmeasured: number };
  loading: boolean;
  // Keyed by session date; supplies the baselines cellZ grades against. The
  // parent's cache is sparse and populates lazily, so a date may be absent.
  sessionDetails: Record<string, SessionDetail>;
  // isFieldVisible treats undefined as "quality + guiding visible", which is the
  // pre-settings-load default; the context getter is optional for the same reason.
  displaySettings: DisplaySettings | undefined;
}

const INPUT_CLASS =
  "text-xs px-2 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary";

// Shown inline while there are no constraints (nothing to look at, and the user
// has to be told what to add) and behind the help icon once there are (the rows
// then speak for themselves). One string so the two sites cannot drift.
const CONSTRAINTS_HELP =
  "Add one or more constraints. A frame is kept only if every metric it has data for passes. " +
  "Frames with none of the constrained metrics are unmeasured.";

const BASELINES: { value: BaselineMode; label: string }[] = [
  { value: "session", label: "This session" },
  { value: "rig", label: "Rig (catalog)" },
];

function verdictLabel(v: FrameVerdict): string {
  if (v.keep) return "Copy";
  return v.reason === "unmeasured" ? "Unmeasured" : "Exclude";
}

function verdictBadgeClass(v: FrameVerdict): string {
  if (v.keep) return "bg-theme-success/15 text-theme-success";
  return v.reason === "unmeasured"
    ? "bg-theme-warning/15 text-theme-warning"
    : "bg-theme-error/15 text-theme-error";
}

export default function WbppQualityPanel(props: WbppQualityPanelProps): JSX.Element {
  // Every edit rebuilds the whole config so the parent only ever sees a
  // complete object.
  const patch = (next: Partial<QualityConfig>) =>
    props.onConfigChange({ ...props.config, ...next });

  const excluded = () => props.totals.fail + props.totals.unmeasured;

  const cols = () =>
    METRIC_COLUMNS.filter((c) => isFieldVisible(props.displaySettings, c.group, c.field));

  // Band coloring only applies in score mode, matching the old preview: raw mode
  // compares literal values, so a baseline-relative band would be misleading.
  // A missing detail (sparse cache) yields no baseline, hence no band.
  const cellClass = (detail: SessionDetail | undefined, frame: FrameRecord, metric: RawMetric) => {
    if (props.config.mode !== "score" || !detail) return "text-theme-text-primary";
    return bandToCellClass(bandForZ(cellZ(detail, frame, metric, props.config.baseline)));
  };

  const addConstraint = () => {
    const used = new Set(props.config.rawConstraints.map((c) => c.metric));
    const next = RAW_METRICS.find((m) => !used.has(m)) ?? RAW_METRICS[0];
    patch({ rawConstraints: [...props.config.rawConstraints, { metric: next, value: 0 }] });
  };

  const updateConstraint = (i: number, delta: Partial<RawConstraint>) =>
    patch({
      rawConstraints: props.config.rawConstraints.map((c, idx) =>
        idx === i ? { ...c, ...delta } : c,
      ),
    });

  const removeConstraint = (i: number) =>
    patch({ rawConstraints: props.config.rawConstraints.filter((_, idx) => idx !== i) });

  return (
    <div class="space-y-3">
      <label class="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          class="w-3.5 h-3.5 rounded-[var(--radius-sm)] border-theme-border cursor-pointer"
          checked={props.enabled}
          onChange={(e) => props.onEnabledChange(e.currentTarget.checked)}
        />
        <span class="text-xs text-theme-text-primary">Skip low-quality light frames</span>
      </label>

      <Show when={props.enabled}>
        <div class="space-y-3 pl-5">
          <Show when={props.loading}>
            <p class="text-tiny text-theme-text-tertiary">Loading session frames…</p>
          </Show>

          {/* Live count line: "exclude" is fail + unmeasured, matching the
              exclude set the parent derives from the same verdicts.

              The scope rides on the noun. These counts cover every light in the
              selected sessions, while the footer counts only what sits under the
              selected folder levels, so the two totals are different numbers by
              design. Naming the domain next to the figures is what stops them
              reading as a contradiction. */}
          <p class="text-tiny text-theme-text-secondary">
            Skips <span class="tabular-nums text-theme-text-primary">{excluded()}</span> of{" "}
            <span class="tabular-nums text-theme-text-primary">{props.totals.total}</span> lights in
            the selected sessions (<span class="tabular-nums">{props.totals.fail}</span> below
            threshold, <span class="tabular-nums">{props.totals.unmeasured}</span> unmeasured).
            Calibration frames are always copied.
          </p>

          {/* Mode */}
          <div class="flex items-center gap-2">
            <span class="text-tiny text-theme-text-tertiary w-20">Mode</span>
            <select
              aria-label="Mode"
              class={INPUT_CLASS}
              value={props.config.mode}
              onChange={(e) => patch({ mode: e.currentTarget.value as FilterMode })}
            >
              <option value="score">Composite score</option>
              <option value="raw">Raw metrics (AND)</option>
            </select>
            {/* Describes scoreFrame + combinedScore + madZ as they actually are:
                three weighted axes, robust z against a per-train-and-filter
                baseline, MIN_GROUP = 8. Kept in step with the baseline popover
                below, which owns the session-vs-rig half of the story. */}
            <HelpPopover label="About the composite score" title="Composite score">
              <p>
                Three metrics feed the score: detected stars at weight 0.5, HFR at 0.25, and
                eccentricity at 0.25. FWHM, guiding RMS and ADU median never affect it.
              </p>
              <p>
                Each is graded against the baseline median for the frame's telescope, camera and
                filter, measured in MAD. Their weighted average sets the score: 50 sits at the
                baseline median, and the scale runs 0 to 100 across 3 MAD either side. Default 60
                keeps frames about 0.6 MAD better than the median, the cutoff that greens a row on
                the session table.
              </p>
              <p>
                Baseline sets what HFR and eccentricity compare against. Detected stars always
                compare within the session.
              </p>
              <p>
                A metric with no value drops out and the remaining weights rescale. A baseline needs
                8 frames sharing one telescope, camera and filter before it grades anything, so a
                short session scores nothing and its frames read as unmeasured.
              </p>
            </HelpPopover>
          </div>

          {/* Score mode: threshold */}
          <Show when={props.config.mode === "score"}>
            <div class="flex items-center gap-3">
              <span class="text-tiny text-theme-text-tertiary w-20">Keep ≥</span>
              <input
                type="range"
                aria-label="Keep score at or above"
                min="0"
                max="100"
                step="1"
                value={props.config.scoreThreshold}
                onInput={(e) => patch({ scoreThreshold: Number(e.currentTarget.value) })}
                class="flex-1"
              />
              <input
                type="number"
                aria-label="Score threshold"
                min="0"
                max="100"
                step="1"
                value={props.config.scoreThreshold}
                onInput={(e) => patch({ scoreThreshold: Number(e.currentTarget.value) })}
                class={`${INPUT_CLASS} w-16 text-right tabular-nums`}
              />
            </div>
            <p class="text-tiny text-theme-text-tertiary">
              Default 60 matches the green row cutoff on the session table.
            </p>
          </Show>

          {/* Raw mode: constraint builder */}
          <Show when={props.config.mode === "raw"}>
            <div class="space-y-2">
              <div class="flex items-center gap-1">
                <span class="text-tiny text-theme-text-tertiary">Constraints</span>
                <Show when={props.config.rawConstraints.length > 0}>
                  <HelpPopover label="About raw constraints" title="Raw metric constraints">
                    <p>{CONSTRAINTS_HELP}</p>
                  </HelpPopover>
                </Show>
              </div>
              <For each={props.config.rawConstraints}>
                {(c, i) => (
                  <div class="flex items-center gap-2">
                    <select
                      aria-label="Metric"
                      class={INPUT_CLASS}
                      value={c.metric}
                      onChange={(e) =>
                        updateConstraint(i(), { metric: e.currentTarget.value as RawMetric })
                      }
                    >
                      <For each={RAW_METRICS}>
                        {(m) => <option value={m}>{RAW_METRIC_LABELS[m]}</option>}
                      </For>
                    </select>
                    <span class="text-tiny text-theme-text-tertiary">
                      {HIGHER_IS_BETTER[c.metric] ? "≥" : "≤"}
                    </span>
                    <input
                      type="number"
                      aria-label={`${RAW_METRIC_LABELS[c.metric]} value`}
                      step="any"
                      class={`${INPUT_CLASS} w-24 tabular-nums`}
                      value={c.value}
                      onInput={(e) => updateConstraint(i(), { value: Number(e.currentTarget.value) })}
                    />
                    <button
                      type="button"
                      class="text-tiny text-theme-error hover:text-theme-error/80 cursor-pointer"
                      onClick={() => removeConstraint(i())}
                    >
                      Remove
                    </button>
                  </div>
                )}
              </For>
              <button
                type="button"
                class="text-tiny text-theme-accent hover:text-theme-accent-hover cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={addConstraint}
                disabled={props.config.rawConstraints.length >= RAW_METRICS.length}
              >
                + Add constraint
              </button>
              {/* Empty state: the one moment the user has nothing to read off
                  the rows is the one moment this must not be behind a click. */}
              <Show when={props.config.rawConstraints.length === 0}>
                <p class="text-tiny text-theme-text-tertiary">{CONSTRAINTS_HELP}</p>
              </Show>
            </div>
          </Show>

          {/* Baseline */}
          <div class="flex items-center gap-2">
            <span class="text-tiny text-theme-text-tertiary w-20">Baseline</span>
            <div class="flex gap-1">
              <For each={BASELINES}>
                {(b) => (
                  <Toggle
                    active={props.config.baseline === b.value}
                    onClick={() => patch({ baseline: b.value })}
                  >
                    {b.label}
                  </Toggle>
                )}
              </For>
            </div>
            <HelpPopover label="About the baseline" title="Baseline">
              <p>
                Baseline affects the composite-score mode and the preview colors only. Raw-metric
                thresholds compare each frame's literal value, not the baseline.
              </p>
            </HelpPopover>
          </div>

          {/* Per-frame preview */}
          <Show when={props.verdicts.length > 0}>
            {/* This table is how the threshold gets chosen, so it has to show
                enough rows to see a pattern in. The cap is rem-based because the
                row height is: the text tiers scale with the root font-size preset,
                and a px cap would show fewer and fewer rows as the preset grows.
                Capped rather than unbounded so the modal body stays the scroller.

                whitespace-nowrap sits on the table, not the cells: every column
                here is an atom (a date, a number, a verdict, a truncated file
                name), none of them may break, and putting it at the one place
                they all inherit from means a new column cannot forget it. */}
            <div class="max-h-[22rem] overflow-y-auto bg-theme-elevated rounded-[var(--radius-sm)] p-2">
              <table class="w-full text-tiny whitespace-nowrap">
                <thead>
                  <tr class="text-theme-text-tertiary border-b border-theme-border">
                    <th class="text-left py-1 px-1.5 font-normal">File</th>
                    <th class="text-left py-1 px-1.5 font-normal">Session</th>
                    <th class="text-center py-1 px-1.5 font-normal">Filter</th>
                    <For each={cols()}>
                      {(c) => <th class="text-right py-1 px-1.5 font-normal">{c.label}</th>}
                    </For>
                    <th class="text-right py-1 px-1.5 font-normal">Score</th>
                    <th class="text-right py-1 px-1.5 font-normal">Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={props.verdicts}>
                    {(v) => {
                      // Sparse cache: an unloaded date has no baselines, so the row
                      // renders its values uncolored rather than throwing.
                      const detail = () => props.sessionDetails[v.sessionDate];
                      return (
                        <tr class="border-b border-theme-border/30">
                          <td class="py-0.5 px-1.5 text-theme-text-secondary font-mono truncate max-w-[14rem]">
                            {v.frame.file_name}
                          </td>
                          <td class="py-0.5 px-1.5 text-theme-text-tertiary tabular-nums">
                            {v.sessionDate}
                          </td>
                          <td class="py-0.5 px-1.5 text-theme-text-primary text-center">
                            {v.frame.filter_used ?? "—"}
                          </td>
                          <For each={cols()}>
                            {(c) => {
                              const raw = () => v.frame[c.metric];
                              return (
                                <td
                                  class={`py-0.5 px-1.5 text-right tabular-nums ${cellClass(detail(), v.frame, c.metric)}`}
                                >
                                  {raw() != null ? c.format(raw()!) : "—"}
                                </td>
                              );
                            }}
                          </For>
                          <td class="py-0.5 px-1.5 text-right tabular-nums text-theme-text-secondary">
                            {v.score != null ? v.score.toFixed(0) : "—"}
                          </td>
                          <td class="py-0.5 px-1.5 text-right">
                            <span
                              class={`px-1.5 py-0.5 rounded-[var(--radius-sm)] text-tiny font-medium ${verdictBadgeClass(v)}`}
                            >
                              {verdictLabel(v)}
                            </span>
                          </td>
                        </tr>
                      );
                    }}
                  </For>
                </tbody>
              </table>
            </div>
          </Show>
        </div>
      </Show>
    </div>
  );
}
