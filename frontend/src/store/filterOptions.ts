import { createResource } from "solid-js";
import { api } from "../api/client";
import type { ObjectTypeCount, DiscoveredResponse } from "../types";

const [fitsKeys, { refetch: refetchFitsKeys }] = createResource(() => api.getFitsKeys());
const [objectTypes, { refetch: refetchObjectTypes }] = createResource(() => api.getObjectTypes());
const [discoveredFilters, { refetch: refetchDiscoveredFilters }] = createResource(() =>
  api.getDiscovered("filters").then((r) => r.items),
);

export function useFilterOptions() {
  return {
    fitsKeys,
    refetchFitsKeys,
    objectTypes,
    refetchObjectTypes,
    discoveredFilters,
    refetchDiscoveredFilters,
  };
}
