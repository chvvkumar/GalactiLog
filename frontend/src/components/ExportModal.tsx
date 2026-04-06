import { Component, For, Show, createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { ExportResponse, SessionOverview } from "../types";

import { formatIntegration } from "../utils/format";

function generateTextExport(data: ExportResponse): string {
  const lines: string[] = [];
  const name = data.catalog_id ? `${data.target_name} (${data.catalog_id})` : data.target_name;
  lines.push(name);

  const equipStr = data.equipment.map((e) => `${e.telescope || "?"} + ${e.camera || "?"}`).join(", ");
  lines.push(`Equipment: ${equipStr}`);
  lines.push(`Dates: ${data.dates.join(", ")}`);
  lines.push("");

  // Aggregate by (filter, exposure) across all dates
  const byFilterExp = new Map<string, { frames: number; exposure: number; total: number; gain: number | null; temp: number | null }>();
  for (const row of data.rows) {
    const key = `${row.filter_name}|${row.exposure}`;
    const existing = byFilterExp.get(key);
    if (existing) {
      existing.frames += row.frames;
      existing.total += row.total_seconds;
    } else {
      byFilterExp.set(key, {
        frames: row.frames,
        exposure: row.exposure,
        total: row.total_seconds,
        gain: row.gain,
        temp: row.sensor_temp,
      });
    }
  }

  for (const [key, info] of byFilterExp) {
    const filter = key.split("|")[0];
    let line = `${filter}: ${info.frames} x ${info.exposure}s (${formatIntegration(info.total)})`;
    if (info.gain != null) line += ` | Gain ${info.gain}`;
    if (info.temp != null) line += ` | ${info.temp}\u00b0C`;
    lines.push(line);
  }

  lines.push("");
  lines.push(`Total integration: ${formatIntegration(data.total_integration_seconds)}`);
  return lines.join("\n");
}

function generateCsvExport(data: ExportResponse): string {
  const headers = ["date", "filter", "number", "duration", "binning", "gain", "sensorCooling", "fNumber", "bortle", "meanSqm", "meanFwhm", "temperature"];
  const lines = [headers.join(",")];

  for (const row of data.rows) {
    const vals = [
      row.date,
      row.astrobin_filter_id ?? "",
      row.frames,
      row.exposure,
      "",  // binning
      row.gain ?? "",
      row.sensor_temp ?? "",
      "",  // fNumber
      data.bortle ?? "",
      row.sky_quality ?? "",
      row.fwhm ?? "",
      row.ambient_temp ?? "",
    ];
    lines.push(vals.join(","));
  }

  return lines.join("\n");
}

interface Props {
  targetId: string;
  targetName: string;
  sessions: SessionOverview[];
  onClose: () => void;
}

const ExportModal: Component<Props> = (props) => {
  const [selectedDates, setSelectedDates] = createSignal<Set<string>>(
    new Set(props.sessions.map((s) => s.session_date))
  );
  const [copied, setCopied] = createSignal(false);

  const sessionList = () => selectedDates().size > 0 ? [...selectedDates()] : undefined;
  const [exportData] = createResource(
    () => sessionList()?.join(",") ?? "all",
    () => api.getExport(props.targetId, sessionList()),
  );

  const toggleDate = (date: string) => {
    const s = new Set(selectedDates());
    if (s.has(date)) s.delete(date);
    else s.add(date);
    setSelectedDates(s);
  };

  const toggleAll = () => {
    if (selectedDates().size === props.sessions.length) {
      setSelectedDates(new Set());
    } else {
      setSelectedDates(new Set(props.sessions.map((s) => s.session_date)));
    }
  };

  const copyText = async () => {
    const data = exportData();
    if (!data) return;
    await navigator.clipboard.writeText(generateTextExport(data));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadCsv = () => {
    const data = exportData();
    if (!data) return;
    const csv = generateCsvExport(data);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${props.targetName.replace(/[^a-zA-Z0-9]/g, "_")}_acquisition.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border flex items-center justify-between">
          <h2 class="text-sm font-medium text-theme-text-primary">Export — {props.targetName}</h2>
          <button class="text-theme-text-secondary hover:text-theme-text-primary" onClick={props.onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
        </div>

        <div class="p-4 space-y-3">
          {/* Session selection */}
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide">Sessions</span>
              <button class="text-xs text-theme-accent hover:underline" onClick={toggleAll}>
                {selectedDates().size === props.sessions.length ? "Deselect all" : "Select all"}
              </button>
            </div>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <For each={props.sessions}>
                {(s) => (
                  <label class="flex items-center gap-2 text-xs text-theme-text-primary cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedDates().has(s.session_date)}
                      onChange={() => toggleDate(s.session_date)}
                    />
                    {s.session_date} — {formatIntegration(s.integration_seconds)} ({s.frame_count} frames)
                  </label>
                )}
              </For>
            </div>
          </div>

          {/* Preview */}
          <Show when={exportData()}>
            {(data) => (
              <div class="bg-theme-elevated rounded p-3 text-xs text-theme-text-primary font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                {generateTextExport(data())}
              </div>
            )}
          </Show>

          <Show when={exportData.loading}>
            <div class="bg-theme-elevated rounded p-3 space-y-2">
              <div class="h-3 w-3/4 bg-theme-surface rounded animate-pulse" />
              <div class="h-3 w-1/2 bg-theme-surface rounded animate-pulse" />
              <div class="h-3 w-2/3 bg-theme-surface rounded animate-pulse" />
              <div class="h-3 w-1/3 bg-theme-surface rounded animate-pulse" />
            </div>
          </Show>
        </div>

        <div class="p-4 border-t border-theme-border flex gap-2 justify-end">
          <button
            class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary disabled:opacity-50"
            disabled={!exportData() || selectedDates().size === 0}
            onClick={copyText}
          >
            {copied() ? "Copied!" : "Copy to Clipboard"}
          </button>
          <button
            class="text-xs px-3 py-1.5 bg-theme-accent text-white rounded hover:opacity-90 transition-opacity disabled:opacity-50"
            disabled={!exportData() || selectedDates().size === 0}
            onClick={downloadCsv}
          >
            Download CSV
          </button>
        </div>
      </div>
    </div>
  );
};

export default ExportModal;
