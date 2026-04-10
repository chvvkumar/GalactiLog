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
import StorageBreakdown from "../components/StorageBreakdown";
import IngestHistory from "../components/IngestHistory";

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
            <strong class="text-theme-text-primary">Overview</strong> shows total integration time, number of targets, sessions, and data quality averages (HFR, eccentricity).
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
          <li class="text-sm text-theme-text-secondary">
            <strong class="text-theme-text-primary">Storage Breakdown</strong> and <strong class="text-theme-text-primary">Ingest History</strong> show disk usage and how your catalog has grown.
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
          <>
            <StatsOverview
              overview={data().overview}
              avgHfr={data().data_quality.avg_hfr}
              avgEccentricity={data().data_quality.avg_eccentricity}
              bestHfr={data().data_quality.best_hfr}
            />

            <EquipmentPerformance combos={data().equipment_performance} />

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
              <FilterUsageChart usage={data().filter_usage} />
              <EquipmentInventory cameras={data().equipment.cameras} telescopes={data().equipment.telescopes} />
              <TopTargets targets={data().top_targets} />
            </div>

            <div class="flex items-center gap-2 mb-1">
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

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
              <StorageBreakdown
                fitsBytes={data().storage.fits_bytes}
                thumbnailBytes={data().storage.thumbnail_bytes}
                databaseBytes={data().storage.database_bytes}
              />
              <IngestHistory history={data().ingest_history} />
            </div>
          </>
        )}
      </Show>
    </div>
  );
};

export default StatisticsPage;
