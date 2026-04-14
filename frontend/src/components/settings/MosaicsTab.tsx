import { Component, For, Show, createSignal, onMount } from "solid-js";
import { api } from "../../api/client";
import { showToast, dismissToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { useSettingsContext } from "../SettingsProvider";
import HelpPopover from "../HelpPopover";
import type {
  MosaicSummary,
  MosaicDetailResponse,
  MosaicSuggestionResponse,
  TargetSearchResultFuzzy,
} from "../../types";

// Module-level cache so data persists across navigations
let cachedSuggestions: MosaicSuggestionResponse[] | null = null;
let cachedMosaics: MosaicSummary[] | null = null;

import { formatIntegration } from "../../utils/format";

export const MosaicsTab: Component = () => {
  const { isAdmin } = useAuth();
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

  const keywords = () => settingsCtx.settings()?.general?.mosaic_keywords ?? ["Panel", "P"];

  const GAP_OPTIONS = [
    { label: "No grouping", value: 0 },
    { label: "1 month", value: 30 },
    { label: "3 months", value: 90 },
    { label: "6 months", value: 180 },
    { label: "1 year", value: 365 },
  ];

  const campaignGap = () =>
    settingsCtx.settings()?.general?.mosaic_campaign_gap_days ?? 0;

  const refresh = async (silent = false) => {
    if (!silent) showToast("Loading mosaics...", "info", 15000);
    try {
      const [s, m] = await Promise.all([
        api.getMosaicSuggestions(),
        api.getMosaics(),
      ]);
      cachedSuggestions = s;
      cachedMosaics = m;
      setSuggestions(s);
      setMosaics(m);
      if (!silent) dismissToast();
    } catch {
      if (!silent) dismissToast();
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
    setDetecting(true);
    try {
      const result = await api.triggerMosaicDetection();
      showToast(`Detection complete - ${result.new_suggestions} new suggestion(s) found`);
      await refresh();
    } catch {
      showToast("Failed to run detection", "error");
    } finally {
      setDetecting(false);
    }
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
      await api.acceptMosaicSuggestion(s.id, selected);
      showToast(`Created mosaic "${s.suggested_name}"`);
      setExpandedSuggestion(null);
      // Update both lists before allowing next accept
      const [newSuggestions, newMosaics] = await Promise.all([
        api.getMosaicSuggestions(),
        api.getMosaics(),
      ]);
      setSuggestions(newSuggestions);
      setMosaics(newMosaics);
    } catch {
      showToast("Failed to accept suggestion", "error");
    } finally {
      setAcceptingId(null);
    }
  };

  const handleDismiss = async (s: MosaicSuggestionResponse) => {
    try {
      await api.dismissMosaicSuggestion(s.id);
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
    for (const s of items) {
      try {
        const panelSel = selectedPanels()[s.id];
        const selected = panelSel && panelSel.size < s.panel_labels.length ? [...panelSel] : undefined;
        await api.acceptMosaicSuggestion(s.id, selected);
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
    try {
      const [newSuggestions, newMosaics] = await Promise.all([
        api.getMosaicSuggestions(),
        api.getMosaics(),
      ]);
      setSuggestions(newSuggestions);
      setMosaics(newMosaics);
    } catch {}
    setBulkAction(null);
    showToast(`Accepted ${succeeded} of ${items.length} suggestion(s)`);
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
        await api.dismissMosaicSuggestion(s.id);
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
        await api.deleteMosaic(id);
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
      const newSuggestions = await api.getMosaicSuggestions();
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
        const detail = await api.getMosaicDetail(id);
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
      const results = await api.searchTargets(query);
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
      await api.addMosaicPanel(mosaicId, target.id, label);
      showToast(`Added panel "${label}"`);
      setPanelSearch("");
      setPanelLabel("");
      setSelectedTarget(null);
      setAddingPanelFor(null);
      // Refresh detail
      const detail = await api.getMosaicDetail(mosaicId);
      setDetails((prev) => ({ ...prev, [mosaicId]: detail }));
      // Refresh summary
      const allMosaics = await api.getMosaics();
      setMosaics(allMosaics);
    } catch {
      showToast("Failed to add panel", "error");
    }
  };

  const handleRemovePanel = async (mosaicId: string, panelId: string) => {
    try {
      await api.removeMosaicPanel(mosaicId, panelId);
      showToast("Panel removed");
      const detail = await api.getMosaicDetail(mosaicId);
      setDetails((prev) => ({ ...prev, [mosaicId]: detail }));
      const allMosaics = await api.getMosaics();
      setMosaics(allMosaics);
    } catch {
      showToast("Failed to remove panel", "error");
    }
  };

  const handleDeleteMosaic = async (id: string) => {
    try {
      await api.deleteMosaic(id);
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
      await api.updateMosaic(id, { name });
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
      await api.createMosaic(name);
      showToast(`Created mosaic "${name}"`);
      setNewMosaicName("");
      setShowCreate(false);
      await refresh();
    } catch {
      showToast("Failed to create mosaic", "error");
    }
  };

  return (
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
      {/* Left column: Detection + Suggestions */}
      <div class="space-y-4">

      {/* Detection Keywords */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-2">
            <h3 class="text-theme-text-primary font-medium">Detection Keywords</h3>
            <HelpPopover title="Detection Keywords">
              <p>Token strings used to detect mosaic panels inside target names. When a target name contains a keyword followed by a number, the target is treated as a panel candidate.</p>
              <p>Example: with keywords "Panel" and "P", the names "M31 Panel 1", "M31 Panel 2", and "NGC 7000 P2" are all recognized as panels of the same mosaic.</p>
              <p>Run Detection re-scans targets after keyword changes to rebuild the suggestion list.</p>
            </HelpPopover>
          </div>
          <Show when={isAdmin()}>
            <button
              onClick={handleDetect}
              disabled={detecting()}
              class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
            >
              {detecting() ? "Detecting..." : "Run Detection"}
            </button>
          </Show>
        </div>
        <div class="flex flex-wrap gap-2">
          <For each={keywords()}>
            {(kw) => (
              <span class="inline-flex items-center gap-1 px-2 py-1 text-sm bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)] text-theme-text-primary">
                {kw}
                <Show when={isAdmin()}>
                  <button
                    onClick={() => removeKeyword(kw)}
                    class="text-theme-text-secondary hover:text-theme-danger ml-1 text-xs"
                    title="Remove"
                  >
                    &times;
                  </button>
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
            <button
              onClick={addKeyword}
              class="px-3 py-1.5 text-sm border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
            >
              Add
            </button>
          </div>
        </Show>
      </div>

      {/* Auto-detected Suggestions */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-2">
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
                <button
                  onClick={handleBulkAccept}
                  class="px-3 py-1.5 text-xs bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded-[var(--radius-sm)] font-medium hover:bg-theme-accent/25 transition-colors"
                >
                  Accept {selectedSuggestionCount() > 0 ? `(${selectedSuggestionCount()})` : `All (${filteredSuggestions().length})`}
                </button>
                <button
                  onClick={handleBulkDismiss}
                  class="px-3 py-1.5 text-xs border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-danger hover:border-theme-danger transition-colors"
                >
                  Dismiss {selectedSuggestionCount() > 0 ? `(${selectedSuggestionCount()})` : `All (${filteredSuggestions().length})`}
                </button>
              </div>
            </div>
          </Show>
          <div class="space-y-2">
            <For each={filteredSuggestions()}>
              {(s) => {
                const uniqueTargets = () => [...new Set(s.target_ids)];
                const totalFrames = () => s.sessions.reduce((a, r) => a + r.frames, 0);
                const totalInt = () => s.sessions.reduce((a, r) => a + r.integration_seconds, 0);

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
                  sortKey() === key ? (sortAsc() ? " \u25B4" : " \u25BE") : "";

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
                          <span class="text-theme-text-primary text-sm font-medium">
                            {s.suggested_name}
                          </span>
                          <div class="text-xs text-theme-text-secondary mt-0.5">
                            {s.panel_labels.length} panels
                            {" \u00b7 "}
                            <span classList={{ "text-theme-warning": totalFrames() === 0 }}>
                              {totalFrames()} frames
                            </span>
                            {" \u00b7 "}
                            {formatIntegration(totalInt())}
                          </div>
                        </div>
                        <span class="text-theme-text-secondary text-xs ml-2">
                          {expandedSuggestion() === s.id ? "\u25B2" : "\u25BC"}
                        </span>
                      </button>
                      <Show when={isAdmin()}>
                        <div class="flex gap-2 ml-3 shrink-0">
                          <button
                            onClick={(e) => { e.stopPropagation(); handleAccept(s); }}
                            disabled={!!acceptingId() || !!bulkAction()}
                            class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {acceptingId() === s.id ? "Accepting..." : "Accept"}{(() => {
                              const sel = selectedPanels()[s.id];
                              const count = sel?.size ?? s.panel_labels.length;
                              return count < s.panel_labels.length ? ` (${count}/${s.panel_labels.length})` : "";
                            })()}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDismiss(s); }}
                            disabled={!!bulkAction()}
                            class="px-2.5 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            Dismiss
                          </button>
                        </div>
                      </Show>
                    </div>

                    <Show when={expandedSuggestion() === s.id}>
                      <div class="border-t border-theme-border">
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
                                    <td class="px-3 py-1.5 text-theme-text-secondary">{sess.filter_used || "\u2014"}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary text-right">{sess.frames}</td>
                                    <td class="px-3 py-1.5 text-theme-text-secondary text-right">{formatIntegration(sess.integration_seconds)}</td>
                                  </tr>
                                )}
                              </For>
                            </tbody>
                          </table>
                        </Show>

                      </div>
                    </Show>
                  </div>
                );
              }}
            </For>
          </div>
        </Show>
      </div>

      </div>{/* end left column */}

      {/* Right column: Existing Mosaics */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <div class="flex items-center gap-2">
            <h3 class="text-theme-text-primary font-medium">
              Mosaics ({mosaics().length})
            </h3>
            <HelpPopover title="Mosaics" align="right">
              <p>Existing mosaic projects. Each mosaic collects one or more target panels and tracks their integration, per-filter breakdown, and layout.</p>
              <p>Create a mosaic manually with the Create Mosaic button, or accept a detection suggestion from the left column. Select one or more rows to enable bulk delete.</p>
              <p>Example: "M31 Mosaic 2x3" holds six target panels; opening the mosaic detail page shows the composite image and per-panel progress.</p>
            </HelpPopover>
          </div>
          <Show when={isAdmin()}>
            <div class="flex gap-2">
              <Show when={selectedMosaicIds().size > 0 && !bulkAction()}>
                <button
                  onClick={handleBulkDeleteMosaics}
                  class="px-3 py-1.5 text-sm border border-theme-danger/50 text-theme-danger rounded-[var(--radius-sm)] hover:bg-theme-danger/10 transition-colors"
                >
                  Delete Selected ({selectedMosaicIds().size})
                </button>
              </Show>
              <button
                onClick={() => setShowCreate(!showCreate())}
                class="px-3 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors"
              >
                {showCreate() ? "Cancel" : "Create Mosaic"}
              </button>
            </div>
          </Show>
        </div>

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
            <button
              onClick={handleCreate}
              class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors"
            >
              Create
            </button>
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
            <p class="text-sm text-theme-text-secondary">No mosaics yet.</p>
          }
        >
          <div class="space-y-2">
            <For each={mosaics()}>
              {(m) => (
                <div class="bg-theme-elevated border border-theme-border-em rounded-[var(--radius-sm)] overflow-hidden">
                  {/* Collapsed header */}
                  <div class="flex items-center p-3">
                    <Show when={isAdmin()}>
                      <input
                        type="checkbox"
                        checked={selectedMosaicIds().has(m.id)}
                        onChange={() => toggleMosaicSelection(m.id)}
                        class="accent-[var(--color-accent)] mr-2 shrink-0"
                      />
                    </Show>
                    <button
                      onClick={() => toggleExpand(m.id)}
                      class="flex-1 flex items-center justify-between text-left hover:bg-theme-base/80 transition-colors"
                    >
                      <div class="flex-1">
                        <span class="text-theme-text-primary text-sm font-medium">
                          {m.name}
                        </span>
                        <div class="text-xs text-theme-text-secondary mt-0.5">
                          {m.panel_count} panels
                          {" \u00b7 "}
                          {formatIntegration(m.total_integration_seconds)} integration
                          {" \u00b7 "}
                          {m.total_frames} frames
                        </div>
                      </div>
                      <span class="text-theme-text-secondary text-xs">
                        {expandedId() === m.id ? "\u25B2" : "\u25BC"}
                      </span>
                    </button>
                    <div class="flex items-center gap-2 ml-3 shrink-0">
                      <Show when={isAdmin()}>
                        <Show
                          when={confirmDeleteId() === m.id}
                          fallback={
                            <button
                              onClick={() => setConfirmDeleteId(m.id)}
                              disabled={!!bulkAction()}
                              class="px-2 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded hover:text-theme-danger hover:border-theme-danger transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              Delete
                            </button>
                          }
                        >
                          <div class="flex items-center gap-2">
                            <span class="text-xs text-theme-danger">Delete?</span>
                            <button
                              onClick={() => handleDeleteMosaic(m.id)}
                              class="px-2 py-1.5 text-sm border border-theme-error/50 text-theme-error rounded-[var(--radius-sm)] hover:bg-theme-error/10 transition-colors"
                            >
                              Confirm
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              class="px-2 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                            >
                              Cancel
                            </button>
                          </div>
                        </Show>
                      </Show>
                      <a
                        href={`/mosaics/${m.id}`}
                        class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors"
                      >
                        Detail
                      </a>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  <Show when={expandedId() === m.id}>
                    <div class="p-3 border-t border-theme-border space-y-3">
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
                            <button
                              onClick={() => handleRename(m.id)}
                              class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setRenamingId(null)}
                              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                            >
                              Cancel
                            </button>
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
                                      {" \u00b7 "}
                                      {p.total_frames} frames
                                    </div>
                                  </div>
                                  <Show when={isAdmin()}>
                                    <button
                                      onClick={() => handleRemovePanel(m.id, p.panel_id)}
                                      class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-danger hover:border-theme-danger transition-colors"
                                    >
                                      Remove
                                    </button>
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
                            <button
                              onClick={() => {
                                setAddingPanelFor(m.id);
                                setPanelSearch("");
                                setPanelLabel("");
                                setSelectedTarget(null);
                                setSearchResults([]);
                              }}
                              class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                            >
                              + Add Panel
                            </button>
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
                              <button
                                onClick={() => handleAddPanel(m.id)}
                                class="px-2 py-1 text-xs border border-theme-accent/50 text-theme-accent rounded-[var(--radius-sm)] hover:bg-theme-accent/10 transition-colors"
                              >
                                Add
                              </button>
                              <button
                                onClick={() => setAddingPanelFor(null)}
                                class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        </Show>
                      </Show>

                    </div>
                  </Show>
                </div>
              )}
            </For>
          </div>
        </Show>
      </div>
    </div>
  );
};
