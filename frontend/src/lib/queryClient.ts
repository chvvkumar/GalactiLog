// Shared TanStack Solid Query client, installed at the app root in
// index.tsx. T2 only stands up the provider -- no call sites use
// useQuery/useMutation yet (that is T3's job).
//
// Defaults chosen deliberately, since T3 inherits them per-query unless
// overridden:
// - refetchOnWindowFocus: false. This app already has several bespoke
//   polling loops (store/taskPoller.ts, store/activeJobs.ts, store/scan.ts)
//   that are not managed by TanStack Query. Leaving the library default
//   (true) on would mean any future query silently refetches on window
//   focus in addition to whatever manual polling already exists for that
//   data, which is surprising until T3 explicitly migrates those pollers.
// - retry: 1. TanStack Query's default of 3 retries (with backoff) is more
//   aggressive than this app's existing fetch layer, which does not retry
//   network failures at all. 1 retry is a modest middle ground until T3
//   revisits this per query.
// - staleTime / gcTime left at library defaults (0 / 5 minutes) for now;
//   revisit per-query in T3 once real query keys exist.
import { QueryClient } from "@tanstack/solid-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
