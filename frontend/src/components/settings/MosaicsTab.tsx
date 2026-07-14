import { Component, For, Show, createEffect, createMemo, createSignal, onMount } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { apiClient } from "../../api/generated/client";
import { unwrap, ApiError } from "../../api/unwrap";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { useSettingsContext } from "../SettingsProvider";
import HelpPopover from "../HelpPopover";
import { emitWithToast } from "../../lib/emitWithToast";
import type {
  MosaicSummary,
  MosaicDetailResponse,
  MosaicSuggestionResponse,
  TargetSearchResultFuzzy,
} from "../../api/types";

// Module-level cache so data persists across navigations
let cachedSuggestions: MosaicSuggestionResponse[] | null = null;
let cachedMosaics: MosaicSummary[] | null = null;

import { formatIntegration } from "../../utils/format";
import InlineEditCell from "../InlineEditCell";
import ColumnPicker from "../ColumnPicker";
import { isColumnVisible } from "../../utils/displaySettings";
import KonvaMosaicArranger, { type PreviewPanel } from "../mosaics/KonvaMosaicArranger";
import Button from "../ui/Button";
import IconButton from "../ui/IconButton";

export const MosaicsTab: Component = () => {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const settingsCtx = useSettingsContext();

  // Keywords state
  const [newKeyword, setNewKeyword] = createSignal("");

  // Suggestions state
  const [suggestions, setSuggestions] = createSignal<MosaicSuggestionResponse[]>([]);
  const [detecting, setDetecting] = createSignal(false);
  const [acceptingId, setAcceptingId] = createSignal<string | null>(null);

  // Mosaics state
  const [mosaics, setMosaics] = createSignal<MosaicSummary[]>([]);
  const [expandedId, setExpandedId] = createSignal<string | null>(null);
  const [details, setDetails] = createSignal<Record<string, MosaicDetailResponse>>({});

  // Add panel state
  const [panelSearch, setPanelSearch] = createSignal("");
  const [panelLabel, setPanelLabel] = createSignal("");
  const [searchResults, setSearchResults] = createSignal<TargetSearchResultFuzzy[]>([]);
  const [selectedTarget, setSelectedTarget] = createSignal<TargetSearchResultFuzzy | null>(null);
  const [addingPanelFor, setAddingPanelFor] = createSignal<string | null>(null);

  // Expanded suggestion
  const [expandedSuggestion, setExpandedSuggestion] = createSignal<string | null>(null);

  // Suggestion filter
  const [suggestionFilter, setSuggestionFilter] = createSignal("");
  const filteredSuggestions = () => {
    const q = suggestionFilter().toLowerCase().trim();
    if (!q) return suggestions();
    return suggestions().filter(s => s.suggested_name.toLowerCase().includes(q));
  };

  // Per-suggestion panel selection: map suggestion id -> set of selected panel labels
  const [selectedPanels, setSelectedPanels] = createSignal<Record<string, Set<string>>>({});

  // Rename mosaic state
  const [renamingId, setRenamingId] = createSignal<string | null>(null);
  const [renameValue, setRenameValue] = createSignal("");

  // Create mosaic state
  const [showCreate, setShowCreate] = createSignal(false);
  const [newMosaicName, setNewMosaicName] = createSignal("");

  // Delete confirmation
  const [confirmDeleteId, setConfirmDeleteId] = createSignal<string | null>(null);

  // Dismiss confirmation (suggestions)
  const [confirmDismissId, setConfirmDismissId] = createSignal<string | null>(null);

  // Collapse state — keywords and suggestions default collapsed, persisted in localStorage
  const [keywordsCollapsed, setKeywordsCollapsed] = createSignal(
    localStorage.getItem("mosaics-keywords-collapsed") !== "false"
  );
  const [suggestionsCollapsed, setSuggestionsCollapsed] = createSignal(
    localStorage.getItem("mosaics-suggestions-collapsed") !== "false"
  );
  const [mosaicsCollapsed, setMosaicsCollapsed] = createSignal(false);

  type MosaicSortKey = "name" | "panels" | "integration" | "frames" | "date_range";
  // Mosaics list sort persisted to localStorage (Dashboard pattern).
  const MOSAIC_LIST_SORT_LS = "mosaics_list_sort";
  let initialListSort: { key: MosaicSortKey; asc: boolean } = { key: "name", asc: true };
  try {
    const stored = localStorage.getItem(MOSAIC_LIST_SORT_LS);
    if (stored) initialListSort = JSON.parse(stored);
  } catch { /* ignore corrupt localStorage */ }
  const [mosaicSortKey, setMosaicSortKey] = createSignal<MosaicSortKey>(initialListSort.key);
  const [mosaicSortAsc, setMosaicSortAsc] = createSignal(initialListSort.asc);
  const persistListSort = (key: MosaicSortKey, asc: boolean) => {
    try { localStorage.setItem(MOSAIC_LIST_SORT_LS, JSON.stringify({ key, asc })); } catch { /* ignore */ }
  };
  const toggleMosaicSort = (key: MosaicSortKey) => {
    if (mosaicSortKey() === key) {
      const asc = !mosaicSortAsc();
      setMosaicSortAsc(asc);
      persistListSort(key, asc);
    } else {
      setMosaicSortKey(key);
      setMosaicSortAsc(true);
      persistListSort(key, true);
    }
  };
  const sortedMosaics = createMemo(() => {
    const key = mosaicSortKey();
    const asc = mosaicSortAsc();
    return [...mosaics()].sort((a, b) => {
      let cmp = 0;
      switch (key) {
        case "name": cmp = a.name.localeCompare(b.name); break;
        case "panels": cmp = a.panel_count - b.panel_count; break;
        case "integration": cmp = a.total_integration_seconds - b.total_integration_seconds; break;
        case "frames": cmp = a.total_frames - b.total_frames; break;
        case "date_range": cmp = (a.first_session ?? "").localeCompare(b.first_session ?? ""); break;
      }
      return asc ? cmp : -cmp;
    });
  });
  const mosaicSortIcon = (key: MosaicSortKey) =>
    mosaicSortKey() === key ? (mosaicSortAsc() ? " ▴" : " ▾") : "";

  createEffect(() => localStorage.setItem("mosaics-keywords-collapsed", String(keywordsCollapsed())));
  createEffect(() => localStorage.setItem("mosaics-suggestions-collapsed", String(suggestionsCollapsed())));

  // Custom column support for mosaics
  const mosaicCustomColumns = () =>
    (settingsCtx.customColumns() ?? []).filter(c => c.applies_to === "mosaic");

  const vis = () => settingsCtx.columnVisibility();

  function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
    const v = vis() ?? {
      dashboard: { builtin: {}, custom: {} },
      session_table: { builtin: {}, custom: {} },
      session_detail: { builtin: {}, custom: {} },
      mosaic_table: { builtin: {}, custom: {} },
    };
    const updated = structuredClone(v);
    if (!updated.mosaic_table) updated.mosaic_table = { builtin: {}, custom: {} };
    if (!updated.mosaic_table[kind]) updated.mosaic_table[kind] = {};
    updated.mosaic_table[kind][key] = visible;
    settingsCtx.saveColumnVisibility(updated);
  }

  const keywords = () => settingsCtx.settings()?.general?.mosaic_keywords ?? ["Panel", "P"];

  const GAP_OPTIONS = [
    { label: "No grouping", value: 0 },
    { label: "1 week", value: 7 },
    { label: "2 weeks", value: 14 },
    { label: "1 month", value: 30 },
    { label: "3 months", value: 90 },
    { label: "6 months", value: 180 },
    { label: "1 year", value: 365 },
  ];

  const campaignGap = () =>
    settingsCtx.settings()?.general?.mosaic_campaign_gap_days ?? 0;

  // Load lifecycle: skeleton rows while the first fetch is in flight, and an
  // inline error with Retry if it fails, instead of a timed info toast that
  // silently swallowed failures.
  const [loading, setLoading] = createSignal(false);
  const [loadError, setLoadError] = createSignal(false);

  const refresh = async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setLoadError(false);
    }
    try {
      const [s, m] = await Promise.all([
        apiClient.GET("/api/mosaics/suggestions").then(unwrap),
        apiClient.GET("/api/mosaics").then(unwrap),
      ]);
      cachedSuggestions = s;
      cachedMosaics = m;
      setSuggestions(s);
      setMosaics(m);
      setLoadError(false);
    } catch {
      if (!silent) setLoadError(true);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  onMount(() => {
    if (cachedSuggestions && cachedMosaics) {
      setSuggestions(cachedSuggestions);
      setMosaics(cachedMosaics);
      refresh(true);
    } else {
      refresh();
    }
  });

  // Keywords
  const addKeyword = async () => {
    const kw = newKeyword().trim();
    if (!kw || keywords().some((k) => k.toLowerCase() === kw.toLowerCase())) return;
    const updated = [...keywords(), kw];
    try {
      const current = settingsCtx.settings()?.general;
      await settingsCtx.saveGeneral({ ...current!, mosaic_keywords: updated });
      setNewKeyword("");
      showToast(`Added keyword "${kw}"`);
    } catch {
      showToast("Failed to save keyword", "error");
    }
  };

  const removeKeyword = async (kw: string) => {
    const updated = keywords().filter((k) => k !== kw);
    try {
      const current = settingsCtx.settings()?.general;
      await settingsCtx.saveGeneral({ ...current!, mosaic_keywords: updated });
      showToast(`Removed keyword "${kw}"`);
    } catch {
      showToast("Failed to remove keyword", "error");
    }
  };

  const handleDetect = async () => {
    if (detecting()) return;
    setDetecting(true);
    await emitWithToast({
      action: () => apiClient.POST("/api/mosaics/detect").then(unwrap),
      pendingLabel: "Running mosaic detection...",
      successLabel: "Mosaic detection complete",
      errorLabel: "Mosaic detection failed",
      category: "mosaic",
      taskLabel: "Mosaic detection",
      timeout: 120_000,
    });
    setDetecting(false);
    refresh(true);
  };

  // Initialize panel selection when expanding a suggestion (all selected by default)
  const initSelection = (s: MosaicSuggestionResponse) => {
    if (!selectedPanels()[s.id]) {
      setSelectedPanels((prev) => ({
        ...prev,
        [s.id]: new Set(s.panel_labels),
      }));
    }
  };

  const togglePanel = (suggestionId: string, label: string) => {
    setSelectedPanels((prev) => {
      const cur = new Set(prev[suggestionId] ?? []);
      if (cur.has(label)) cur.delete(label);
      else cur.add(label);
      return { ...prev, [suggestionId]: cur };
    });
  };

  const toggleAllPanels = (s: MosaicSuggestionResponse) => {
    const cur = selectedPanels()[s.id];
    const allSelected = cur && cur.size === s.panel_labels.length;
    setSelectedPanels((prev) => ({
      ...prev,
      [s.id]: allSelected ? new Set<string>() : new Set(s.panel_labels),
    }));
  };

  const isPanelSelected = (suggestionId: string, label: string): boolean => {
    return selectedPanels()[suggestionId]?.has(label) ?? true;
  };

  // Totals reflecting only the currently selected panels of a suggestion.
  // When all panels are selected, this matches the full suggestion totals.
  const selectedTotals = (s: MosaicSuggestionResponse) => {
    const selectedSessions = s.sessions.filter((r) => isPanelSelected(s.id, r.panel_label));
    const panels = new Set(selectedSessions.map((r) => r.panel_label)).size;
    const frames = selectedSessions.reduce((a, r) => a + r.frames, 0);
    const integration = selectedSessions.reduce((a, r) => a + r.integration_seconds, 0);
    return { panels, frames, integration };
  };

  // Suggestions
  const handleAccept = async (s: MosaicSuggestionResponse) => {
    if (acceptingId()) return; // prevent concurrent accepts
    const sel = selectedPanels()[s.id];
    const selected = sel && sel.size < s.panel_labels.length ? [...sel] : undefined;
    if (sel && sel.size === 0) {
      showToast("Select at least one panel", "error");
      return;
    }
    setAcceptingId(s.id);
    try {
      await apiClient
        .POST("/api/mosaics/suggestions/{suggestion_id}/accept", {
          params: { path: { suggestion_id: s.id } },
          body: { selected_panels: selected ?? null },
        })
        .then(unwrap);
      showToast(`Created mosaic "${s.suggested_name}"`);
      setExpandedSuggestion(null);
      // Update both lists before allowing next accept
      const [newSuggestions, newMosaics] = await Promise.all([
        apiClient.GET("/api/mosaics/suggestions").then(unwrap),
        apiClient.GET("/api/mosaics").then(unwrap),
      ]);
      setSuggestions(newSuggestions);
      setMosaics(newMosaics);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Server already returns a specific detail (e.g. name already exists)
        showToast(err.message, "error");
      } else if (err instanceof ApiError) {
        showToast(`Failed to accept suggestion: ${err.message}`, "error");
      } else {
        showToast("Failed to accept suggestion", "error");
      }
    } finally {
      setAcceptingId(null);
    }
  };

  const handleDismiss = async (s: MosaicSuggestionResponse) => {
    try {
      await apiClient
        .POST("/api/mosaics/suggestions/{suggestion_id}/dismiss", {
          params: { path: { suggestion_id: s.id } },
        })
        .then(unwrap);
      setConfirmDismissId(null);
      setExpandedSuggestion(null);
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    } catch {
      showToast("Failed to dismiss suggestion", "error");
    }
  };

  // Bulk action state
  const [bulkAction, setBulkAction] = createSignal<string | null>(null); // "accepting" | "dismissing" | "deleting"
  const [bulkProgress, setBulkProgress] = createSignal({ done: 0, total: 0 });
  const [selectedSuggestionIds, setSelectedSuggestionIds] = createSignal<Set<string>>(new Set());
  const [selectedMosaicIds, setSelectedMosaicIds] = createSignal<Set<string>>(new Set());

  const toggleSuggestionSelection = (id: string) => {
    setSelectedSuggestionIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllSuggestions = () => {
    const visible = filteredSuggestions().map((s) => s.id);
    const allSelected = visible.length > 0 && visible.every((id) => selectedSuggestionIds().has(id));
    if (allSelected) {
      setSelectedSuggestionIds((prev) => {
        const next = new Set(prev);
        for (const id of visible) next.delete(id);
        return next;
      });
    } else {
      setSelectedSuggestionIds((prev) => {
        const next = new Set(prev);
        for (const id of visible) next.add(id);
        return next;
      });
    }
  };

  const selectedSuggestionCount = () => {
    const visible = new Set(filteredSuggestions().map((s) => s.id));
    return [...selectedSuggestionIds()].filter((id) => visible.has(id)).length;
  };

  const toggleMosaicSelection = (id: string) => {
    setSelectedMosaicIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllMosaics = () => {
    const all = mosaics().map((m) => m.id);
    const allSelected = selectedMosaicIds().size === all.length;
    setSelectedMosaicIds(allSelected ? new Set<string>() : new Set(all));
  };

  const handleBulkAccept = async () => {
    const sel = selectedSuggestionIds();
    const items = sel.size > 0
      ? filteredSuggestions().filter((s) => sel.has(s.id))
      : filteredSuggestions();
    if (items.length === 0) return;
    setBulkAction("accepting");
    setBulkProgress({ done: 0, total: items.length });
    let succeeded = 0;
    const failures: { name: string; reason: string }[] = [];
    for (const s of items) {
      try {
        const panelSel = selectedPanels()[s.id];
        const selected = panelSel && panelSel.size < s.panel_labels.length ? [...panelSel] : undefined;
        await apiClient
          .POST("/api/mosaics/suggestions/{suggestion_id}/accept", {
            params: { path: { suggestion_id: s.id } },
            body: { selected_panels: selected ?? null },
          })
          .then(unwrap);
        succeeded++;
        setBulkProgress({ done: succeeded, total: items.length });
        setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
        setSelectedSuggestionIds((prev) => {
          const next = new Set(prev);
          next.delete(s.id);
          return next;
        });
      } catch (err) {
        const reason = err instanceof ApiError ? err.message : "Unknown error";
        failures.push({ name: s.suggested_name, reason });
      }
    }
    try {
      const [newSuggestions, newMosaics] = await Promise.all([
        apiClient.GET("/api/mosaics/suggestions").then(unwrap),
        apiClient.GET("/api/mosaics").then(unwrap),
      ]);
      setSuggestions(newSuggestions);
      setMosaics(newMosaics);
    } catch {}
    setBulkAction(null);
    if (failures.length > 0) {
      const detail = failures.map((f) => `${f.name} (${f.reason})`).join("; ");
      showToast(
        `Accepted ${succeeded} of ${items.length}. ${failures.length} failed: ${detail}`,
        "error",
      );
    } else {
      showToast(`Accepted ${succeeded} of ${items.length} suggestion(s)`);
    }
  };

  const handleBulkDismiss = async () => {
    const sel = selectedSuggestionIds();
    const items = sel.size > 0
      ? filteredSuggestions().filter((s) => sel.has(s.id))
      : filteredSuggestions();
    if (items.length === 0) return;
    setBulkAction("dismissing");
    setBulkProgress({ done: 0, total: items.length });
    let succeeded = 0;
    for (const s of items) {
      try {
        await apiClient
          .POST("/api/mosaics/suggestions/{suggestion_id}/dismiss", {
            params: { path: { suggestion_id: s.id } },
          })
          .then(unwrap);
        succeeded++;
        setBulkProgress({ done: succeeded, total: items.length });
        setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
        setSelectedSuggestionIds((prev) => {
          const next = new Set(prev);
          next.delete(s.id);
          return next;
        });
      } catch {
        // Skip failures, continue with next
      }
    }
    setBulkAction(null);
    showToast(`Dismissed ${succeeded} of ${items.length} suggestion(s)`);
  };

  const handleBulkDeleteMosaics = async () => {
    const ids = [...selectedMosaicIds()];
    if (ids.length === 0) return;
    setBulkAction("deleting");
    setBulkProgress({ done: 0, total: ids.length });
    let succeeded = 0;
    for (const id of ids) {
      try {
        await apiClient.DELETE("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: id } } }).then(unwrap);
        succeeded++;
        setBulkProgress({ done: succeeded, total: ids.length });
        // Remove from list immediately
        setMosaics((prev) => prev.filter((m) => m.id !== id));
        setSelectedMosaicIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      } catch {
        // Skip failures, continue with next
      }
    }
    // Refresh suggestions (some may now be valid again)
    try {
      const newSuggestions = await apiClient.GET("/api/mosaics/suggestions").then(unwrap);
      setSuggestions(newSuggestions);
    } catch {}
    setBulkAction(null);
    setExpandedId(null);
    showToast(`Deleted ${succeeded} of ${ids.length} mosaic(s)`);
  };

  // Expand/collapse mosaic
  const toggleExpand = async (id: string) => {
    if (expandedId() === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    setAddingPanelFor(null);
    if (!details()[id]) {
      try {
        const detail = await apiClient
          .GET("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: id } } })
          .then(unwrap);
        setDetails((prev) => ({ ...prev, [id]: detail }));
      } catch {
        showToast("Failed to load mosaic details", "error");
      }
    }
  };

  // Panel search
  const handlePanelSearch = async (query: string) => {
    setPanelSearch(query);
    setSelectedTarget(null);
    if (query.length < 2) {
      setSearchResults([]);
      return;
    }
    try {
      const results = await apiClient
        .GET("/api/targets/search", { params: { query: { q: query } } })
        .then(unwrap);
      setSearchResults(results);
    } catch {
      setSearchResults([]);
    }
  };

  const selectTarget = (t: TargetSearchResultFuzzy) => {
    setSelectedTarget(t);
    setPanelSearch(t.primary_name);
    setSearchResults([]);
  };

  const handleAddPanel = async (mosaicId: string) => {
    const target = selectedTarget();
    const label = panelLabel().trim();
    if (!target || !label) {
      showToast("Select a target and enter a panel label", "error");
      return;
    }
    try {
      await apiClient
        .POST("/api/mosaics/{mosaic_id}/panels", {
          params: { path: { mosaic_id: mosaicId } },
          body: { target_id: target.id, panel_label: label },
        })
        .then(unwrap);
      showToast(`Added panel "${label}"`);
      setPanelSearch("");
      setPanelLabel("");
      setSelectedTarget(null);
      setAddingPanelFor(null);
      // Refresh detail
      const detail = await apiClient
        .GET("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: mosaicId } } })
        .then(unwrap);
      setDetails((prev) => ({ ...prev, [mosaicId]: detail }));
      // Refresh summary
      const allMosaics = await apiClient.GET("/api/mosaics").then(unwrap);
      setMosaics(allMosaics);
    } catch {
      showToast("Failed to add panel", "error");
    }
  };

  const handleRemovePanel = async (mosaicId: string, panelId: string) => {
    try {
      await apiClient
        .DELETE("/api/mosaics/{mosaic_id}/panels/{panel_id}", {
          params: { path: { mosaic_id: mosaicId, panel_id: panelId } },
        })
        .then(unwrap);
      showToast("Panel removed");
      const detail = await apiClient
        .GET("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: mosaicId } } })
        .then(unwrap);
      setDetails((prev) => ({ ...prev, [mosaicId]: detail }));
      const allMosaics = await apiClient.GET("/api/mosaics").then(unwrap);
      setMosaics(allMosaics);
    } catch {
      showToast("Failed to remove panel", "error");
    }
  };

  const handleDeleteMosaic = async (id: string) => {
    try {
      await apiClient.DELETE("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: id } } }).then(unwrap);
      showToast("Mosaic deleted");
      setConfirmDeleteId(null);
      setExpandedId(null);
      await refresh();
    } catch {
      showToast("Failed to delete mosaic", "error");
    }
  };

  const handleRename = async (id: string) => {
    const name = renameValue().trim();
    if (!name) return;
    try {
      await apiClient
        .PUT("/api/mosaics/{mosaic_id}", { params: { path: { mosaic_id: id } }, body: { name } })
        .then(unwrap);
      showToast(`Renamed mosaic to "${name}"`);
      setRenamingId(null);
      setRenameValue("");
      await refresh();
    } catch {
      showToast("Failed to rename mosaic", "error");
    }
  };

  const handleCreate = async () => {
    const name = newMosaicName().trim();
    if (!name) return;
    try {
      await apiClient.POST("/api/mosaics", { body: { name, panels: [] } }).then(unwrap);
      showToast(`Created mosaic "${name}"`);
      setNewMosaicName("");
      setShowCreate(false);
      await refresh();
    } catch {
      showToast("Failed to create mosaic", "error");
    }
  };

  // Compute total column count for expanded row colspan
  const totalColumns = () => {
    let count = 1; // Name always visible
    if (isColumnVisible(vis(), "mosaic_table", "builtin", "panels")) count++;
    if (isColumnVisible(vis(), "mosaic_table", "builtin", "integration")) count++;
    if (isColumnVisible(vis(), "mosaic_table", "builtin", "frames")) count++;
    if (isColumnVisible(vis(), "mosaic_table", "builtin", "date_range")) count++;
    count += mosaicCustomColumns().filter(c => isColumnVisible(vis(), "mosaic_table", "custom", c.slug)).length;
    count++; // actions column
    return count;
  };

  return (
    <div class="space-y-4">
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">

      {/* Detection Keywords */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center cursor-pointer select-none" onClick={() => setKeywordsCollapsed(!keywordsCollapsed())}>
          <div class="flex items-center gap-2">
            <span class="text-theme-text-secondary text-xs">{keywordsCollapsed() ? "▶" : "▼"}</span>
            <h3 class="text-theme-text-primary font-medium">Detection Keywords</h3>
            <HelpPopover title="Detection Keywords">
              <p>Token strings used to detect mosaic panels inside target names. When a target name contains a keyword followed by a number, the target is treated as a panel candidate.</p>
              <p>Example: with keywords "Panel" and "P", the names "M31 Panel 1", "M31 Panel 2", and "NGC 7000 P2" are all recognized as panels of the same mosaic.</p>
              <p>Run Detection re-scans targets after keyword changes to rebuild the suggestion list.</p>
            </HelpPopover>
          </div>
          <Show when={isAdmin()}>
            <Button
              variant="primary"
              onClick={(e) => { e.stopPropagation(); handleDetect(); }}
              disabled={detecting()}
            >
              {detecting() ? "Detecting..." : "Run Detection"}
            </Button>
          </Show>
        </div>
        <Show when={!keywordsCollapsed()}>
        <div class="flex flex-wrap gap-2">
          <For each={keywords()}>
            {(kw) => (
              <span class="inline-flex items-center gap-1 px-2 py-1 text-sm bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary">
                {kw}
                <Show when={isAdmin()}>
                  <IconButton
                    variant="danger"
                    onClick={() => removeKeyword(kw)}
                    class="ml-1 text-xs"
                    title="Remove"
                  >
                    &times;
                  </IconButton>
                </Show>
              </span>
            )}
          </For>
        </div>
        <Show when={isAdmin()}>
          <div class="flex gap-2">
            <input
              type="text"
              value={newKeyword()}
              onInput={(e) => setNewKeyword(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && addKeyword()}
              placeholder="New keyword..."
              class="flex-1 px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent"
            />
            <Button variant="primary" size="sm" onClick={addKeyword}>
              Add
            </Button>
          </div>
        </Show>
        </Show>
      </div>

      {/* Auto-detected Suggestions */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center cursor-pointer select-none" onClick={() => setSuggestionsCollapsed(!suggestionsCollapsed())}>
          <div class="flex items-center gap-2">
            <span class="text-theme-text-secondary text-xs">{suggestionsCollapsed() ? "▶" : "▼"}</span>
            <h3 class="text-theme-text-primary font-medium">
              Suggestions ({suggestionFilter() ? `${filteredSuggestions().length}/` : ""}{suggestions().length})
            </h3>
            <HelpPopover title="Suggestions">
              <p>Proposed mosaic groupings derived from detection. Each suggestion bundles targets that share a base name and differ only in panel index.</p>
              <p>Accept a suggestion to create a mosaic from those panels; dismiss to hide it from future detection runs.</p>
              <p>The campaign gap selector controls how sessions for the same panel are split: captures more than the selected gap apart become separate campaigns. Re-run detection after changing the gap.</p>
              <p>Example: with a 30-day gap, an M31 panel shot in October and again in January produces two campaigns; with a 180-day gap, both nights merge into one.</p>
            </HelpPopover>
          </div>
          <Show when={isAdmin()}>
            <select
              value={campaignGap()}
              onClick={(e) => e.stopPropagation()}
              onChange={async (e) => {
                const val = parseInt(e.currentTarget.value, 10);
                try {
                  const current = settingsCtx.settings()?.general;
                  await settingsCtx.saveGeneral({ ...current!, mosaic_campaign_gap_days: val });
                  const label = GAP_OPTIONS.find((o) => o.value === val)?.label ?? String(val);
                  showToast(`Campaign gap set to ${label}. Re-run detection to apply.`);
                } catch {
                  showToast("Failed to save campaign gap", "error");
                }
              }}
              class="px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:outline-none focus:border-theme-accent"
            >
              <For each={GAP_OPTIONS}>
                {(opt) => (
                  <option value={opt.value} selected={opt.value === campaignGap()}>
                    {opt.label}
                  </option>
                )}
              </For>
            </select>
          </Show>
        </div>
        <Show when={!suggestionsCollapsed()}>
        <Show when={suggestions().length > 4}>
          <input
            type="text"
            value={suggestionFilter()}
            onInput={(e) => setSuggestionFilter(e.currentTarget.value)}
            placeholder="Filter suggestions..."
            class="w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent"
          />
        </Show>
        {/* Bulk action progress bar */}
        <Show when={bulkAction() && (bulkAction() === "accepting" || bulkAction() === "dismissing")}>
          <div class="space-y-1.5">
            <div class="flex justify-between text-xs text-theme-text-secondary">
              <span>{bulkAction() === "accepting" ? "Accepting" : "Dismissing"} suggestions...</span>
              <span>{bulkProgress().done}/{bulkProgress().total}</span>
            </div>
            <div class="w-full h-1.5 bg-theme-base rounded-full overflow-hidden">
              <div
                class="h-full bg-theme-accent rounded-full transition-all duration-300"
                style={{ width: `${bulkProgress().total > 0 ? (bulkProgress().done / bulkProgress().total) * 100 : 0}%` }}
              />
            </div>
          </div>
        </Show>

        <Show
          when={suggestions().length > 0}
          fallback={
            <p class="text-sm text-theme-text-secondary">
              No pending suggestions. Run detection to scan for mosaic panels.
            </p>
          }
        >
          {/* Bulk action buttons for suggestions */}
          <Show when={isAdmin() && filteredSuggestions().length > 0 && !bulkAction()}>
            <div class="flex items-center gap-2">
              <input
                type="checkbox"
                checked={filteredSuggestions().length > 0 && filteredSuggestions().every((s) => selectedSuggestionIds().has(s.id))}
                onChange={toggleAllSuggestions}
                class="accent-[var(--color-accent)]"
              />
              <span class="text-xs text-theme-text-secondary">
                {selectedSuggestionCount() > 0 ? `${selectedSuggestionCount()} selected` : "Select all"}
              </span>
              <div class="flex gap-2 ml-auto">
                <Button variant="primary" size="sm" onClick={handleBulkAccept}>
                  Accept {selectedSuggestionCount() > 0 ? `(${selectedSuggestionCount()})` : `All (${filteredSuggestions().length})`}
                </Button>
                <Button variant="danger" size="sm" onClick={handleBulkDismiss}>
                  Dismiss {selectedSuggestionCount() > 0 ? `(${selectedSuggestionCount()})` : `All (${filteredSuggestions().length})`}
                </Button>
              </div>
            </div>
          </Show>
          <div class="space-y-2">
            <For each={filteredSuggestions()}>
              {(s) => {
                const uniqueTargets = () => [...new Set(s.target_ids)];
                // Header summary reflects the currently selected panel subset
                const totals = () => selectedTotals(s);

                type SortKey = "panel_label" | "object_name" | "date" | "filter_used" | "frames" | "integration_seconds";
                const [sortKey, setSortKey] = createSignal<SortKey>("panel_label");
                const [sortAsc, setSortAsc] = createSignal(true);
                const toggleSort = (key: SortKey) => {
                  if (sortKey() === key) setSortAsc(!sortAsc());
                  else { setSortKey(key); setSortAsc(true); }
                };
                const sortedSessions = () => {
                  const key = sortKey();
                  const asc = sortAsc();
                  return [...s.sessions].sort((a, b) => {
                    const av = a[key] ?? "";
                    const bv = b[key] ?? "";
                    const cmp = typeof av === "number" ? av - (bv as number) : String(av).localeCompare(String(bv));
                    return asc ? cmp : -cmp;
                  });
                };
                const sortIcon = (key: SortKey) =>
                  sortKey() === key ? (sortAsc() ? " ▴" : " ▾") : "";

                return (
                  <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)] overflow-hidden">
                    <div class="flex items-center p-3">
                      <Show when={isAdmin()}>
                        <input
                          type="checkbox"
                          checked={selectedSuggestionIds().has(s.id)}
                          onChange={() => toggleSuggestionSelection(s.id)}
                          class="accent-[var(--color-accent)] mr-2 shrink-0"
                        />
                      </Show>
                      <button
                        onClick={() => {
                          const next = expandedSuggestion() === s.id ? null : s.id;
                          setExpandedSuggestion(next);
                          if (next) initSelection(s);
                        }}
                        class="flex-1 flex items-center justify-between text-left hover:bg-theme-base/80 transition-colors"
                      >
                        <div class="flex-1">
                          <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-theme-text-primary text-sm font-medium">
                              {s.suggested_name}
                            </span>
                            <Show when={s.confidence}>
                              <span
                                class="text-[10px] uppercase tracking-wide font-medium rounded px-1.5 py-0.5 border"
                                classList={{
                                  "bg-theme-success/15 text-theme-success border-theme-success/30": s.confidence === "high",
                                  "bg-theme-warning/15 text-theme-warning border-theme-warning/30": s.confidence !== "high",
                                }}
                                title={s.confidence === "high"
                                  ? "Name and position agree on these panels"
                                  : "Single signal or conflicting evidence; review before accepting"}
                              >
                                {s.confidence === "high" ? "High confidence" : "Low confidence"}
                              </span>
                            </Show>
                            <Show when={s.discovery_source}>
                              <span class="text-[10px] text-theme-text-secondary border border-theme-border rounded px-1.5 py-0.5">
                                {s.discovery_source === "both"
                                  ? "name + position"
                                  : s.discovery_source}
                              </span>
                            </Show>
                          </div>
                          <div class="text-xs text-theme-text-secondary mt-0.5">
                            {totals().panels} panels
                            {" · "}
                            <span classList={{ "text-theme-warning": totals().frames === 0 }}>
                              {totals().frames} frames
                            </span>
                            {" · "}
                            {formatIntegration(totals().integration)}
                            <Show when={(s.other_session_count ?? 0) > 0}>
                              {" · "}
                              <span class="text-theme-warning">
                                +{s.other_session_count} more sessions
                              </span>
                            </Show>
                          </div>
                        </div>
                        <span class="text-theme-text-secondary text-xs ml-2">
                          {expandedSuggestion() === s.id ? "▲" : "▼"}
                        </span>
                      </button>
                      <Show when={isAdmin()}>
                        <div class="flex items-center gap-2 ml-3 shrink-0">
                          {(() => {
                            const sel = selectedPanels()[s.id];
                            const count = sel?.size ?? s.panel_labels.length;
                            const noneSelected = !!sel && sel.size === 0;
                            return (
                              <Button
                                variant="primary"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); handleAccept(s); }}
                                disabled={!!acceptingId() || !!bulkAction() || noneSelected}
                                title={noneSelected ? "Select at least one panel to accept" : undefined}
                              >
                                {acceptingId() === s.id ? "Accepting..." : "Accept"}
                                {count < s.panel_labels.length ? ` (${count}/${s.panel_labels.length})` : ""}
                              </Button>
                            );
                          })()}
                          <Show
                            when={confirmDismissId() === s.id}
                            fallback={
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); setConfirmDismissId(s.id); }}
                                disabled={!!bulkAction()}
                              >
                                Dismiss
                              </Button>
                            }
                          >
                            <div class="flex items-center gap-2">
                              <span
                                class="text-xs text-theme-text-secondary"
                                title="Dismissals are not permanent: re-running detection can resurface this suggestion."
                              >
                                Dismiss?
                              </span>
                              <Button
                                variant="danger"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); handleDismiss(s); }}
                              >
                                Confirm
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); setConfirmDismissId(null); }}
                              >
                                Cancel
                              </Button>
                            </div>
                          </Show>
                        </div>
                      </Show>
                    </div>

                    <Show when={expandedSuggestion() === s.id}>
                      <div class="border-t border-theme-border">
                        {/* Low-confidence flags */}
                        <Show when={s.flags && s.flags.length > 0}>
                          <div class="mx-3 mt-3 p-2 rounded-[var(--radius-sm)] border border-theme-warning/30 bg-theme-warning/10">
                            <div class="text-[11px] font-medium text-theme-warning mb-1">
                              Review notes
                            </div>
                            <ul class="list-disc list-inside space-y-0.5">
                              <For each={s.flags}>
                                {(flag) => (
                                  <li class="text-xs text-theme-text-secondary">{flag}</li>
                                )}
                              </For>
                            </ul>
                          </div>
                        </Show>

                        {/* Target link */}
                        <div class="px-3 pt-3 pb-1">
                          <For each={uniqueTargets()}>
                            {(tid) => (
                              <a
                                href={`/targets/${tid}`}
                                class="text-xs text-theme-accent hover:underline"
                              >
                                {s.target_names[tid] || tid}
                              </a>
                            )}
                          </For>
                        </div>

                        {/* Session table */}
                        <Show when={s.sessions.length > 0}>
                          <table class="w-full text-xs">
                            <thead>
                              <tr class="text-theme-text-secondary border-b border-theme-border/50">
                                <th class="px-3 py-1.5 w-6">
                                  <input
                                    type="checkbox"
                                    checked={(selectedPanels()[s.id]?.size ?? s.panel_labels.length) === s.panel_labels.length}
                                    onChange={() => toggleAllPanels(s)}
                                    class="accent-[var(--color-accent)]"
                                  />
                                </th>
                                {([["panel_label", "Panel", "left"], ["object_name", "OBJECT", "left"], ["date", "Date", "left"], ["filter_used", "Filter", "left"], ["frames", "Frames", "right"], ["integration_seconds", "Integration", "right"]] as const).map(([key, label, align]) => (
                                  <th
                                    class={`text-${align} px-3 py-1.5 font-medium cursor-pointer select-none hover:text-theme-text-primary transition-colors`}
                                    onClick={() => toggleSort(key)}
                                  >
                                    {label}{sortIcon(key)}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              <For each={sortedSessions()}>
                                {(sess) => (
                                  <tr
                                    class="border-b border-theme-border/30 hover:bg-theme-base/30"
                                    classList={{ "opacity-40": !isPanelSelected(s.id, sess.panel_label) }}
                                  >
                                    <td class="px-3 py-1.5">
                                      <input
                                        type="checkbox"
                                        checked={isPanelSelected(s.id, sess.panel_label)}
                                        onChange={() => togglePanel(s.id, sess.panel_label)}
                                        class="accent-[var(--color-accent)]"
                                      />
                                    </td>
                                    <td class="px-3 py-1.5 text-theme-text-primary">{sess.panel_label}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary">{sess.object_name}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary">{sess.date}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary">{sess.filter_used || "—"}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary text-right">{sess.frames}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary text-right">{formatIntegration(sess.integration_seconds)}</td>
                                  </tr>
                                )}
                              </For>
                            </tbody>
                          </table>
                        </Show>

                        {/* Tile preview */}
                        <Show when={s.preview_panels && s.preview_panels.length > 0}>
                          <div class="px-3 py-3 border-t border-theme-border/50">
                            <div class="text-[11px] font-medium text-theme-text-secondary mb-2">
                              Tile preview
                            </div>
                            <Show
                              when={s.preview_panels.some((p) => isPanelSelected(s.id, p.panel_label))}
                              fallback={
                                <p class="text-xs text-theme-text-secondary">No panels selected.</p>
                              }
                            >
                              <KonvaMosaicArranger
                                previewMode={true}
                                panels={s.preview_panels
                                  .filter((p) => isPanelSelected(s.id, p.panel_label))
                                  .map((p): PreviewPanel => ({
                                    target_id: p.target_id,
                                    panel_label: p.panel_label,
                                    ra: p.ra,
                                    dec: p.dec,
                                    thumbnail_url: p.thumbnail_url,
                                  }))}
                                rotationAngle={0}
                                pixelCoords={false}
                                availableFilters={[]}
                                selectedFilter={null}
                                onFilterChange={() => {}}
                                filterLoading={false}
                                thumbnailOverrides={null}
                              />
                            </Show>
                          </div>
                        </Show>

                      </div>
                    </Show>
                  </div>
                );
              }}
            </For>
          </div>
        </Show>
        </Show>
      </div>

      </div>{/* end top row grid */}

      {/* Mosaics section - full width */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center cursor-pointer select-none" onClick={() => setMosaicsCollapsed(!mosaicsCollapsed())}>
          <div class="flex items-center gap-2">
            <span class="text-theme-text-secondary text-xs">{mosaicsCollapsed() ? "▶" : "▼"}</span>
            <h3 class="text-theme-text-primary font-medium">
              Mosaics ({mosaics().length})
            </h3>
            <HelpPopover title="Mosaics" align="right">
              <p>Existing mosaic projects. Each mosaic collects one or more target panels and tracks their integration, per-filter breakdown, and layout.</p>
              <p>Create a mosaic manually with the Create Mosaic button, or accept a detection suggestion from the left column. Select one or more rows to enable bulk delete.</p>
              <p>Example: "M31 Mosaic 2x3" holds six target panels; opening the mosaic detail page shows the composite image and per-panel progress.</p>
            </HelpPopover>
          </div>
          <div class="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <Show when={isAdmin()}>
            <div class="flex gap-2">
              <Show when={selectedMosaicIds().size > 0 && !bulkAction()}>
                <Button variant="danger" size="sm" onClick={handleBulkDeleteMosaics}>
                  Delete Selected ({selectedMosaicIds().size})
                </Button>
              </Show>
              <Show when={mosaics().some(m => m.needs_review)}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async (e) => {
                    e.stopPropagation();
                    await apiClient.POST("/api/mosaics/clear-reviews").then(unwrap);
                    await refresh();
                  }}
                >
                  Clear All Reviews
                </Button>
              </Show>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowCreate(!showCreate())}
              >
                {showCreate() ? "Cancel" : "Create Mosaic"}
              </Button>
            </div>
          </Show>
          </div>
        </div>

        <Show when={!mosaicsCollapsed()}>
        {/* Bulk delete progress bar */}
        <Show when={bulkAction() === "deleting"}>
          <div class="space-y-1.5">
            <div class="flex justify-between text-xs text-theme-text-secondary">
              <span>Deleting mosaics...</span>
              <span>{bulkProgress().done}/{bulkProgress().total}</span>
            </div>
            <div class="w-full h-1.5 bg-theme-base rounded-full overflow-hidden">
              <div
                class="h-full bg-theme-danger rounded-full transition-all duration-300"
                style={{ width: `${bulkProgress().total > 0 ? (bulkProgress().done / bulkProgress().total) * 100 : 0}%` }}
              />
            </div>
          </div>
        </Show>

        {/* Create form */}
        <Show when={showCreate()}>
          <div class="flex gap-2 p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
            <input
              type="text"
              value={newMosaicName()}
              onInput={(e) => setNewMosaicName(e.currentTarget.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              placeholder="Mosaic name..."
              class="flex-1 px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent"
            />
            <Button variant="primary" onClick={handleCreate}>
              Create
            </Button>
          </div>
        </Show>

        {/* Select all checkbox */}
        <Show when={isAdmin() && mosaics().length > 1}>
          <div class="flex items-center gap-2 text-xs text-theme-text-secondary">
            <input
              type="checkbox"
              checked={selectedMosaicIds().size === mosaics().length && mosaics().length > 0}
              onChange={toggleAllMosaics}
              class="accent-[var(--color-accent)]"
            />
            <span>Select all</span>
          </div>
        </Show>

        <Show
          when={mosaics().length > 0}
          fallback={
            <Show
              when={loadError()}
              fallback={
                <Show
                  when={loading()}
                  fallback={<p class="text-sm text-theme-text-secondary">No mosaics yet.</p>}
                >
                  <div class="space-y-2">
                    <For each={Array.from({ length: 4 })}>
                      {() => (
                        <div class="flex items-center gap-3 p-3 border border-theme-border rounded-[var(--radius-sm)]">
                          <div class="h-4 w-40 bg-theme-elevated rounded animate-pulse" />
                          <div class="h-4 w-16 bg-theme-elevated rounded animate-pulse ml-auto" />
                          <div class="h-4 w-16 bg-theme-elevated rounded animate-pulse" />
                        </div>
                      )}
                    </For>
                  </div>
                </Show>
              }
            >
              <div class="px-3 py-2 rounded border border-theme-error/30 bg-theme-error/10 text-theme-error text-sm flex items-center justify-between">
                <span>Failed to load mosaics.</span>
                <button onClick={() => refresh()} class="ml-3 underline hover:no-underline">Retry</button>
              </div>
            </Show>
          }
        >
          <table class="w-full text-sm border-collapse">
            <thead>
              <tr class="sticky top-0 bg-theme-surface border-b border-theme-border-em z-10">
                <th class="text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap cursor-pointer select-none hover:text-theme-text-secondary transition-colors" onClick={() => toggleMosaicSort("name")}>Name{mosaicSortIcon("name")}</th>
                <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "panels")}>
                  <th class="text-right py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap cursor-pointer select-none hover:text-theme-text-secondary transition-colors" onClick={() => toggleMosaicSort("panels")}>Panels{mosaicSortIcon("panels")}</th>
                </Show>
                <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "integration")}>
                  <th class="text-right py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap cursor-pointer select-none hover:text-theme-text-secondary transition-colors" onClick={() => toggleMosaicSort("integration")}>Integration{mosaicSortIcon("integration")}</th>
                </Show>
                <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "frames")}>
                  <th class="text-right py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap cursor-pointer select-none hover:text-theme-text-secondary transition-colors" onClick={() => toggleMosaicSort("frames")}>Frames{mosaicSortIcon("frames")}</th>
                </Show>
                <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "date_range")}>
                  <th class="text-right py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap cursor-pointer select-none hover:text-theme-text-secondary transition-colors" onClick={() => toggleMosaicSort("date_range")}>Date Range{mosaicSortIcon("date_range")}</th>
                </Show>
                <For each={mosaicCustomColumns()}>
                  {(col) => (
                    <Show when={isColumnVisible(vis(), "mosaic_table", "custom", col.slug)}>
                      <th class="text-right py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap">{col.name}</th>
                    </Show>
                  )}
                </For>
                <th class="text-left py-2 px-3 text-label font-medium uppercase tracking-wider text-theme-text-tertiary whitespace-nowrap">
                  <ColumnPicker
                    table="mosaic_table"
                    builtinColumns={[
                      { key: "name", label: "Name", alwaysVisible: true },
                      { key: "panels", label: "Panels" },
                      { key: "integration", label: "Integration" },
                      { key: "frames", label: "Frames" },
                      { key: "date_range", label: "Date Range" },
                    ]}
                    customColumns={mosaicCustomColumns()}
                    visibility={vis()}
                    onToggle={handleColumnToggle}
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              <For each={sortedMosaics()}>
                {(m) => (
                  <>
                    <tr class="border-b border-theme-border hover:bg-theme-base/30 cursor-pointer" onClick={() => navigate(`/mosaics/${m.id}`)}>
                      {/* Name cell */}
                      <td class="py-2.5 px-3 text-theme-text-primary text-sm">
                        <div class="flex items-center gap-2">
                          <Show when={isAdmin()}>
                            <input
                              type="checkbox"
                              checked={selectedMosaicIds().has(m.id)}
                              onChange={() => toggleMosaicSelection(m.id)}
                              onClick={(e) => e.stopPropagation()}
                              class="accent-[var(--color-accent)] shrink-0"
                            />
                          </Show>
                          <span class="font-medium">{m.name}</span>
                          <Show when={m.needs_review}>
                            <span class="text-xs text-theme-warning border border-theme-warning/30 rounded px-1.5 py-0.5 whitespace-nowrap">
                              Needs Review
                            </span>
                          </Show>
                        </div>
                      </td>
                      {/* Panels cell */}
                      <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "panels")}>
                        <td class="py-2.5 px-3 text-right tabular-nums">{m.panel_count}</td>
                      </Show>
                      {/* Integration cell */}
                      <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "integration")}>
                        <td class="py-2.5 px-3 text-right tabular-nums">{formatIntegration(m.total_integration_seconds)}</td>
                      </Show>
                      {/* Frames cell */}
                      <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "frames")}>
                        <td class="py-2.5 px-3 text-right tabular-nums">{m.total_frames}</td>
                      </Show>
                      {/* Date Range cell */}
                      <Show when={isColumnVisible(vis(), "mosaic_table", "builtin", "date_range")}>
                        <td class="py-2.5 px-3 text-right text-theme-text-secondary text-xs">
                          <Show when={m.first_session} fallback={"—"}>
                            {m.first_session === m.last_session
                              ? m.first_session
                              : `${m.first_session} – ${m.last_session}`}
                          </Show>
                        </td>
                      </Show>
                      {/* Custom column cells */}
                      <For each={mosaicCustomColumns()}>
                        {(col) => (
                          <Show when={isColumnVisible(vis(), "mosaic_table", "custom", col.slug)}>
                            <td class="py-2.5 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                              <InlineEditCell
                                columnType={col.column_type}
                                value={m.custom_values?.[col.slug]}
                                dropdownOptions={col.dropdown_options}
                                onSave={async (val) => {
                                  await apiClient
                                    .PUT("/api/custom-columns/values", {
                                      body: {
                                        column_id: col.id,
                                        mosaic_id: m.id,
                                        value: val,
                                      },
                                    })
                                    .then(unwrap);
                                }}
                              />
                            </td>
                          </Show>
                        )}
                      </For>
                      {/* Actions cell */}
                      <td class="py-2.5 px-3" onClick={(e) => e.stopPropagation()}>
                        <div class="flex items-center justify-end gap-2">
                          <Show when={isAdmin()}>
                            <Show
                              when={confirmDeleteId() === m.id}
                              fallback={
                                <Button
                                  variant="danger"
                                  size="sm"
                                  onClick={() => setConfirmDeleteId(m.id)}
                                  disabled={!!bulkAction()}
                                >
                                  Delete
                                </Button>
                              }
                            >
                              <div class="flex items-center gap-2">
                                <span class="text-xs text-theme-danger">Delete?</span>
                                <Button
                                  variant="danger"
                                  size="sm"
                                  onClick={() => handleDeleteMosaic(m.id)}
                                >
                                  Confirm
                                </Button>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => setConfirmDeleteId(null)}
                                >
                                  Cancel
                                </Button>
                              </div>
                            </Show>
                          </Show>
                          <button
                            onClick={() => toggleExpand(m.id)}
                            class="px-2.5 py-1 border border-theme-border-em rounded text-label text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-accent transition-colors"
                          >
                            {expandedId() === m.id ? "Collapse" : "Expand"}
                          </button>
                        </div>
                      </td>
                    </tr>

                    {/* Expanded detail row */}
                    <Show when={expandedId() === m.id}>
                      <tr>
                        <td colspan={totalColumns()} class="p-0">
                          <div class="p-3 border-b border-theme-border bg-theme-base/20 space-y-3">
                            {/* Rename */}
                            <Show when={isAdmin()}>
                              <Show
                                when={renamingId() === m.id}
                                fallback={
                                  <button
                                    onClick={() => { setRenamingId(m.id); setRenameValue(m.name); }}
                                    class="text-xs text-theme-text-secondary hover:text-theme-text-primary transition-colors"
                                    title="Rename mosaic"
                                  >
                                    Rename
                                  </button>
                                }
                              >
                                <div class="flex gap-2 items-center">
                                  <input
                                    type="text"
                                    value={renameValue()}
                                    onInput={(e) => setRenameValue(e.currentTarget.value)}
                                    onKeyDown={(e) => e.key === "Enter" && handleRename(m.id)}
                                    class="flex-1 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary focus:outline-none focus:border-theme-accent"
                                  />
                                  <Button
                                    variant="primary"
                                    size="sm"
                                    onClick={() => handleRename(m.id)}
                                  >
                                    Save
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => setRenamingId(null)}
                                  >
                                    Cancel
                                  </Button>
                                </div>
                              </Show>
                            </Show>

                            {/* Panel list */}
                            <Show when={details()[m.id]}>
                              {(detail) => (
                                <div class="space-y-2">
                                  <For each={detail().panels}>
                                    {(p) => (
                                      <div class="flex items-center justify-between p-2 bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)]">
                                        <div class="flex-1">
                                          <span class="text-theme-text-primary text-sm">
                                            {p.panel_label}
                                          </span>
                                          <span class="text-theme-text-secondary text-xs ml-2">
                                            {p.target_name}
                                          </span>
                                          <div class="text-xs text-theme-text-secondary mt-0.5">
                                            {formatIntegration(p.total_integration_seconds)}
                                            {" · "}
                                            {p.total_frames} frames
                                          </div>
                                        </div>
                                        <Show when={isAdmin()}>
                                          <Button
                                            variant="danger"
                                            size="sm"
                                            onClick={() => handleRemovePanel(m.id, p.panel_id)}
                                          >
                                            Remove
                                          </Button>
                                        </Show>
                                      </div>
                                    )}
                                  </For>
                                  <Show when={detail().panels.length === 0}>
                                    <p class="text-xs text-theme-text-secondary">
                                      No panels yet. Add targets as panels below.
                                    </p>
                                  </Show>
                                </div>
                              )}
                            </Show>

                            {/* Add panel */}
                            <Show when={isAdmin()}>
                              <Show
                                when={addingPanelFor() === m.id}
                                fallback={
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => {
                                      setAddingPanelFor(m.id);
                                      setPanelSearch("");
                                      setPanelLabel("");
                                      setSelectedTarget(null);
                                      setSearchResults([]);
                                    }}
                                  >
                                    + Add Panel
                                  </Button>
                                }
                              >
                                <div class="p-2 bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)] space-y-2">
                                  <div class="relative">
                                    <input
                                      type="text"
                                      value={panelSearch()}
                                      onInput={(e) => handlePanelSearch(e.currentTarget.value)}
                                      placeholder="Search targets..."
                                      class="w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent"
                                    />
                                    <Show when={searchResults().length > 0}>
                                      <div class="absolute z-10 w-full mt-1 bg-theme-surface border border-theme-border rounded-[var(--radius-sm)] shadow-[var(--shadow-sm)] max-h-40 overflow-y-auto">
                                        <For each={searchResults()}>
                                          {(t) => (
                                            <button
                                              onClick={() => selectTarget(t)}
                                              class="w-full text-left px-2 py-1.5 text-sm text-theme-text-primary hover:bg-theme-base/50 transition-colors"
                                            >
                                              {t.primary_name}
                                            </button>
                                          )}
                                        </For>
                                      </div>
                                    </Show>
                                  </div>
                                  <input
                                    type="text"
                                    value={panelLabel()}
                                    onInput={(e) => setPanelLabel(e.currentTarget.value)}
                                    placeholder="Panel label (e.g., Panel 1)..."
                                    class="w-full px-2 py-1.5 text-sm bg-theme-base border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary placeholder:text-theme-text-secondary/50 focus:outline-none focus:border-theme-accent"
                                  />
                                  <div class="flex gap-2">
                                    <Button
                                      variant="primary"
                                      size="sm"
                                      onClick={() => handleAddPanel(m.id)}
                                    >
                                      Add
                                    </Button>
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      onClick={() => setAddingPanelFor(null)}
                                    >
                                      Cancel
                                    </Button>
                                  </div>
                                </div>
                              </Show>
                            </Show>

                          </div>
                        </td>
                      </tr>
                    </Show>
                  </>
                )}
              </For>
            </tbody>
          </table>
        </Show>
        </Show>
      </div>
    </div>
  );
};
