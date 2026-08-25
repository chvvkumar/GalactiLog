import { Component, Show, createSignal } from "solid-js";
import { A } from "@solidjs/router";
import { useQuery } from "@tanstack/solid-query";
import { useStats } from "../store/stats";
import { guidingStats } from "../api/guidingStats";
import { queryKeys } from "../api/queryKeys";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import HelpPopover from "../components/HelpPopover";
import StatsOverview from "../components/StatsOverview";
import EquipmentInventory from "../components/EquipmentInventory";
import EquipmentPerformance from "../components/EquipmentPerformance";
import FilterUsageChart from "../components/FilterUsageChart";
import ImagingTimeline from "../components/ImagingTimeline";
import ImagingCalendar from "../components/ImagingCalendar";
import TopTargets from "../components/TopTargets";
import GuidingScorecard, { GuidingEmptyNotice } from "../components/GuidingScorecard";
import GuidingAltitude from "../components/GuidingAltitude";

const StatisticsPage: Component = () => {
  const { stats } = useStats();
  const ctx = useSettingsContext();
  const [timelineView, setTimelineView] = createSignal<"timeline" | "calendar">("timeline");
  const [guidingOpen, setGuidingOpen] = createSignal(false);
  const guidingQuery = useQuery(() => ({
    queryKey: queryKeys.guidingStats(),
    queryFn: ({ signal }) => guidingStats.get(signal),
  }));

  return (
    <div class={`page-enter p-4 space-y-4 ${contentWidthClass(ctx.contentWidth())}`}>
      <div class="flex items-center gap-2">
        <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Statistics</h1>
        <HelpPopover>
          <p class="text-sm text-theme-text-secondary">
            Aggregate metrics across the full catalog. Five sections: Overview, Equipment Performance, Guiding, Breakdowns, and Imaging Activity. Open the popover next to each section for details.
          </p>
        </HelpPopover>
      </div>

      <Show when={stats.loading && !stats()}>
        <div class="text-center text-theme-text-secondary py-8">Loading analytics...</div>
      </Show>

      <Show when={stats.error && !stats()}>
        <div class="text-center text-theme-error py-8">Failed to load stats</div>
      </Show>

      <Show when={stats()}>
        {(data) => (
          <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Overview</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Catalog-wide totals: integration time, frame count, catalog age (days since the earliest frame), session count, and average integration per target. Example: "42 targets, 187 sessions, 312 hours total" at a glance.
                  </p>
                </HelpPopover>
              </div>
              <StatsOverview overview={data().overview} storage={data().storage} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Equipment Performance</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Metric summaries grouped by telescope, camera, and filter combination. HFR is measured in pixels and is only comparable within a single optical train; use FWHM in arcseconds to compare performance across telescopes. Example: median FWHM per rig, frames captured per camera.
                  </p>
                </HelpPopover>
              </div>
              <EquipmentPerformance combos={data().equipment_performance} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <button
                  class="flex items-center gap-2 text-sm font-semibold text-theme-text-primary cursor-pointer"
                  aria-expanded={guidingOpen()}
                  onClick={() => setGuidingOpen(!guidingOpen())}
                >
                  <h2>Guiding</h2>
                  <span class={`text-caption transition-transform ${guidingOpen() ? "" : "-rotate-90"}`}>&#9660;</span>
                </button>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    PHD2 guide-log comparisons per rig, in two panels: a scorecard of RMS, settling and guided hours for each rig, and RMS split by the target altitude band it was captured at. A rig is the telescope mapped to the PHD2 profile, so cameras under one telescope share a value. RMS figures are frame-count weighted over sessions of at least 100 guide frames, and are not comparable across different guide exposures. Sessions from unmapped profiles are excluded; <A href="/settings?tab=equipment#phd2-profiles" class="text-theme-accent hover:underline">map profiles in Settings</A>.
                  </p>
                </HelpPopover>
              </div>
              <Show when={guidingOpen()}>
                <Show when={guidingQuery.isPending}>
                  <div class="text-center text-theme-text-secondary py-4 text-sm">Loading...</div>
                </Show>
                <Show when={guidingQuery.isError}>
                  <div class="text-sm text-theme-error">Failed to load guiding stats</div>
                </Show>
                <Show when={guidingQuery.data}>
                  {(g) => (
                    <Show
                      when={g().rigs.length > 0}
                      fallback={<GuidingEmptyNotice unmapped={g().unmapped_session_count} />}
                    >
                      <div class="space-y-4">
                        <GuidingScorecard rigs={g().rigs} />
                        <GuidingAltitude altitudeBands={g().altitude_bands} />
                      </div>
                    </Show>
                  )}
                </Show>
              </Show>
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Breakdowns</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Three breakdown cards. Equipment Inventory lists telescopes, cameras, and filters seen across the catalog. Below it, Filter Usage shows integration time per filter and Top Targets lists the targets with the most integration time. Example: confirm that Ha dominates your narrowband hours.
                  </p>
                </HelpPopover>
              </div>
              <div class="space-y-4">
                <div class="[&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
                  <EquipmentInventory cameras={data().equipment.cameras} telescopes={data().equipment.telescopes} />
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
                  <FilterUsageChart usage={data().filter_usage} />
                  <TopTargets targets={data().top_targets} />
                </div>
              </div>
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Imaging Activity</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Temporal view of when imaging happened. Timeline is a chronological strip across months, weeks, and days. Calendar is a month grid marking imaging nights. Example: spot long gaps between sessions, or identify productive weather windows.
                  </p>
                </HelpPopover>
              </div>
              <div class="flex items-center gap-2">
                <button
                  class={`px-3 py-1 text-xs rounded ${timelineView() === "timeline" ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "bg-theme-bg text-theme-text-secondary border border-theme-border hover:bg-theme-hover"}`}
                  onClick={() => setTimelineView("timeline")}
                >
                  Timeline
                </button>
                <button
                  class={`px-3 py-1 text-xs rounded ${timelineView() === "calendar" ? "bg-theme-elevated text-theme-text-primary font-medium border border-theme-border-em" : "bg-theme-bg text-theme-text-secondary border border-theme-border hover:bg-theme-hover"}`}
                  onClick={() => setTimelineView("calendar")}
                >
                  Calendar
                </button>
              </div>
              <Show when={timelineView() === "timeline"}>
                <div class="tab-fade-in">
                  <ImagingTimeline
                    monthly={data().timeline_monthly}
                    weekly={data().timeline_weekly}
                    daily={data().timeline_daily}
                  />
                </div>
              </Show>
              <Show when={timelineView() === "calendar"}>
                <div class="tab-fade-in">
                  <ImagingCalendar />
                </div>
              </Show>
            </section>
          </div>
        )}
      </Show>
    </div>
  );
};

export default StatisticsPage;
