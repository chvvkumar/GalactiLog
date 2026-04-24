import { Component, Show, createSignal } from "solid-js";
import { useStats } from "../store/stats";
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

const StatisticsPage: Component = () => {
  const { stats } = useStats();
  const ctx = useSettingsContext();
  const [timelineView, setTimelineView] = createSignal<"timeline" | "calendar">("timeline");

  return (
    <div class={`page-enter p-4 space-y-4 ${contentWidthClass(ctx.contentWidth())}`}>
      <div class="flex items-center gap-2">
        <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Statistics</h1>
        <HelpPopover>
          <p class="text-sm text-theme-text-secondary">
            Aggregate metrics across the full catalog. Four sections: Overview, Equipment Performance, Breakdowns, and Imaging Activity. Open the popover next to each section for details.
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
              <StatsOverview overview={data().overview} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Equipment Performance</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Metric summaries grouped by telescope, camera, and filter combination. Use this to compare how gear performs. Example: median HFR per telescope, frames captured per camera.
                  </p>
                </HelpPopover>
              </div>
              <EquipmentPerformance combos={data().equipment_performance} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Breakdowns</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Three breakdown cards. Filter Usage shows integration time per filter. Equipment Inventory lists telescopes, cameras, and filters seen across the catalog. Top Targets lists the targets with the most integration time. Example: confirm that Ha dominates your narrowband hours.
                  </p>
                </HelpPopover>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
                <FilterUsageChart usage={data().filter_usage} />
                <EquipmentInventory cameras={data().equipment.cameras} telescopes={data().equipment.telescopes} />
                <TopTargets targets={data().top_targets} />
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
