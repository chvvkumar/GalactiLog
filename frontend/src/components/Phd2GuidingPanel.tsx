import { For, Show, createSignal, type Component } from "solid-js";
import { formatArcsec } from "../utils/format";
import { formatSecondsShort } from "../utils/phd2Format";
import type { Phd2NightSummary } from "../api/types";

/**
 * Night-level PHD2 rollup inside an expanded session card. Markup mirrors the
 * Session Insights accordion and the Session Summary metric strip so the card
 * reads as one surface; the chart lives separately in Phd2GuideGraph.
 */
const Phd2GuidingPanel: Component<{ summary: Phd2NightSummary }> = (props) => {
  const [open, setOpen] = createSignal(true);
  const s = () => props.summary;

  return (
    <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
      <button
        class="flex justify-between items-center w-full text-xs py-2 px-3 hover:bg-theme-hover rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors cursor-pointer"
        classList={{ "text-theme-text-primary": open(), "text-theme-text-secondary": !open() }}
        onClick={() => setOpen((v) => !v)}
      >
        <span class="font-semibold border-l-2 border-theme-accent pl-2">
          Guiding (PHD2){" "}
          <span class="text-theme-text-tertiary font-normal">
            ({s().session_count} {s().session_count === 1 ? "session" : "sessions"})
          </span>
        </span>
        <svg
          class={`w-3.5 h-3.5 transition-transform duration-200 ${open() ? "rotate-180" : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
        </svg>
      </button>
      <div class={`grid transition-[grid-template-rows] duration-200 ${open() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
        <div class="overflow-hidden">
          <div class="px-3 pb-3 space-y-1.5">
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-label">
              <span>
                <span class="text-theme-text-tertiary">RMS:</span>{" "}
                <span class="font-bold text-metric-guiding">{formatArcsec(s().rms_total_arcsec)}</span>
              </span>
              <span>
                <span class="text-theme-text-tertiary">RA:</span>{" "}
                <span class="font-bold text-theme-text-primary">{formatArcsec(s().rms_ra_arcsec)}</span>
              </span>
              <span>
                <span class="text-theme-text-tertiary">Dec:</span>{" "}
                <span class="font-bold text-theme-text-primary">{formatArcsec(s().rms_dec_arcsec)}</span>
              </span>
              <span>
                <span class="text-theme-text-tertiary">Sessions:</span>{" "}
                <span class="font-bold text-theme-text-primary">{s().session_count}</span>
                <Show when={s().gated_session_count > 0}>
                  <span class="text-theme-text-tertiary"> ({s().gated_session_count} too short to grade)</span>
                </Show>
              </span>
            </div>
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-label">
              <span>
                <span class="text-theme-text-tertiary">Star lost:</span>{" "}
                <span class="font-bold text-theme-text-primary">{s().drop_count}</span>
                <Show when={s().drop_count > 0}>
                  <span class="text-theme-text-tertiary">
                    {" "}({formatSecondsShort(s().unguided_seconds)} unguided, longest run {s().max_drop_run})
                  </span>
                </Show>
              </span>
              <span>
                <span class="text-theme-text-tertiary">Dithers:</span>{" "}
                <span class="font-bold text-theme-text-primary">{s().dither_count}</span>
              </span>
              <span>
                <span class="text-theme-text-tertiary">Settle:</span>{" "}
                <span class="font-bold text-theme-text-primary">
                  {s().settle_median_s !== null ? `${s().settle_median_s!.toFixed(1)}s` : "—"}
                </span>
                <Show when={s().settle_failed_count > 0}>
                  <span class="text-theme-warning"> · {s().settle_failed_count} failed</span>
                </Show>
              </span>
            </div>
            <Show when={s().cal_issues.length > 0}>
              <div class="flex flex-wrap items-center gap-1.5 pt-0.5">
                <span class="text-tiny text-theme-text-tertiary">Calibration:</span>
                <For each={s().cal_issues}>
                  {(issue) => (
                    <span class="text-tiny px-1.5 py-0.5 rounded bg-theme-warning/15 text-theme-warning border border-theme-warning/20">
                      {issue}
                    </span>
                  )}
                </For>
              </div>
            </Show>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Phd2GuidingPanel;
