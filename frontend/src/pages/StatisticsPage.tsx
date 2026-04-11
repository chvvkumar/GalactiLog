import { Component, Show, createSignal } from "solid-js";
import { useStats } from "../store/stats";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
import SettingsHelpSection from "../components/settings/SettingsHelpSection";
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
    <div class={`p-4 space-y-4 ${contentWidthClass(ctx.contentWidth())}`}>
      <h1 class="text-xl font-semibold tracking-tight text-theme-text-primary">Statistics</h1>

      <SettingsHelpSection tabId="statistics">
        <p class="text-sm text-theme-text-secondary">
          The Statistics page provides an overview of your entire imaging catalog with aggregate metrics and visualizations.
        </p>
        <ul class="list-disc list-inside space-y-1">
          <li class="text-sm text-theme-text-secondary">
            <strong class="text-theme-text-primary">Overview</strong> shows total integration time, frame count, how long the catalog has been active, average session length (with multi-rig nights counted per rig), and average integration per target.
          </li>
          <li class="text-sm text-theme-text-secondary">
            <strong class="text-theme-text-primary">Equipment Performance</strong> compares imaging quality across telescope/camera combinations.
          </li>
          <li class="text-sm text-theme-text-secondary">
            <strong class="text-theme-text-primary">Filter Usage</strong>, <strong class="text-theme-text-primary">Equipment Inventory</strong>, and <strong class="text-theme-text-primary">Top Targets</strong> give quick breakdowns of what you image most.
          </li>
          <li class="text-sm text-theme-text-secondary">
            <strong class="text-theme-text-primary">Timeline</strong> and <strong class="text-theme-text-primary">Calendar</strong> views show imaging activity over time - useful for tracking seasonal patterns and productivity.
          </li>
        </ul>
      </SettingsHelpSection>

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
              <h2 class="text-sm font-semibold text-theme-text-primary">Overview</h2>
              <StatsOverview overview={data().overview} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h2 class="text-sm font-semibold text-theme-text-primary">Equipment Performance</h2>
              <EquipmentPerformance combos={data().equipment_performance} />
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h2 class="text-sm font-semibold text-theme-text-primary">Breakdowns</h2>
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
                <FilterUsageChart usage={data().filter_usage} />
                <EquipmentInventory cameras={data().equipment.cameras} telescopes={data().equipment.telescopes} />
                <TopTargets targets={data().top_targets} />
              </div>
            </section>

            <section class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h2 class="text-sm font-semibold text-theme-text-primary">Imaging Activity</h2>
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
                <ImagingTimeline
                  monthly={data().timeline_monthly}
                  weekly={data().timeline_weekly}
                  daily={data().timeline_daily}
                />
              </Show>
              <Show when={timelineView() === "calendar"}>
                <ImagingCalendar />
              </Show>
            </section>
          </div>
        )}
      </Show>
    </div>
  );
};

export default StatisticsPage;
