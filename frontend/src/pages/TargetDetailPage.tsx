import { Component, Show, For, createResource, createSignal, createEffect, createMemo, on, onMount, onCleanup } from "solid-js";
import { A, useParams, useSearchParams } from "@solidjs/router";
import { useQuery } from "@tanstack/solid-query";
import { apiClient } from "../api/generated/client";
import { unwrap } from "../api/unwrap";
import { queryKeys } from "../api/queryKeys";
// TargetDetailResponse/SessionDetail are the hand-written definitions in
// `../api/types` -- the generated schema marks many numeric/string fields
// as merely optional (`T | null | undefined`) where these declare them
// required-nullable (`T | null`), which this file's formatting helpers
// (formatCoord/formatSize/buildRows) and SessionOverview/SessionDetail
// assignments rely on throughout. Same precedent as
// DashboardFilterProvider.tsx's TargetAggregationResponse cast and
// TargetRow.tsx's TargetAggregation cast: cast the apiClient result to
// this type at the two fetch boundaries below.
import type { TargetDetailResponse, SessionDetail } from "../api/types";
import type { TargetSearchResultFuzzy, MergedTargetResponse } from "../api/types";
import SessionAccordionCard from "../components/SessionAccordionCard";
import { showToast } from "../components/Toast";
import FilterBadges from "../components/FilterBadges";
import TargetMetricsChart from "../components/TargetMetricsChart";
import WbppExportModal from "../components/WbppExportModal";
import AladinViewer from "../components/AladinViewer";
import { useSettingsContext } from "../components/SettingsProvider";
import { isFieldVisible } from "../utils/displaySettings";
import { contentWidthClass } from "../utils/format";
import HelpPopover from "../components/HelpPopover";
import { timezoneLabel, formatDate } from "../utils/dateTime";
import ActionsMenu from "../components/ActionsMenu";
import InlineRename from "../components/InlineRename";
import CollapsibleHeader from "../components/CollapsibleHeader";
import MergePreviewModal from "../components/MergePreviewModal";
import Button, { buttonClasses } from "../components/ui/Button";
import { useAuth } from "../components/AuthProvider";
import { OBJECT_TYPE_OPTIONS } from "../constants/objectTypes";

import { formatIntegration, formatArcsec } from "../utils/format";
import { getErrorMessage } from "../utils/errors";
import { useNotesAutosave } from "../lib/useNotesAutosave";

function formatCoord(val: number | null, label: string): string {
  if (val === null) return "";
  return `${label} ${val.toFixed(3)}°`;
}

function formatSize(major: number | null, minor: number | null): string {
  if (major === null) return "";
  if (minor === null) return `${major.toFixed(1)}'`;
  return `${major.toFixed(1)}' \u00d7 ${minor.toFixed(1)}'`;
}

// Two-step merge flow: search then preview
interface MergeFromDetailFlowProps {
  winnerId: string;
  winnerName: string;
  onClose: () => void;
  onMerged: () => void;
}

const MergeFromDetailFlow: Component<MergeFromDetailFlowProps> = (props) => {
  const [searchQuery, setSearchQuery] = createSignal("");
  const [searchResults, setSearchResults] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [searching, setSearching] = createSignal(false);
  const [selectedTarget, setSelectedTarget] = createSignal<TargetSearchResultFuzzy | null>(null);

  let searchInputRef: HTMLInputElement | undefined;
  let searchTimeout: ReturnType<typeof setTimeout>;

  onMount(() => {
    searchInputRef?.focus();
  });

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") props.onClose();
  };

  const handleSearch = (q: string) => {
    setSearchQuery(q);
    setSelectedTarget(null);
    clearTimeout(searchTimeout);
    if (q.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    searchTimeout = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await apiClient
          .GET("/api/targets/search", {
            params: { query: { q: q.trim(), include_unresolved: true } },
          })
          .then(unwrap);
        setSearchResults(results.filter((t) => t.id !== props.winnerId));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  };

  const dialogId = "merge-from-detail-dialog";
  const titleId = "merge-from-detail-title";

  return (
    <Show
      when={selectedTarget()}
      fallback={
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={props.onClose}
          onKeyDown={handleKeyDown}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            id={dialogId}
            class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <div class="p-4 border-b border-theme-border">
              <h3 id={titleId} class="text-theme-text-primary font-medium">
                Merge into "{props.winnerName}"
              </h3>
              <p class="text-xs text-theme-text-secondary mt-1">
                Search for a target to merge into this one. You will preview what changes before confirming.
              </p>
            </div>
            <div class="p-4 space-y-3">
              <div class="text-xs px-2 py-1.5 rounded bg-theme-warning/10 text-theme-warning border border-theme-warning/20">
                All images and sessions from the selected target will be moved here. You can revert from Settings &gt; Target Merges.
              </div>
              <div>
                <label class="block text-xs text-theme-text-secondary mb-1">Search for target to merge</label>
                <input
                  ref={searchInputRef}
                  type="text"
                  class="w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:border-theme-accent focus:outline-none"
                  value={searchQuery()}
                  onInput={(e) => handleSearch(e.currentTarget.value)}
                  placeholder="Type to search targets..."
                />
              </div>
              <Show when={searching()}>
                <p class="text-xs text-theme-text-secondary">Searching...</p>
              </Show>
              <Show when={searchResults().length > 0}>
                <div class="border border-theme-border rounded-[var(--radius-sm)] max-h-48 overflow-y-auto">
                  <For each={searchResults()}>
                    {(t) => (
                      <button
                        onClick={() => setSelectedTarget(t)}
                        class="w-full text-left px-3 py-2 text-sm border-b border-theme-border last:border-b-0 transition-colors text-theme-text-primary hover:bg-theme-hover"
                      >
                        <span class="font-medium">{t.primary_name}</span>
                        <Show when={t.object_type}>
                          <span class="text-xs text-theme-text-secondary ml-2">{t.object_type}</span>
                        </Show>
                        <Show when={t.unresolved}>
                          <span class="text-xs text-theme-warning ml-2">
                            Unresolved{t.image_count != null ? ` · ${t.image_count} ${t.image_count === 1 ? "image" : "images"}` : ""}
                          </span>
                        </Show>
                      </button>
                    )}
                  </For>
                </div>
              </Show>
              <Show when={searchQuery().trim().length >= 2 && !searching() && searchResults().length === 0}>
                <p class="text-xs text-theme-text-secondary">No targets found</p>
              </Show>
              <div class="flex justify-end gap-2 pt-2">
                <Button variant="secondary" size="sm" onClick={props.onClose}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </div>
      }
    >
      {(t) => (
        <MergePreviewModal
          winnerId={props.winnerId}
          loserId={t().unresolved ? undefined : t().id}
          loserName={t().unresolved ? t().primary_name : undefined}
          onClose={props.onClose}
          onMerged={props.onMerged}
        />
      )}
    </Show>
  );
};

const TargetDetailPage: Component = () => {
  const params = useParams<{ targetId: string }>();
  const [searchParams] = useSearchParams();
  const auth = useAuth();
  const ctx = useSettingsContext();
  const { displaySettings, graphSettings, saveGraphSettings, timezone, contentWidth } = ctx;
  const tzLabel = () => timezoneLabel(timezone());
  const visible = (group: Parameters<typeof isFieldVisible>[1], field: string) =>
    isFieldVisible(displaySettings(), group, field);

  const targetDetailQuery = useQuery(() => ({
    queryKey: queryKeys.targetDetail(params.targetId),
    queryFn: () =>
      apiClient
        .GET("/api/targets/{target_id}/detail", {
          params: { path: { target_id: params.targetId } },
        })
        .then(unwrap) as Promise<TargetDetailResponse>,
  }));
  // Solid `createResource`-shaped accessor kept for source compatibility with
  // this file's many `targetDetail()` / `.loading` / `.error` call sites and
  // with `on(targetDetail, ...)` below (same technique as
  // DashboardFilterProvider.tsx's `targetData`). `.loading` maps to
  // `isFetching` (not `isLoading`) so it stays true during refetches too,
  // matching Solid's `resource.loading` semantics used by the old code.
  const targetDetail = (() => targetDetailQuery.data) as (() => TargetDetailResponse | undefined) & {
    readonly loading: boolean;
    readonly error: unknown;
  };
  Object.defineProperty(targetDetail, "loading", { enumerable: true, get: () => targetDetailQuery.isFetching });
  Object.defineProperty(targetDetail, "error", { enumerable: true, get: () => targetDetailQuery.error });
  const refetchDetail = async () => { await targetDetailQuery.refetch(); };

  const [showMerge, setShowMerge] = createSignal(false);
  const [showWbppExport, setShowWbppExport] = createSignal(false);
  const [expandedSessions, setExpandedSessions] = createSignal<Set<string>>(new Set());
  const [sessionCache, setSessionCache] = createSignal<Record<string, SessionDetail>>({});
  const [targetChartExpanded, setTargetChartExpanded] = createSignal(graphSettings().target_chart_expanded);
  const [selectedChartDates, setSelectedChartDates] = createSignal<string[]>([]);

  const mergeHistoryQuery = useQuery(() => ({
    queryKey: queryKeys.targetMergeHistory(params.targetId),
    queryFn: (): Promise<MergedTargetResponse[]> =>
      params.targetId.startsWith("obj:")
        ? Promise.resolve([])
        : apiClient
            .GET("/api/targets/{target_id}/merge-history", {
              params: { path: { target_id: params.targetId } },
            })
            .then(unwrap)
            .catch(() => []),
  }));
  const mergeHistory = () => mergeHistoryQuery.data;
  const refetchMergeHistory = async () => { await mergeHistoryQuery.refetch(); };
  const [mergeHistoryExpanded, setMergeHistoryExpanded] = createSignal(false);
  const [undoingMerge, setUndoingMerge] = createSignal<string | null>(null);

  const [skyViewExpanded, setSkyViewExpanded] = createSignal(false);

  // The DSS reference thumbnail is an auth-gated binary, so it is loaded as a
  // blob via fetchWithRefresh (matching getMosaicCompositeBlob) rather than a
  // raw <img src>, which would have no 401-refresh path.
  // Kept as `createResource` (not `useQuery`) deliberately: this preserves the
  // existing, already-correct object-URL create/revoke lifecycle below
  // exactly as-is (per the migration plan's blob-endpoint hazard note, the
  // priority for blob fetches is preserving that lifecycle, not uniformity
  // with the rest of the file's reads). Only the fetch itself moves onto
  // apiClient -- `parseAs: "blob"` (openapi-fetch) matches the old
  // `fetchWithRefresh(...).blob()` behavior; the generated schema types this
  // endpoint's success body as `unknown` (FastAPI's streaming response isn't
  // declared with a content schema), so the unwrap result is cast to `Blob`.
  const [referenceThumbnailUrl] = createResource(
    () => (skyViewExpanded() && targetDetail()?.reference_thumbnail_path ? params.targetId : null),
    async (id: string) => {
      const blob = await apiClient
        .GET("/api/targets/{target_id}/reference-thumbnail", {
          params: { path: { target_id: id } },
          parseAs: "blob",
        })
        .then(unwrap) as Blob;
      return URL.createObjectURL(blob);
    },
  );
  let lastReferenceThumbnailUrl: string | undefined;
  createEffect(() => {
    const url = referenceThumbnailUrl();
    if (lastReferenceThumbnailUrl && lastReferenceThumbnailUrl !== url) {
      URL.revokeObjectURL(lastReferenceThumbnailUrl);
    }
    lastReferenceThumbnailUrl = url;
  });
  onCleanup(() => {
    if (lastReferenceThumbnailUrl) URL.revokeObjectURL(lastReferenceThumbnailUrl);
  });

  const [notesExpanded, setNotesExpanded] = createSignal(false);
  const { notes: targetNotes, onInput: onNotesInput, saving: notesSaving } = useNotesAutosave({
    serverValue: () => targetDetail()?.notes,
    save: async (text) => {
      await apiClient
        .PUT("/api/targets/{target_id}/notes", {
          params: { path: { target_id: params.targetId } },
          body: { notes: text || null },
        })
        .then(unwrap);
    },
    errorLabel: "Failed to save notes",
  });

  // Rename/re-resolve signals
  const [editing, setEditing] = createSignal(false);
  const [savingIdentity, setSavingIdentity] = createSignal(false);

  // Object type edit
  const [editingObjectType, setEditingObjectType] = createSignal(false);
  const [savingObjectType, setSavingObjectType] = createSignal(false);

  const handleObjectTypeChange = async (value: string) => {
    const detail = targetDetail();
    if (!detail) return;
    setSavingObjectType(true);
    try {
      await apiClient
        .PUT("/api/targets/{target_id}/identity", {
          params: { path: { target_id: detail.target_id } },
          body: { object_type: value, re_resolve: false },
        })
        .then(unwrap);
      setEditingObjectType(false);
      await refetchDetail();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Failed to update object type"), "error");
    } finally {
      setSavingObjectType(false);
    }
  };

  const handleRename = async (nameInput: string) => {
    const detail = targetDetail();
    if (!detail) return;
    const name = nameInput.trim();
    if (!name) {
      showToast("Name cannot be empty", "error");
      return;
    }
    if (name === detail.primary_name) {
      showToast("Name is unchanged", "error");
      setEditing(false);
      return;
    }
    setSavingIdentity(true);
    try {
      await apiClient
        .PUT("/api/targets/{target_id}/identity", {
          params: { path: { target_id: detail.target_id } },
          body: { primary_name: name, re_resolve: false },
        })
        .then(unwrap);
      setEditing(false);
      await refetchDetail();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Rename failed"), "error");
    } finally {
      setSavingIdentity(false);
    }
  };

  const handleReResolve = async () => {
    const detail = targetDetail();
    if (!detail) return;
    setSavingIdentity(true);
    try {
      await apiClient
        .PUT("/api/targets/{target_id}/identity", {
          params: { path: { target_id: detail.target_id } },
          body: { re_resolve: true },
        })
        .then(unwrap);
      await refetchDetail();
      showToast("Re-resolve queued");
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Re-resolve failed"), "error");
    } finally {
      setSavingIdentity(false);
    }
  };

  const handleUndoMerge = async (merged: MergedTargetResponse) => {
    setUndoingMerge(merged.id);
    try {
      await apiClient
        .POST("/api/targets/{target_id}/unmerge", {
          params: { path: { target_id: merged.id } },
        })
        .then(unwrap);
      showToast(`Unmerged "${merged.primary_name}"`);
      await Promise.all([refetchMergeHistory(), refetchDetail()]);
      // Unmerging moves frames off this night, so drop the cache and re-load
      // any still-expanded session dates to avoid stale expanded cards that
      // disagree with the refetched summary rows (AUD-012).
      setSessionCache({});
      [...expandedSessions()].forEach(loadSessionDetail);
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Undo merge failed"), "error");
    } finally {
      setUndoingMerge(null);
    }
  };

  createEffect(
    on(targetDetail, (detail, prev) => {
      if (detail && !prev) {
        const n = graphSettings().default_chart_sessions ?? 1;
        const selected = n === 0 ? detail.sessions : detail.sessions.slice(0, n);
        setSelectedChartDates(selected.map((s) => s.session_date));
      }
    })
  );

  const toggleTargetChart = () => {
    const next = !targetChartExpanded();
    setTargetChartExpanded(next);
    saveGraphSettings({ target_chart_expanded: next });
  };

  const toggleChartDate = (date: string) => {
    setSelectedChartDates((prev) =>
      prev.includes(date) ? prev.filter((d) => d !== date) : [...prev, date]
    );
  };

  const selectAllDates = () => {
    const detail = targetDetail();
    if (detail) setSelectedChartDates(detail.sessions.map((s) => s.session_date));
  };

  const selectNoDates = () => setSelectedChartDates([]);

  const copyMultiSessionAstrobinCsv = async () => {
    const dates = selectedChartDates();
    if (dates.length === 0) return;

    const cache = sessionCache();
    const missingDates = dates.filter((d) => !cache[d]);

    if (missingDates.length > 0) {
      try {
        const results = await Promise.all(
          missingDates.map((d) =>
            apiClient
              .GET("/api/targets/{target_id}/sessions/{date}", {
                params: { path: { target_id: params.targetId, date: d } },
              })
              .then(unwrap) as Promise<SessionDetail>
          )
        );
        const newCache = { ...sessionCache() };
        missingDates.forEach((d, i) => {
          newCache[d] = results[i];
        });
        setSessionCache(newCache);
      } catch (e: unknown) {
        showToast(getErrorMessage(e, "Failed to load session details"), "error");
        return;
      }
    }

    const aliasMap = ctx.filterAliasMap();
    const abFilterIds = ctx.settings()?.general.astrobin_filter_ids ?? {};
    const bortle = ctx.settings()?.general.astrobin_bortle ?? "";

    const lookupAbId = (filterName: string) => {
      const canonical = aliasMap[filterName] ?? filterName;
      return abFilterIds[canonical] ?? abFilterIds[filterName] ?? "";
    };

    const median = (vals: number[]) => {
      if (vals.length === 0) return null;
      const s = [...vals].sort((a, b) => a - b);
      const mid = Math.floor(s.length / 2);
      return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    };

    const header =
      "date,filter,number,duration,binning,gain,sensorCooling,fNumber,bortle,meanSqm,meanFwhm,temperature";
    const allRows: string[] = [];
    const updatedCache = sessionCache();

    for (const date of dates) {
      const d = updatedCache[date];
      if (!d) continue;

      const buildRows = (
        filterDetails: typeof d.filter_details,
        gain: number | null,
        sensorTemp: number | null,
        fwhm: number | null,
        ambientTemp: number | null
      ) => {
        for (const f of filterDetails) {
          const filterId = lookupAbId(f.filter_name);
          const g = gain !== null ? gain : "";
          const cooling = sensorTemp !== null ? Math.round(sensorTemp) : "";
          const mFwhm = fwhm !== null ? fwhm.toFixed(2) : "";
          const temp = ambientTemp !== null ? ambientTemp.toFixed(2) : "";
          allRows.push(
            `${d.session_date},${filterId},${f.frame_count},${f.exposure_time ?? ""},,${g},${cooling},,${bortle},,${mFwhm},${temp}`
          );
        }
      };

      if (d.rigs.length > 1) {
        for (const rig of d.rigs) {
          const temps = rig.frames
            .map((f) => f.sensor_temp)
            .filter((t): t is number => t !== null);
          const fwhms = rig.frames
            .map((f) => f.fwhm)
            .filter((v): v is number => v !== null);
          const ambTemps = rig.frames
            .map((f) => f.ambient_temp)
            .filter((v): v is number => v !== null);
          buildRows(rig.filter_details, rig.gain, median(temps), median(fwhms), median(ambTemps));
        }
      } else {
        buildRows(d.filter_details, d.gain, d.sensor_temp, d.median_fwhm, d.median_ambient_temp);
      }
    }

    const csv = [header, ...allRows].join("\n");
    navigator.clipboard.writeText(csv).then(() => {
      showToast(`AstroBin CSV copied (${dates.length} session${dates.length === 1 ? "" : "s"})`, "success", 3000);
    }).catch(() => {
      showToast("Failed to copy to clipboard", "error");
    });
  };

  const pendingLoads = new Set<string>();
  const MAX_CONCURRENT_LOADS = 2;
  const loadQueue: string[] = [];

  const processQueue = () => {
    while (loadQueue.length > 0 && pendingLoads.size < MAX_CONCURRENT_LOADS) {
      const date = loadQueue.shift()!;
      if (sessionCache()[date] || pendingLoads.has(date)) continue;
      pendingLoads.add(date);
      (apiClient
        .GET("/api/targets/{target_id}/sessions/{date}", {
          params: { path: { target_id: params.targetId, date } },
        })
        .then(unwrap) as Promise<SessionDetail>)
        .then((detail) => {
          setSessionCache((prev) => ({ ...prev, [date]: detail }));
        })
        .catch((e: unknown) => {
          showToast(getErrorMessage(e, `Failed to load session ${date}`), "error");
          setExpandedSessions((prev) => {
            const next = new Set(prev);
            next.delete(date);
            return next;
          });
        })
        .finally(() => {
          pendingLoads.delete(date);
          processQueue();
        });
    }
  };

  const loadSessionDetail = (date: string) => {
    if (sessionCache()[date] || pendingLoads.has(date)) return;
    loadQueue.push(date);
    processQueue();
  };

  const chartSessionDetails = createMemo(() => {
    const cache = sessionCache();
    const dates = selectedChartDates();
    const result: Record<string, SessionDetail> = {};
    for (const d of dates) {
      if (cache[d]) result[d] = cache[d];
    }
    return result;
  });

  // Auto-expand first session or session from query param, and load its data
  createEffect(() => {
    const td = targetDetail();
    if (!td) return;
    // If ?view=sessions, start with all sessions collapsed (overview mode)
    if (searchParams.view === "sessions") return;
    const sessionDate = searchParams.session;
    if (sessionDate && typeof sessionDate === "string") {
      setExpandedSessions(new Set([sessionDate]));
      loadSessionDetail(sessionDate);
    } else if (td.sessions.length > 0) {
      const first = td.sessions[0].session_date;
      setExpandedSessions(new Set([first]));
      loadSessionDetail(first);
    }
  });

  const toggleSession = (date: string) => {
    const wasExpanded = expandedSessions().has(date);
    setExpandedSessions((prev) => {
      const next = new Set(prev);
      if (wasExpanded) next.delete(date);
      else next.add(date);
      return next;
    });
    if (!wasExpanded) {
      loadSessionDetail(date);
    }
  };

  return (
    <div class={`page-enter min-h-[calc(100vh-57px)] bg-theme-base ${contentWidthClass(contentWidth())}`}>
      {/* Back nav */}
      <div class="px-4 py-3 border-b border-theme-border">
        <A href="/" class="text-theme-text-secondary hover:text-theme-text-primary text-sm transition-colors">
          ← Back to Dashboard
        </A>
      </div>

      <Show when={targetDetail.loading}>
        <div class="p-8 text-theme-text-secondary">Loading target data...</div>
      </Show>

      <Show when={targetDetail.error}>
        <div class="p-8 text-theme-error">Failed to load target detail</div>
      </Show>

      <Show when={showMerge() && targetDetail()}>
        <MergeFromDetailFlow
          winnerId={targetDetail()!.target_id}
          winnerName={targetDetail()!.primary_name}
          onClose={() => setShowMerge(false)}
          onMerged={async () => {
            setShowMerge(false);
            await Promise.all([refetchDetail(), refetchMergeHistory()]);
            // A merge changes which frames belong to a given night, so any
            // already-expanded session card would keep showing stale cached
            // data. Clear the cache and re-load every still-expanded date so
            // the expanded card matches the refetched summary row (AUD-012).
            setSessionCache({});
            [...expandedSessions()].forEach(loadSessionDetail);
          }}
        />
      </Show>

      <Show when={showWbppExport() && targetDetail()}>
        <WbppExportModal
          targetId={params.targetId}
          targetName={targetDetail()!.primary_name}
          selectedDates={selectedChartDates()}
          sessionCache={sessionCache()}
          onClose={() => setShowWbppExport(false)}
        />
      </Show>

      <Show when={targetDetail()}>
        {(detail) => (
          <div class="px-4 sm:px-6 py-4 sm:py-5">
            <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
            {/* Target Hero */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div>
                <div>
                  <div class="flex items-start justify-between gap-3">
                  <div class="flex items-center gap-2 min-w-0">
                    <Show
                      when={editing()}
                      fallback={
                        <>
                          <h1 class="text-2xl font-semibold tracking-tight text-theme-text-primary">
                            {detail().primary_name}
                          </h1>
                          <Show when={detail().name_locked}>
                            <span class="text-theme-text-tertiary text-lg" title="Name manually locked">&#128274;</span>
                          </Show>
                          <Show when={detail().user_defined}>
                            <span class="px-2 py-0.5 rounded-full text-label font-medium bg-theme-accent/15 text-theme-accent" title="User-defined target, excluded from catalog enrichment">Custom</span>
                          </Show>
                          <Show when={auth.isAdmin()}>
                            <button
                              class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors text-lg leading-none"
                              title="Rename target"
                              aria-label="Rename target"
                              disabled={savingIdentity()}
                              onClick={() => setEditing(true)}
                            >
                              &#9998;
                            </button>
                            <button
                              class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors text-lg leading-none"
                              title="Re-resolve from SIMBAD"
                              aria-label="Re-resolve from SIMBAD"
                              disabled={savingIdentity()}
                              onClick={handleReResolve}
                            >
                              &#8635;
                            </button>
                          </Show>
                        </>
                      }
                    >
                      <InlineRename
                        initialValue={detail().primary_name}
                        onSave={handleRename}
                        onCancel={() => setEditing(false)}
                        saving={savingIdentity()}
                        inputClass="text-2xl font-semibold tracking-tight bg-transparent border-b border-theme-accent text-theme-text-primary focus:outline-none min-w-0 flex-1"
                      />
                    </Show>
                    <HelpPopover>
                      <p class="text-sm text-theme-text-secondary">
                        The Target Detail page shows everything GalactiLog knows about a single imaging target.
                      </p>
                      <p class="text-sm text-theme-text-secondary">
                        The header displays the resolved object name, coordinates, object type, and angular size from SIMBAD when available.
                      </p>
                      <ul class="list-disc list-inside space-y-1 text-sm text-theme-text-secondary">
                        <li><strong class="text-theme-text-primary">Integration summary</strong> shows total exposure time, frame counts, and filter breakdown.</li>
                        <li><strong class="text-theme-text-primary">Charts</strong> visualize quality metrics (HFR, FWHM, guiding RMS, etc.) across sessions. Click the chart header to expand or collapse it.</li>
                        <li><strong class="text-theme-text-primary">Sessions</strong> are listed as expandable cards. Each card shows per-session metrics, and expanding it reveals individual frame details with all recorded FITS header data.</li>
                        <li>Use the <strong class="text-theme-text-primary">Export</strong> menu in the Sessions section to copy an AstroBin-compatible CSV or generate a WBPP export for the selected sessions.</li>
                      </ul>
                    </HelpPopover>
                  </div>
                  <div class="flex items-center gap-2 shrink-0">
                    <Show when={auth.isAdmin()}>
                      <Button variant="primary" onClick={() => setShowMerge(true)}>
                        Merge
                      </Button>
                    </Show>
                  </div>
                  </div>
                  <div class="text-xs text-theme-text-secondary mt-1 flex flex-wrap gap-x-2 gap-y-0.5 items-center">
                    <Show when={detail().object_category || auth.isAdmin()}>
                      <Show
                        when={editingObjectType() && auth.isAdmin()}
                        fallback={
                          <span class="flex items-center gap-1">
                            <span>{detail().object_category ?? "Unknown type"}</span>
                            <Show when={auth.isAdmin()}>
                              <button
                                class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors leading-none"
                                title="Edit object type"
                                aria-label="Edit object type"
                                disabled={savingObjectType()}
                                onClick={() => setEditingObjectType(true)}
                              >
                                &#9998;
                              </button>
                            </Show>
                          </span>
                        }
                      >
                        <span class="flex items-center gap-1">
                          <select
                            class="text-xs bg-theme-base border border-theme-accent rounded px-1 py-0.5 text-theme-text-primary focus:outline-none"
                            disabled={savingObjectType()}
                            value={detail().object_category ?? ""}
                            onChange={(e) => handleObjectTypeChange(e.currentTarget.value)}
                          >
                            <option value="" disabled>Select type...</option>
                            <For each={OBJECT_TYPE_OPTIONS}>
                              {(opt) => <option value={opt}>{opt}</option>}
                            </For>
                          </select>
                          <button
                            class="text-theme-text-tertiary hover:text-theme-error transition-colors leading-none"
                            title="Cancel"
                            aria-label="Cancel object type edit"
                            onClick={() => setEditingObjectType(false)}
                            disabled={savingObjectType()}
                          >
                            &#10005;
                          </button>
                        </span>
                      </Show>
                      <Show when={!editingObjectType()}>
                        <span>·</span>
                      </Show>
                    </Show>
                    <Show when={detail().constellation}>
                      <span>{detail().constellation}</span>
                      <span>·</span>
                    </Show>
                    <Show when={detail().ra !== null}>
                      <span>{formatCoord(detail().ra, "RA")}</span>
                    </Show>
                    <Show when={detail().dec !== null}>
                      <span>{formatCoord(detail().dec, "Dec")}</span>
                    </Show>
                    <Show when={detail().size_major !== null}>
                      <span>·</span>
                      <span>Size {formatSize(detail().size_major, detail().size_minor)}</span>
                    </Show>
                    <Show when={detail().v_mag !== null}>
                      <span>·</span>
                      <span>Visual Mag. {detail().v_mag!.toFixed(1)}</span>
                    </Show>
                    <Show when={detail().surface_brightness !== null}>
                      <span>·</span>
                      <span>SB {detail().surface_brightness!.toFixed(1)}</span>
                    </Show>
                    <Show when={detail().distance_pc != null}>
                      <span>·</span>
                      <span>Distance {detail().distance_pc!.toFixed(0)} pc</span>
                    </Show>
                    <Show when={detail().aliases.length > 1}>
                      <span>· Aliases: {detail().aliases.slice(1).join(", ")}</span>
                    </Show>
                    <Show when={detail().sac_description || detail().sac_notes}>
                      <span>· {detail().sac_description}{detail().sac_description && detail().sac_notes ? " — " : ""}{detail().sac_notes}</span>
                    </Show>
                    <span>·</span>
                    <span>{detail().session_count} sessions</span>
                    <span class="mx-1.5">·</span>
                    <span>{detail().first_session_date} → {detail().last_session_date} ({tzLabel()})</span>
                  </div>
                  <Show when={detail().catalog_memberships?.length}>
                    <div class="flex flex-wrap gap-1.5 mt-1">
                      <For each={detail().catalog_memberships}>
                        {(m) => (
                          <span
                            class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-theme-surface border border-theme-border text-theme-text-secondary"
                            title={m.metadata ? JSON.stringify(m.metadata) : undefined}
                          >
                            {m.catalog_number}
                          </span>
                        )}
                      </For>
                    </div>
                  </Show>
                </div>
              </div>

              {/* Cumulative stats bar */}
              <div class="mt-4 space-y-3">
                <div class="grid grid-cols-[repeat(auto-fit,minmax(100px,1fr))] gap-2">
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center">
                    <div class="text-lg font-semibold text-metric-integration">{formatIntegration(detail().total_integration_seconds)}</div>
                    <div class="text-caption text-theme-text-secondary">Total Integration</div>
                  </div>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center">
                    <div class="text-lg font-semibold text-metric-frames">{detail().total_frames.toLocaleString()}</div>
                    <div class="text-caption text-theme-text-secondary">Total Frames</div>
                  </div>
                  <Show when={visible("quality", "hfr")}>
                    <div
                      class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center"
                      title="Arcsecond HFR when the plate scale is known; pixel HFR is only comparable within one optical train"
                    >
                      <div class="text-lg font-semibold text-metric-hfr tabular-nums">
                        {detail().avg_hfr_arcsec != null
                          ? formatArcsec(detail().avg_hfr_arcsec)
                          : detail().avg_hfr != null
                            ? `${detail().avg_hfr!.toFixed(2)} px`
                            : "—"}
                      </div>
                      <div class="text-caption text-theme-text-secondary">Avg HFR</div>
                    </div>
                  </Show>
                  <Show when={visible("quality", "eccentricity")}>
                    <div
                      class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center cursor-help"
                      title="Eccentricity is session-relative: it reflects the ratio of rig error to seeing for that session, so there is no universal good/bad threshold. Compare sessions against each other, not against a fixed number."
                    >
                      <div class="text-lg font-semibold text-metric-eccentricity tabular-nums">
                        {detail().avg_eccentricity?.toFixed(2) ?? "—"}
                      </div>
                      <div class="text-caption text-theme-text-secondary">Avg Eccentricity</div>
                    </div>
                  </Show>
                  <Show when={visible("quality", "fwhm")}>
                    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center">
                      <div class="text-lg font-semibold text-theme-info">
                        {detail().avg_fwhm?.toFixed(2) ?? "—"}
                      </div>
                      <div class="text-caption text-theme-text-secondary">Avg FWHM</div>
                    </div>
                  </Show>
                  <Show when={visible("quality", "detected_stars")}>
                    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center">
                      <div class="text-lg font-semibold text-metric-stars">
                        {detail().avg_detected_stars?.toFixed(0) ?? "—"}
                      </div>
                      <div class="text-caption text-theme-text-secondary">Avg Stars</div>
                    </div>
                  </Show>
                  <Show when={visible("guiding", "rms_total")}>
                    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center">
                      <div class="text-lg font-semibold text-metric-guiding">
                        {detail().avg_guiding_rms_arcsec !== null ? formatArcsec(detail().avg_guiding_rms_arcsec) : "—"}
                      </div>
                      <div class="text-caption text-theme-text-secondary">Avg Guide RMS</div>
                    </div>
                  </Show>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center flex flex-col items-center justify-center">
                    <div class="mb-1">
                      <FilterBadges distribution={Object.fromEntries(detail().filters_used.map(f => [f, 0]))} compact />
                    </div>
                    <div class="text-caption text-theme-text-secondary">Filters Used</div>
                  </div>
                </div>
              </div>
            </div>


            {/* Merge History */}
            <Show when={mergeHistory()?.length}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
                <CollapsibleHeader
                  title="Merge History"
                  expanded={mergeHistoryExpanded}
                  onToggle={() => setMergeHistoryExpanded((v) => !v)}
                  suffix={<span class="text-theme-text-tertiary font-normal normal-case tracking-normal ml-2">({mergeHistory()!.length})</span>}
                />
                <Show when={mergeHistoryExpanded()}>
                  <div class="mt-2 space-y-2">
                    <For each={mergeHistory()}>
                      {(merged) => (
                        <div class="flex items-center justify-between p-3 bg-theme-surface border border-theme-border rounded-[var(--radius-sm)]">
                          <div class="flex-1 min-w-0">
                            <span class="text-theme-text-primary text-sm font-medium">{merged.primary_name}</span>
                            <div class="text-xs text-theme-text-secondary mt-0.5">
                              Merged on {formatDate(merged.merged_at, timezone())}
                              {" · "}{merged.image_count} {merged.image_count === 1 ? "image" : "images"}
                            </div>
                          </div>
                          <Show when={auth.isAdmin()}>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => handleUndoMerge(merged)}
                              disabled={undoingMerge() === merged.id}
                              class="shrink-0 ml-3"
                            >
                              {undoingMerge() === merged.id ? "Undoing..." : "Undo Merge"}
                            </Button>
                          </Show>
                        </div>
                      )}
                    </For>
                  </div>
                </Show>
              </div>
            </Show>

            {/* Sky View & Reference Thumbnail */}
            <Show when={detail().ra != null && detail().dec != null}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
                <div class="flex items-center gap-2">
                  <CollapsibleHeader
                    title="Sky View"
                    expanded={skyViewExpanded}
                    onToggle={() => setSkyViewExpanded((v) => !v)}
                  />
                  <HelpPopover>
                    <p class="text-sm text-theme-text-secondary">
                      Interactive sky viewer centered on the target. The Aladin panel supports zoom and pan across surveys (DSS2, PanSTARRS, and others), and the reference thumbnail shows the default DSS image for context. Example: switch surveys in Aladin to compare how the target looks in different wavelengths.
                    </p>
                  </HelpPopover>
                </div>
                <Show when={skyViewExpanded()}>
                  <div class="mt-2 flex gap-3 items-stretch">
                    <div class="w-[60%] min-w-0 flex flex-col">
                      <AladinViewer
                        ra={detail().ra!}
                        dec={detail().dec!}
                        fov={detail().size_major ? detail().size_major! * 1.5 / 60 : 0.5}
                      />
                    </div>
                    <Show when={detail().reference_thumbnail_path}>
                      <div class="w-[40%] min-w-0">
                        <div class="text-xs font-medium text-theme-text-tertiary mb-1">DSS Reference</div>
                        <Show when={referenceThumbnailUrl()}>
                          <img
                            src={referenceThumbnailUrl()}
                            alt="DSS reference"
                            class="rounded-[var(--radius-sm)] border border-theme-border w-full h-auto"
                          />
                        </Show>
                      </div>
                    </Show>
                  </div>
                </Show>
              </div>
            </Show>

            {/* Target Notes */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
              <div class="flex items-center gap-2">
                <CollapsibleHeader
                  title="Notes"
                  expanded={notesExpanded}
                  onToggle={() => setNotesExpanded((v) => !v)}
                  suffix={
                    <Show when={targetNotes()}>
                      <span class="text-theme-text-tertiary font-normal normal-case tracking-normal ml-2">has content</span>
                    </Show>
                  }
                  trailing={
                    <Show when={notesSaving()}>
                      <span class="text-xs text-theme-text-secondary">Saving...</span>
                    </Show>
                  }
                />
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Free-form notes attached to this target. Notes persist across sessions and are included in exports. Example: record plate solving issues, framing plans, or processing decisions.
                  </p>
                </HelpPopover>
              </div>
              <Show when={notesExpanded()}>
                <textarea
                  class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[60px] mt-2"
                  placeholder="Add notes about this target..."
                  value={targetNotes()}
                  onInput={(e) => onNotesInput(e.currentTarget.value)}
                />
              </Show>
            </div>

            {/* Target Metrics Chart */}
            <Show when={targetDetail()}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
                <div class="flex items-center gap-2">
                  <CollapsibleHeader
                    title="Graphs"
                    expanded={targetChartExpanded}
                    onToggle={toggleTargetChart}
                  />
                  <HelpPopover>
                    <p class="text-sm text-theme-text-secondary">
                      Per-frame metric plots (HFR, FWHM, eccentricity, guide RMS, and others) over time. Use the date selector to narrow to a single imaging night or span multiple sessions. Example: spot a degrading HFR trend across a single night to identify focus drift.
                    </p>
                  </HelpPopover>
                </div>
                <Show when={targetChartExpanded()}>
                  <TargetMetricsChart
                    selectedDates={selectedChartDates()}
                    sessionDetails={chartSessionDetails()}
                    expanded={targetChartExpanded()}
                    onLoadSession={loadSessionDetail}
                    availableFilters={detail().filters_used ?? []}
                  />
                </Show>
              </div>
            </Show>

            {/* Session Table */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Sessions</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Each card is one imaging session on this target. Expand a card to see per-frame details (exposure, filter, camera temperature, HFR, guiding). Example: compare two sessions of the same target to pick the better one for stacking.
                  </p>
                </HelpPopover>
                <div class="ml-auto">
                  <ActionsMenu
                    ariaLabel="Export options"
                    buttonClass={buttonClasses("primary")}
                    triggerContent={<span class="inline-flex items-center gap-1">Export<span class="text-xs leading-none" aria-hidden="true">&#9662;</span></span>}
                  >
                    {(close) => (
                      <>
                        <button
                          type="button"
                          role="menuitem"
                          disabled={selectedChartDates().length === 0}
                          title={selectedChartDates().length === 0 ? "Select one or more sessions first" : undefined}
                          class="w-full text-left px-3 py-1.5 text-sm text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                          onClick={() => {
                            if (selectedChartDates().length === 0) return;
                            close();
                            void copyMultiSessionAstrobinCsv();
                          }}
                        >
                          {selectedChartDates().length > 0
                            ? `AstroBin CSV (${selectedChartDates().length})`
                            : "AstroBin CSV"}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          disabled={selectedChartDates().length === 0}
                          title={selectedChartDates().length === 0 ? "Select one or more sessions first" : undefined}
                          class="w-full text-left px-3 py-1.5 text-sm text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                          onClick={() => {
                            if (selectedChartDates().length === 0) return;
                            close();
                            setShowWbppExport(true);
                          }}
                        >
                          {selectedChartDates().length > 0
                            ? `WBPP Export (${selectedChartDates().length})`
                            : "WBPP Export"}
                        </button>
                      </>
                    )}
                  </ActionsMenu>
                </div>
              </div>
              <div class="overflow-x-auto">
              <table class="w-full min-w-[600px]" style={{ "border-collapse": "separate", "border-spacing": "0 10px" }}>
                <thead>
                  <tr class="text-caption text-theme-text-tertiary uppercase tracking-wider">
                    <th class="py-2 pl-4 pr-1 w-8">
                      <input
                        type="checkbox"
                        checked={selectedChartDates().length === detail().sessions.length}
                        ref={(el) => {
                          createEffect(() => {
                            const len = selectedChartDates().length;
                            const total = detail().sessions.length;
                            el.indeterminate = len > 0 && len < total;
                          });
                        }}
                        onChange={(e) => {
                          if (e.currentTarget.checked) selectAllDates();
                          else selectNoDates();
                        }}
                        class="w-3.5 h-3.5 rounded border-theme-border cursor-pointer"
                        title="Select all / none"
                      />
                    </th>
                    <th class="py-2 px-4 text-left font-medium">Date ({tzLabel()})</th>
                    <th class="py-2 px-2 text-right font-medium"></th>
                    <th class="py-2 px-2 text-right font-medium">Frames</th>
                    <Show when={visible("quality", "hfr")}>
                      <th class="py-2 px-2 text-right font-medium">HFR</th>
                    </Show>
                    <Show when={visible("quality", "eccentricity")}>
                      <th class="py-2 px-2 text-right font-medium">Eccentricity</th>
                    </Show>
                    <Show when={visible("quality", "fwhm")}>
                      <th class="py-2 px-2 text-right font-medium">FWHM</th>
                    </Show>
                    <Show when={visible("quality", "detected_stars")}>
                      <th class="py-2 px-2 text-right font-medium">Stars</th>
                    </Show>
                    <Show when={visible("guiding", "rms_total")}>
                      <th class="py-2 px-2 text-right font-medium">Guide RMS</th>
                    </Show>
                    <For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "session")}>
                      {(col) => (
                        <th class="py-2 px-2 text-right font-medium">{col.name}</th>
                      )}
                    </For>
                    <th class="py-2 px-2 text-right font-medium">Filters</th>
                    <th class="py-2 px-2"></th>
                  </tr>
                </thead>
                  <For each={detail().sessions}>
                    {(session) => (
                      <SessionAccordionCard
                        session={session}
                        isExpanded={expandedSessions().has(session.session_date)}
                        onToggle={() => toggleSession(session.session_date)}
                        detail={sessionCache()[session.session_date] ?? null}
                        autoScroll={searchParams.session === session.session_date}
                        visibleColumns={{
                          hfr: visible("quality", "hfr"),
                          eccentricity: visible("quality", "eccentricity"),
                          fwhm: visible("quality", "fwhm"),
                          detected_stars: visible("quality", "detected_stars"),
                          guiding_rms: visible("guiding", "rms_total"),
                        }}
                        showCheckbox={true}
                        checked={selectedChartDates().includes(session.session_date)}
                        onCheckChange={() => toggleChartDate(session.session_date)}
                        targetId={params.targetId}
                        ra={session.ra ?? detail().ra}
                        dec={session.dec ?? detail().dec}
                        position_angle={session.position_angle ?? detail().position_angle}
                        targetName={detail().primary_name}
                      />
                    )}
                  </For>
              </table>
              </div>
            </div>
            </div>
          </div>
        )}
      </Show>
    </div>
  );
};

export default TargetDetailPage;
