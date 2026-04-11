import { Component } from "solid-js";
import type { OverviewStats } from "../types";
import StorageBreakdown from "./StorageBreakdown";

import { formatIntegration } from "../utils/format";

const StatsOverview: Component<{
  overview: OverviewStats;
  storage: { fits_bytes: number; thumbnail_bytes: number; database_bytes: number };
}> = (props) => {
  const cards = () => [
    { label: "Total Integration", subtitle: "all LIGHT frames", value: formatIntegration(props.overview.total_integration_seconds) },
    { label: "Resolved Targets", subtitle: "via SIMBAD", value: String(props.overview.target_count) },
    { label: "Total Frames", subtitle: "all LIGHT frames", value: props.overview.total_frames.toLocaleString() },
  ];

  return (
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-stretch">
      {cards().map((c) => (
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 text-center flex flex-col justify-center">
          <div class="text-xs text-theme-text-secondary mb-1">{c.label}</div>
          <div class="text-theme-text-primary font-semibold text-xl">{c.value}</div>
          {c.subtitle && <div class="text-caption text-theme-text-tertiary italic mt-1">{c.subtitle}</div>}
        </div>
      ))}
      <StorageBreakdown
        fitsBytes={props.storage.fits_bytes}
        thumbnailBytes={props.storage.thumbnail_bytes}
        databaseBytes={props.storage.database_bytes}
      />
    </div>
  );
};

export default StatsOverview;
