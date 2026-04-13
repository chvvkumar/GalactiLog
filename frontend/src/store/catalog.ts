import { createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { EquipmentList } from "../types";

const [shouldFetchEquipment, setShouldFetchEquipment] = createSignal(false);

const [equipment] = createResource(
  () => shouldFetchEquipment() || undefined,
  () => api.getEquipment(),
);
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
