import { createResource, onCleanup, onMount, startTransition } from "solid-js";
import { api } from "../api/client";

const [stats, { refetch: refetchStats }] = createResource(() => api.getStats());

let _subscribers = 0;
let _pollInterval: ReturnType<typeof setInterval> | null = null;

function _startPoll() {
  if (_pollInterval) return;
  _pollInterval = setInterval(() => startTransition(() => refetchStats()), 30_000);
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
