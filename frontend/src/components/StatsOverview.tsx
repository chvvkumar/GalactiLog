import { Component } from "solid-js";
import type { OverviewStats } from "../types";
import { formatIntegration } from "../utils/format";

function formatSpan(start: string | null, end: string | null): string {
  if (!start || !end) return "\u2014";
  const s = new Date(start);
  const e = new Date(end);
  if (isNaN(s.getTime()) || isNaN(e.getTime())) return "\u2014";
  let months = (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth());
  if (e.getDate() < s.getDate()) months -= 1;
  if (months < 0) months = 0;
  const years = Math.floor(months / 12);
  const rem = months % 12;
  if (years === 0 && rem === 0) return "< 1 mo";
  if (years === 0) return `${rem} mo`;
  if (rem === 0) return `${years}y`;
  return `${years}y ${rem}mo`;
}

function formatSpanSubtitle(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  return `${start} → ${end}`;
}

const StatsOverview: Component<{
  overview: OverviewStats;
}> = (props) => {
  const cards = () => {
    const ov = props.overview;
    const avgSession = ov.session_count > 0
      ? formatIntegration(ov.total_integration_seconds / ov.session_count)
      : "\u2014";
    const avgPerTarget = ov.target_count > 0
      ? formatIntegration(ov.total_integration_seconds / ov.target_count)
      : "\u2014";
    return [
      { label: "Total Integration", subtitle: "all LIGHT frames", value: formatIntegration(ov.total_integration_seconds) },
      { label: "Total Frames", subtitle: "all LIGHT frames", value: ov.total_frames.toLocaleString() },
      { label: "Active Span", subtitle: formatSpanSubtitle(ov.first_capture_date, ov.last_capture_date), value: formatSpan(ov.first_capture_date, ov.last_capture_date) },
      { label: "Avg Session Length", subtitle: `${ov.session_count.toLocaleString()} sessions`, value: avgSession },
      { label: "Avg per Target", subtitle: `${ov.target_count.toLocaleString()} targets`, value: avgPerTarget },
    ];
  };

  return (
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {cards().map((c) => (
        <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 text-center">
          <div class="text-xs text-theme-text-secondary mb-1">{c.label}</div>
          <div class="text-theme-text-primary font-semibold text-xl">{c.value}</div>
          {c.subtitle && <div class="text-caption text-theme-text-tertiary italic mt-1">{c.subtitle}</div>}
        </div>
      ))}
    </div>
  );
};

export default StatsOverview;
