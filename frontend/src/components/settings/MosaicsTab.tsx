import { Component, For, Show, createSignal, onMount } from "solid-js";
import { api } from "../../api/client";
import { showToast } from "../Toast";
import { useAuth } from "../AuthProvider";
import { useSettingsContext } from "../SettingsProvider";
import type {
  MosaicSummary,
  MosaicDetailResponse,
  MosaicSuggestionResponse,
  TargetSearchResultFuzzy,
} from "../../types";

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return h < 1 ? `${Math.round(h * 60)}m` : `${h.toFixed(1)}h`;
}

export const MosaicsTab: Component = () => {
  const { isAdmin } = useAuth();
  const settingsCtx = useSettingsContext();

  // Keywords state
  const [newKeyword, setNewKeyword] = createSignal("");

  // Suggestions state
  const [suggestions, setSuggestions] = createSignal<MosaicSuggestionResponse[]>([]);
  const [detecting, setDetecting] = createSignal(false);

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

  // Create mosaic state
  const [showCreate, setShowCreate] = createSignal(false);
  const [newMosaicName, setNewMosaicName] = createSignal("");

  // Delete confirmation
  const [confirmDeleteId, setConfirmDeleteId] = createSignal<string | null>(null);

  const keywords = () => settingsCtx.settings()?.general?.mosaic_keywords ?? ["Panel", "P"];

  const refresh = async () => {
    try {
      const [s, m] = await Promise.all([
        api.getMosaicSuggestions(),
        api.getMosaics(),
      ]);
      setSuggestions(s);
      setMosaics(m);
    } catch {
      // Non-blocking
    }
  };

  onMount(refresh);

  // Keywords
  const addKeyword = async () => {
    const kw = newKeyword().trim();
    if (!kw || keywords().includes(kw)) return;
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
      showToast(`Detection complete — ${result.new_suggestions} new suggestion(s) found`);
      await refresh();
    } catch {
      showToast("Failed to run detection", "error");
    } finally {
      setDetecting(false);
    }
  };

  // Suggestions
  const handleAccept = async (s: MosaicSuggestionResponse) => {
    try {
      await api.acceptMosaicSuggestion(s.id);
      showToast(`Created mosaic "${s.suggested_name}"`);
      await refresh();
    } catch {
      showToast("Failed to accept suggestion", "error");
    }
  };

  const handleDismiss = async (s: MosaicSuggestionResponse) => {
    try {
      await api.dismissMosaicSuggestion(s.id);
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    } catch {
      showToast("Failed to dismiss suggestion", "error");
    }
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
    <div class="space-y-4">
      {/* Detection Keywords */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <h3 class="text-theme-text-primary font-medium">Detection Keywords</h3>
          <Show when={isAdmin()}>
            <button
              onClick={handleDetect}
              disabled={detecting()}
              class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-sm disabled:opacity-50 hover:text-theme-text-primary hover:border-theme-accent transition-colors"
            >
              {detecting() ? "Detecting..." : "Run Detection"}
            </button>
          </Show>
        </div>
        <p class="text-xs text-theme-text-secondary">
          Keywords used to identify mosaic panels in target names (e.g., "M31 Panel 1", "NGC7000 P2").
        </p>
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
              class="px-3 py-1.5 text-sm bg-theme-accent text-white rounded-[var(--radius-sm)] hover:opacity-90"
            >
              Add
            </button>
          </div>
        </Show>
      </div>

      {/* Auto-detected Suggestions */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <h3 class="text-theme-text-primary font-medium">
          Suggestions ({suggestions().length})
        </h3>
        <Show
          when={suggestions().length > 0}
          fallback={
            <p class="text-sm text-theme-text-secondary">
              No pending suggestions. Run detection to scan for mosaic panels.
            </p>
          }
        >
          <div class="space-y-2">
            <For each={suggestions()}>
              {(s) => (
                <div class="flex items-center justify-between p-3 bg-theme-base/50 border border-theme-border rounded-[var(--radius-sm)]">
                  <div class="flex-1">
                    <span class="text-theme-text-primary text-sm font-medium">
                      {s.suggested_name}
                    </span>
                    <div class="text-xs text-theme-text-secondary mt-0.5">
                      {s.target_ids.length} panels: {s.panel_labels.join(", ")}
                    </div>
                  </div>
                  <Show when={isAdmin()}>
                    <div class="flex gap-2">
                      <button
                        onClick={() => handleAccept(s)}
                        class="px-2 py-1 text-xs bg-theme-success text-theme-text-primary rounded hover:opacity-90"
                      >
                        Accept
                      </button>
                      <button
                        onClick={() => handleDismiss(s)}
                        class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                      >
                        Dismiss
                      </button>
                    </div>
                  </Show>
                </div>
              )}
            </For>
          </div>
        </Show>
      </div>

      {/* Existing Mosaics */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-3">
        <div class="flex justify-between items-center">
          <h3 class="text-theme-text-primary font-medium">
            Mosaics ({mosaics().length})
          </h3>
          <Show when={isAdmin()}>
            <button
              onClick={() => setShowCreate(!showCreate())}
              class="px-3 py-1.5 text-sm border border-theme-border text-theme-text-secondary rounded-[var(--radius-sm)] hover:text-theme-text-primary hover:border-theme-accent transition-colors"
            >
              {showCreate() ? "Cancel" : "Create Mosaic"}
            </button>
          </Show>
        </div>

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
              class="px-3 py-1.5 text-sm bg-theme-accent text-white rounded-[var(--radius-sm)] hover:opacity-90"
            >
              Create
            </button>
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
                <div class="border border-theme-border rounded-[var(--radius-sm)] overflow-hidden">
                  {/* Collapsed header */}
                  <button
                    onClick={() => toggleExpand(m.id)}
                    class="w-full flex items-center justify-between p-3 bg-theme-base/50 text-left hover:bg-theme-base/80 transition-colors"
                  >
                    <div class="flex-1">
                      <span class="text-theme-text-primary text-sm font-medium">
                        {m.name}
                      </span>
                      <div class="text-xs text-theme-text-secondary mt-0.5">
                        {m.panel_count} panels
                        {" \u00b7 "}
                        {formatHours(m.total_integration_seconds)} integration
                        {" \u00b7 "}
                        {m.total_frames} frames
                      </div>
                    </div>
                    <span class="text-theme-text-secondary text-xs">
                      {expandedId() === m.id ? "\u25B2" : "\u25BC"}
                    </span>
                  </button>

                  {/* Expanded detail */}
                  <Show when={expandedId() === m.id}>
                    <div class="p-3 border-t border-theme-border space-y-3">
                      {/* Panel list */}
                      <Show when={details()[m.id]}>
                        {(detail) => (
                          <div class="space-y-2">
                            <For each={detail().panels}>
                              {(p) => (
                                <div class="flex items-center justify-between p-2 bg-theme-base/30 border border-theme-border/50 rounded-[var(--radius-sm)]">
                                  <div class="flex-1">
                                    <span class="text-theme-text-primary text-sm">
                                      {p.panel_label}
                                    </span>
                                    <span class="text-theme-text-secondary text-xs ml-2">
                                      {p.target_name}
                                    </span>
                                    <div class="text-xs text-theme-text-secondary mt-0.5">
                                      {formatHours(p.total_integration_seconds)}
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
                          <div class="p-2 bg-theme-base/30 border border-theme-border/50 rounded-[var(--radius-sm)] space-y-2">
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
                                class="px-2 py-1 text-xs bg-theme-accent text-white rounded hover:opacity-90"
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

                      {/* Footer actions */}
                      <div class="flex items-center justify-between pt-2 border-t border-theme-border/50">
                        <a
                          href={`/mosaics/${m.id}`}
                          class="text-xs text-theme-accent hover:underline"
                        >
                          View mosaic detail
                        </a>
                        <Show when={isAdmin()}>
                          <Show
                            when={confirmDeleteId() === m.id}
                            fallback={
                              <button
                                onClick={() => setConfirmDeleteId(m.id)}
                                class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-danger hover:border-theme-danger transition-colors"
                              >
                                Delete
                              </button>
                            }
                          >
                            <div class="flex items-center gap-2">
                              <span class="text-xs text-theme-danger">Delete this mosaic?</span>
                              <button
                                onClick={() => handleDeleteMosaic(m.id)}
                                class="px-2 py-1 text-xs bg-theme-danger text-white rounded hover:opacity-90"
                              >
                                Confirm
                              </button>
                              <button
                                onClick={() => setConfirmDeleteId(null)}
                                class="px-2 py-1 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary transition-colors"
                              >
                                Cancel
                              </button>
                            </div>
                          </Show>
                        </Show>
                      </div>
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
