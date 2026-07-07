import { createResource, onCleanup, onMount, startTransition } from "solid-js";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
// Deliberately cast to the OLD hand-written `StatsResponse` (required nested
// fields, e.g. `EquipmentComboMetrics.avg_session_seconds`) rather than the
// generated-schema alias, which types several nested numeric fields as
// optional (backend Pydantic defaults). This store is consumed by
// StatisticsPage.tsx and its downstream chart components (EquipmentPerformance,
// EquipmentInventory, ImagingTimeline, TopTargets, StatsOverview), none of
// which are in this slice's scope and still import their prop types from the
// old `../types`; repointing here would ripple a required->optional type
// break into files this slice does not touch. Same precedent as scan.ts in
// Slice 1. The backend always populates these fields, so the cast reflects
// actual runtime shape; a later slice that migrates the Statistics page can
// drop the cast alongside repointing its consumers to `../api/types`.
import type { StatsResponse } from "../types";

const [stats, { refetch: refetchStats }] = createResource(() =>
  apiClient.GET("/api/stats", {}).then(unwrap) as Promise<StatsResponse>,
);

let _subscribers = 0;
let _pollInterval: ReturnType<typeof setInterval> | null = null;

function _poll() {
  if (document.visibilityState === "visible") {
    startTransition(() => refetchStats());
  }
}

function _startPoll() {
  if (_pollInterval) return;
  _pollInterval = setInterval(_poll, 120_000);
}

function _stopPoll() {
  if (_pollInterval) {
    clearInterval(_pollInterval);
    _pollInterval = null;
  }
}

export function useStats() {
  onMount(() => {
    _subscribers++;
    _startPoll();
  });

  onCleanup(() => {
    _subscribers--;
    if (_subscribers <= 0) {
      _subscribers = 0;
      _stopPoll();
    }
  });

  return { stats, refetchStats: () => startTransition(() => refetchStats()) };
}
