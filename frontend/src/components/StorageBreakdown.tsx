import { Component } from "solid-js";
import { formatBytes } from "../utils/format";

const StorageBreakdown: Component<{
  fitsBytes: number;
  thumbnailBytes: number;
  databaseBytes: number;
}> = (props) => {
  const rows = () => [
    { label: "FITS files", value: props.fitsBytes, hint: "raw capture data" },
    { label: "Thumbnails", value: props.thumbnailBytes, hint: "generated previews" },
    { label: "Database", value: props.databaseBytes, hint: "metadata and indexes" },
  ];

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <h3 class="text-theme-text-primary font-medium text-sm mb-3">Storage</h3>
      <div class="divide-y divide-theme-border/40">
        {rows().map((r) => (
          <div class="flex items-baseline justify-between py-2">
            <div>
              <div class="text-sm text-theme-text-primary">{r.label}</div>
              <div class="text-caption text-theme-text-tertiary italic">{r.hint}</div>
            </div>
            <div class="text-sm font-semibold text-theme-text-primary tabular-nums">{formatBytes(r.value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default StorageBreakdown;
