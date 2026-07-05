import { createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import type { ObjectTypeCount } from "../types";

const [shouldFetch, setShouldFetch] = createSignal(false);
// Set once bootstrap has seeded fits keys / object types so those resources
// resolve from the seed without waiting for a consumer to mount.
const [seeded, setSeeded] = createSignal(false);

let pendingFitsSeed: string[] | null = null;
let pendingObjectTypesSeed: ObjectTypeCount[] | null = null;

const [fitsKeys, { refetch: refetchFitsKeys, mutate: mutateFitsKeys }] = createResource(
  () => (shouldFetch() || seeded()) || undefined,
  async () => {
    if (pendingFitsSeed) {
      const s = pendingFitsSeed;
      pendingFitsSeed = null;
      return s;
    }
    return api.getFitsKeys();
  },
);
const [objectTypes, { refetch: refetchObjectTypes, mutate: mutateObjectTypes }] = createResource(
  () => (shouldFetch() || seeded()) || undefined,
  async () => {
    if (pendingObjectTypesSeed) {
      const s = pendingObjectTypesSeed;
      pendingObjectTypesSeed = null;
      return s;
    }
    return api.getObjectTypes();
  },
);
// Discovered filters are not part of the bootstrap payload and stay gated on an
// actual consumer so they are not fetched at startup.
const [discoveredFilters, { refetch: refetchDiscoveredFilters }] = createResource(
  () => shouldFetch() || undefined,
  () => api.getDiscovered("filters").then((r) => r.items),
);

export function seedFilterOptions(fitsKeysData: string[], objectTypesData: ObjectTypeCount[]) {
  pendingFitsSeed = fitsKeysData;
  pendingObjectTypesSeed = objectTypesData;
  mutateFitsKeys(fitsKeysData);
  mutateObjectTypes(objectTypesData);
  setSeeded(true);
}

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
