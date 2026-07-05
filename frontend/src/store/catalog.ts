import { createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { EquipmentList } from "../types";

const [shouldFetchEquipment, setShouldFetchEquipment] = createSignal(false);

// One-shot seed consumed by the resource's first run (see settings store).
let pendingEquipmentSeed: EquipmentList | null = null;
const [equipment, { mutate: mutateEquipment }] = createResource(
  () => shouldFetchEquipment() || undefined,
  async () => {
    if (pendingEquipmentSeed) {
      const s = pendingEquipmentSeed;
      pendingEquipmentSeed = null;
      return s;
    }
    return api.getEquipment();
  },
);

export function seedEquipment(data: EquipmentList) {
  pendingEquipmentSeed = data;
  mutateEquipment(data);
  setShouldFetchEquipment(true);
}
const [expandedTargets, setExpandedTargets] = createSignal<Set<string>>(new Set());

export function useCatalog() {
  if (!shouldFetchEquipment()) setShouldFetchEquipment(true);
  return {
    equipment,
    expandedTargets,

    toggleExpanded: (targetId: string) => {
      setExpandedTargets((prev) => {
        const next = new Set(prev);
        if (next.has(targetId)) next.delete(targetId);
        else next.add(targetId);
        return next;
      });
    },
  };
}
