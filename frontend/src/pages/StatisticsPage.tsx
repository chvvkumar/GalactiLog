import { Component, Show, createSignal } from "solid-js";
import { useStats } from "../store/stats";
import { useSettingsContext } from "../components/SettingsProvider";
import { contentWidthClass } from "../utils/format";
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
                class={`px-3 py-1 text-xs rounded ${timelineView() === "timeline" ? "bg-theme-accent text-white" : "bg-theme-bg text-theme-text-secondary border border-theme-border"}`}
                onClick={() => setTimelineView("timeline")}
              >
                Timeline
              </button>
              <button
                class={`px-3 py-1 text-xs rounded ${timelineView() === "calendar" ? "bg-theme-accent text-white" : "bg-theme-bg text-theme-text-secondary border border-theme-border"}`}
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
