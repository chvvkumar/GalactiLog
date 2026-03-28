import { createResource, onCleanup, onMount } from "solid-js";
import { api } from "../api/client";

const [stats, { refetch: refetchStats }] = createResource(() => api.getStats());

export function useStats() {
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  // Auto-refresh stats every 30 seconds while on the admin page
  onMount(() => {
    pollInterval = setInterval(() => refetchStats(), 30_000);
  });

  onCleanup(() => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  });

  return { stats, refetchStats };
}
