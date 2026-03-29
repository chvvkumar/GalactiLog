import { createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { EquipmentList } from "../types";

const [equipment] = createResource(() => api.getEquipment());
const [expandedTargets, setExpandedTargets] = createSignal<Set<string>>(new Set());

export function useCatalog() {
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
