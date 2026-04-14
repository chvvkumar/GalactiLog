import { createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { ObjectTypeCount, DiscoveredResponse } from "../types";

const [shouldFetch, setShouldFetch] = createSignal(false);

const [fitsKeys, { refetch: refetchFitsKeys }] = createResource(
  () => shouldFetch() || undefined,
  () => api.getFitsKeys(),
);
const [objectTypes, { refetch: refetchObjectTypes }] = createResource(
  () => shouldFetch() || undefined,
  () => api.getObjectTypes(),
);
const [discoveredFilters, { refetch: refetchDiscoveredFilters }] = createResource(
  () => shouldFetch() || undefined,
  () => api.getDiscovered("filters").then((r) => r.items),
);

export function useFilterOptions() {
  if (!shouldFetch()) setShouldFetch(true);
  return {
    fitsKeys,
    refetchFitsKeys,
    objectTypes,
    refetchObjectTypes,
    discoveredFilters,
    refetchDiscoveredFilters,
  };
}
