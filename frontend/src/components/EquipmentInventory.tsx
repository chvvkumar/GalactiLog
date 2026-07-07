import { Component, Show } from "solid-js";
import type { EquipmentItem } from "../api/types";
import { formatIntegration, formatArcsec } from "../utils/format";
import DataTable, { type DataTableColumn } from "./DataTable";

const EquipmentTable: Component<{ title: string; items: EquipmentItem[] }> = (props) => {
  const columns: DataTableColumn<EquipmentItem>[] = [
    {
      key: "name",
      label: props.title,
      render: (item) => (
        <>
          {item.name}
          <Show when={item.grouped}>
            <span class="text-theme-text-secondary text-tiny ml-1 cursor-help" title="Grouped: multiple equipment aliases are combined under this name">&#x29C9;</span>
          </Show>
        </>
      ),
    },
    {
      key: "frame_count",
      label: "Frames",
      align: "right",
      render: (item) => item.frame_count.toLocaleString(),
    },
    {
      key: "nights",
      label: "Nights",
      align: "right",
      render: (item) => item.nights.toLocaleString(),
    },
    {
      key: "target_count",
      label: "Targets",
      align: "right",
      render: (item) => item.target_count.toLocaleString(),
    },
    {
      key: "avg_session_seconds",
      label: "Avg Session",
      align: "right",
      render: (item) => (item.avg_session_seconds != null ? formatIntegration(item.avg_session_seconds) : "—"),
    },
    {
      key: "integration_seconds",
      label: "Integration",
      align: "right",
      render: (item) => formatIntegration(item.integration_seconds),
    },
    {
      key: "median_fwhm",
      label: "Med FWHM",
      align: "right",
      render: (item) => (item.median_fwhm !== null ? formatArcsec(item.median_fwhm) : "—"),
    },
    {
      key: "median_guiding_rms",
      label: "Guiding",
      align: "right",
      render: (item) => (item.median_guiding_rms !== null ? formatArcsec(item.median_guiding_rms) : "—"),
    },
  ];

  return (
    <div>
      <DataTable
        columns={columns}
        rows={props.items}
        rowKey={(item) => item.name}
        class="text-xs"
        emptyMessage="No equipment data"
      />
    </div>
  );
};

const EquipmentInventory: Component<{ cameras: EquipmentItem[]; telescopes: EquipmentItem[] }> = (props) => {
  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-4">
      <h3 class="text-theme-text-primary font-medium text-sm">Equipment Inventory</h3>
      <EquipmentTable title="Cameras" items={props.cameras} />
      <EquipmentTable title="Telescopes" items={props.telescopes} />
    </div>
  );
};

export default EquipmentInventory;
