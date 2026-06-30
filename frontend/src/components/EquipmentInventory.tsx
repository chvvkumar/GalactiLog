import { Component, For, Show } from "solid-js";
import type { EquipmentItem } from "../types";
import { formatIntegration } from "../utils/format";

const EquipmentTable: Component<{ title: string; items: EquipmentItem[] }> = (props) => (
  <div>
    <table class="w-full text-xs table-fixed">
      <colgroup>
        <col class="w-[24%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
        <col class="w-[10.857%]" />
      </colgroup>
      <thead>
        <tr class="border-b border-theme-border">
          <th class="text-left text-theme-text-secondary font-normal py-1 pr-4">{props.title}</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Frames</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Nights</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Targets</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Avg Session</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Integration</th>
          <th class="text-right text-theme-text-secondary font-normal py-1 pr-4">Med FWHM</th>
          <th class="text-right text-theme-text-secondary font-normal py-1">Guiding</th>
        </tr>
      </thead>
      <tbody>
        <For each={props.items}>{(item) => (
          <tr class="border-b border-theme-border/30">
            <td class="text-left text-theme-text-primary py-1 pr-4">
              {item.name}
              <Show when={item.grouped}>
                <span class="text-theme-text-secondary text-tiny ml-1 cursor-help" title="Grouped: multiple equipment aliases are combined under this name">&#x29C9;</span>
              </Show>
            </td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{item.frame_count.toLocaleString()}</td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{item.nights.toLocaleString()}</td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{item.target_count.toLocaleString()}</td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{item.avg_session_seconds !== null ? formatIntegration(item.avg_session_seconds) : "—"}</td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{formatIntegration(item.integration_seconds)}</td>
            <td class="text-right text-theme-text-secondary py-1 pr-4 whitespace-nowrap">{item.median_fwhm !== null ? item.median_fwhm.toFixed(2) + "″" : "—"}</td>
            <td class="text-right text-theme-text-secondary py-1 whitespace-nowrap">{item.median_guiding_rms !== null ? item.median_guiding_rms.toFixed(2) + "″" : "—"}</td>
          </tr>
        )}</For>
      </tbody>
    </table>
  </div>
);

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
