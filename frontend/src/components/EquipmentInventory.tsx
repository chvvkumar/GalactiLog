import { Component, For } from "solid-js";
import type { EquipmentItem } from "../types";

const EquipmentTable: Component<{ title: string; items: EquipmentItem[] }> = (props) => (
  <div>
    <table class="w-full text-xs">
      <thead>
        <tr class="border-b border-theme-border">
          <th class="text-left text-theme-text-secondary font-normal py-1 pr-4">{props.title}</th>
          <th class="text-right text-theme-text-secondary font-normal py-1">Frames</th>
        </tr>
      </thead>
      <tbody>
        <For each={props.items}>{(item) => (
          <tr class="border-b border-theme-border/30">
            <td class="text-left text-theme-text-primary py-1 pr-4">{item.name}</td>
            <td class="text-right text-theme-text-secondary py-1 whitespace-nowrap">{item.frame_count.toLocaleString()}</td>
          </tr>
        )}</For>
      </tbody>
    </table>
  </div>
);

const EquipmentInventory: Component<{ cameras: EquipmentItem[]; telescopes: EquipmentItem[] }> = (props) => {
  return (
    <div class="bg-theme-surface rounded-lg p-4 space-y-4">
      <h3 class="text-theme-text-primary font-medium text-sm">Equipment Inventory</h3>
      <EquipmentTable title="Cameras" items={props.cameras} />
      <EquipmentTable title="Telescopes" items={props.telescopes} />
    </div>
  );
};

export default EquipmentInventory;
