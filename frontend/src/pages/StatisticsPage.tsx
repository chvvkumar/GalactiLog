import { Component, Show } from "solid-js";
import { useStats } from "../store/stats";
import DatabaseOverview from "../components/DatabaseOverview";
import EquipmentInventory from "../components/EquipmentInventory";
import FilterUsageChart from "../components/FilterUsageChart";
import ImagingTimeline from "../components/ImagingTimeline";
import TopTargets from "../components/TopTargets";
import StorageBreakdown from "../components/StorageBreakdown";
import IngestHistory from "../components/IngestHistory";

const StatisticsPage: Component = () => {
  const { stats } = useStats();

  return (
    <div class="p-4 space-y-4 max-w-7xl mx-auto">

      <Show when={stats.loading && !stats()}>
        <div class="text-center text-theme-text-secondary py-8">Loading analytics...</div>
      </Show>

      <Show when={stats.error && !stats()}>
        <div class="text-center text-theme-error py-8">Failed to load stats</div>
      </Show>

      <Show when={stats()}>
        {(data) => (
          <>
            <DatabaseOverview
              overview={data().overview}
              avgHfr={data().data_quality.avg_hfr}
              avgEccentricity={data().data_quality.avg_eccentricity}
              bestHfr={data().data_quality.best_hfr}
            />

            <div class="grid grid-cols-3 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
              <FilterUsageChart usage={data().filter_usage} />
              <EquipmentInventory cameras={data().equipment.cameras} telescopes={data().equipment.telescopes} />
              <TopTargets targets={data().top_targets} />
            </div>

            <ImagingTimeline timeline={data().timeline} />

            <div class="grid grid-cols-2 gap-4 [&>*]:border [&>*]:border-theme-border [&>*]:rounded-[var(--radius-md)] [&>*]:shadow-[var(--shadow-sm)]">
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
