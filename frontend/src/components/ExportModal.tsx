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

  for (const info of aggregateByFilterExposure(data)) {
    let line = `${info.filter}: ${info.frames} x ${info.exposure}s (${formatIntegration(info.total)})`;
    if (info.gain != null) line += ` | Gain ${info.gain}`;
    if (info.temp != null) line += ` | ${info.temp}\u00b0C`;
    lines.push(line);
  }

  lines.push("");
  lines.push(`Total integration: ${formatIntegration(data.total_integration_seconds)}`);
  return lines.join("\n");
}

interface AggregatedRow {
  filter: string;
  frames: number;
  exposure: number;
  total: number;
  gain: number | null;
  temp: number | null;
}

function aggregateByFilterExposure(data: ExportResponse): AggregatedRow[] {
  const byKey = new Map<string, AggregatedRow>();
  for (const row of data.rows) {
    const key = `${row.filter_name}|${row.exposure}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.frames += row.frames;
      existing.total += row.total_seconds;
    } else {
      byKey.set(key, {
        filter: row.filter_name,
        frames: row.frames,
        exposure: row.exposure,
        total: row.total_seconds,
        gain: row.gain,
        temp: row.sensor_temp,
      });
    }
  }
  return [...byKey.values()];
}

function generateMarkdownExport(data: ExportResponse): string {
  const lines: string[] = [];
  const name = data.catalog_id ? `${data.target_name} (${data.catalog_id})` : data.target_name;
  lines.push(`# ${name}`);
  lines.push("");

  const equipStr = data.equipment.map((e) => `${e.telescope || "?"} + ${e.camera || "?"}`).join(", ");
  lines.push(`**Equipment:** ${equipStr}`);
  lines.push(`**Dates:** ${data.dates.join(", ")}`);
  lines.push(`**Total integration:** ${formatIntegration(data.total_integration_seconds)}`);
  lines.push("");

  lines.push("| Filter | Frames | Exposure | Total | Gain | Temp |");
  lines.push("|---|---|---|---|---|---|");
  for (const info of aggregateByFilterExposure(data)) {
    const gain = info.gain != null ? String(info.gain) : "";
    const temp = info.temp != null ? `${info.temp}\u00b0C` : "";
    lines.push(`| ${info.filter} | ${info.frames} | ${info.exposure}s | ${formatIntegration(info.total)} | ${gain} | ${temp} |`);
  }

  return lines.join("\n");
}

function generateBbcodeExport(data: ExportResponse): string {
  const lines: string[] = [];
  const name = data.catalog_id ? `${data.target_name} (${data.catalog_id})` : data.target_name;
  lines.push(`[b]${name}[/b]`);

  const equipStr = data.equipment.map((e) => `${e.telescope || "?"} + ${e.camera || "?"}`).join(", ");
  lines.push(`Equipment: ${equipStr}`);
  lines.push(`Dates: ${data.dates.join(", ")}`);
  lines.push("");

  lines.push("[list]");
  for (const info of aggregateByFilterExposure(data)) {
    let line = `[*]${info.filter}: ${info.frames} x ${info.exposure}s (${formatIntegration(info.total)})`;
    if (info.gain != null) line += ` | Gain ${info.gain}`;
    if (info.temp != null) line += ` | ${info.temp}\u00b0C`;
    lines.push(line);
  }
  lines.push("[/list]");
  lines.push("");
  lines.push(`[b]Total integration:[/b] ${formatIntegration(data.total_integration_seconds)}`);
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

type ExportFormat = "text" | "markdown" | "bbcode" | "csv";

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "markdown", label: "Markdown" },
  { value: "bbcode", label: "BBCode" },
  { value: "csv", label: "CSV" },
];

function renderExport(format: ExportFormat, data: ExportResponse): string {
  switch (format) {
    case "markdown": return generateMarkdownExport(data);
    case "bbcode": return generateBbcodeExport(data);
    case "csv": return generateCsvExport(data);
    default: return generateTextExport(data);
  }
}

const FORMAT_FILE_EXT: Record<ExportFormat, string> = {
  text: "txt",
  markdown: "md",
  bbcode: "txt",
  csv: "csv",
};

const FORMAT_MIME: Record<ExportFormat, string> = {
  text: "text/plain",
  markdown: "text/markdown",
  bbcode: "text/plain",
  csv: "text/csv",
};

const ExportModal: Component<Props> = (props) => {
  const [selectedDates, setSelectedDates] = createSignal<Set<string>>(
    new Set(props.sessions.map((s) => s.session_date))
  );
  const [format, setFormat] = createSignal<ExportFormat>("text");
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
      setSelectedDates(new Set<string>());
    } else {
      setSelectedDates(new Set(props.sessions.map((s) => s.session_date)));
    }
  };

  const copyText = async () => {
    const data = exportData();
    if (!data) return;
    await navigator.clipboard.writeText(renderExport(format(), data));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadFile = () => {
    const data = exportData();
    if (!data) return;
    const fmt = format();
    const content = renderExport(fmt, data);
    const blob = new Blob([content], { type: FORMAT_MIME[fmt] });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const safeName = props.targetName.replace(/[^a-zA-Z0-9]/g, "_");
    a.download = `${safeName}_acquisition.${FORMAT_FILE_EXT[fmt]}`;
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
          <h2 class="text-sm font-medium text-theme-text-primary">Export - {props.targetName}</h2>
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
                    {s.session_date} - {formatIntegration(s.integration_seconds)} ({s.frame_count} frames)
                  </label>
                )}
              </For>
            </div>
          </div>

          {/* Format selector */}
          <div>
            <div class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide mb-2">Format</div>
            <div class="flex flex-wrap gap-1">
              <For each={FORMATS}>
                {(f) => (
                  <button
                    class={`text-xs px-3 py-1 rounded border transition-colors ${
                      format() === f.value
                        ? "bg-theme-accent/15 text-theme-accent border-theme-accent/30"
                        : "bg-theme-elevated text-theme-text-secondary border-theme-border hover:text-theme-text-primary"
                    }`}
                    onClick={() => setFormat(f.value)}
                  >
                    {f.label}
                  </button>
                )}
              </For>
            </div>
          </div>

          {/* Preview */}
          <Show when={exportData()}>
            {(data) => (
              <div class="bg-theme-elevated rounded p-3 text-xs text-theme-text-primary font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                {renderExport(format(), data())}
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
            class="text-xs px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50"
            disabled={!exportData() || selectedDates().size === 0}
            onClick={downloadFile}
          >
            Download {format().toUpperCase()}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ExportModal;
