import { createSignal, createResource } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import type { ObjectTypeCount } from "../api/types";

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
    return apiClient.GET("/api/targets/fits-keys", {}).then(unwrap);
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
    return apiClient.GET("/api/targets/object-types", {}).then(unwrap);
  },
);
// Discovered filters are not part of the bootstrap payload and stay gated on an
// actual consumer so they are not fetched at startup.
const [discoveredFilters, { refetch: refetchDiscoveredFilters }] = createResource(
  () => shouldFetch() || undefined,
  () =>
    apiClient
      .GET("/api/settings/discovered/{section}", { params: { path: { section: "filters" } } })
      .then(unwrap)
      .then((r) => r.items),
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
