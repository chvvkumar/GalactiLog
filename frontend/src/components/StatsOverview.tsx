import { Component } from "solid-js";
import type { OverviewStats } from "../types";
import { formatIntegration, formatBytes } from "../utils/format";

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
  storage?: { fits_bytes: number; fits_disk_bytes: number; thumbnail_bytes: number; database_bytes: number };
}> = (props) => {
  const cards = (): { label: string; subtitle: string; value: string; title?: string }[] => {
    const ov = props.overview;
    const avgRigSession = ov.rig_session_count > 0
      ? formatIntegration(ov.total_integration_seconds / ov.rig_session_count)
      : "\u2014";
    const avgPerTarget = ov.target_count > 0
      ? formatIntegration(ov.total_integration_seconds / ov.target_count)
      : "\u2014";
    return [
      { label: "Total Integration", subtitle: "all LIGHT frames", value: formatIntegration(ov.total_integration_seconds) },
      { label: "Total Frames", subtitle: "all LIGHT frames", value: ov.total_frames.toLocaleString() },
      { label: "Catalogued Size", subtitle: props.storage ? `${formatBytes(props.storage.fits_disk_bytes)} on disk` : "", value: props.storage ? formatBytes(props.storage.fits_bytes) : "—", title: "Catalogued Size: total size of FITS files recorded in the catalog (sum of file sizes in the database; reflects the include-calibration setting). The 'on disk' figure is the actual disk usage of the FITS directory measured with du, including files not yet catalogued such as excluded calibration frames." },
      { label: "Active Span", subtitle: formatSpanSubtitle(ov.first_capture_date, ov.last_capture_date), value: formatSpan(ov.first_capture_date, ov.last_capture_date) },
      { label: "Avg Rig-Session Length", subtitle: `${ov.rig_session_count.toLocaleString()} rig-sessions`, value: avgRigSession, title: "A rig-session is one night imaged with one telescope+camera combination; a single night imaged with two rigs counts as two rig-sessions here. This differs from the Imaging Calendar and per-target session counts, which count distinct imaging nights." },
      { label: "Avg per Target", subtitle: `${ov.target_count.toLocaleString()} resolved targets`, value: avgPerTarget },
    ];
  };

  return (
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards().map((c) => (
        <div title={c.title} class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 text-center">
          <div class="text-xs text-theme-text-secondary mb-1">{c.label}</div>
          <div class="text-theme-text-primary font-semibold text-xl">{c.value}</div>
          {c.subtitle && <div class="text-[10px] leading-tight whitespace-nowrap text-theme-text-tertiary italic mt-1">{c.subtitle}</div>}
        </div>
      ))}
    </div>
  );
};

export default StatsOverview;
