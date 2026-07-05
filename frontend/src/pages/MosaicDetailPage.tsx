import { Component, Show, For, createResource, createSignal, createMemo, createEffect, onMount, onCleanup } from "solid-js";
import { A, useParams, useNavigate } from "@solidjs/router";
import { api } from "../api/client";
import type { PanelStats } from "../types";
import { formatIntegration, contentWidthClass } from "../utils/format";
import { useSettingsContext } from "../components/SettingsProvider";
import HelpPopover from "../components/HelpPopover";
import { showToast } from "../components/Toast";
import InlineEditCell from "../components/InlineEditCell";
import { isColumnVisible } from "../utils/displaySettings";
import KonvaMosaicArranger from "../components/mosaics/KonvaMosaicArranger";
import MosaicCompositeModal from "../components/mosaics/MosaicCompositeModal";
import ConfirmDialog from "../components/ConfirmDialog";
import { getErrorMessage } from "../utils/errors";
import { useNotesAutosave } from "../lib/useNotesAutosave";

const MosaicDetailPage: Component = () => {
  const ctx = useSettingsContext();
  const params = useParams<{ mosaicId: string }>();
  const navigate = useNavigate();
  const [mosaic, { refetch }] = createResource(() => params.mosaicId, (id) => api.getMosaicDetail(id));

  // Title-row actions: composite, rename, delete, export.
  const [showComposite, setShowComposite] = createSignal(false);
  const [editingName, setEditingName] = createSignal(false);
  const [editName, setEditName] = createSignal("");
  const [savingName, setSavingName] = createSignal(false);
  const [actionsMenuOpen, setActionsMenuOpen] = createSignal(false);
  const [deleteConfirm, setDeleteConfirm] = createSignal(false);
  let actionsMenuRef: HTMLDivElement | undefined;
  const onActionsMenuDocClick = (e: MouseEvent) => {
    if (!actionsMenuRef) return;
    if (!actionsMenuRef.contains(e.target as Node)) setActionsMenuOpen(false);
  };
  const onActionsMenuKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") setActionsMenuOpen(false);
  };
  onMount(() => {
    document.addEventListener("click", onActionsMenuDocClick);
    document.addEventListener("keydown", onActionsMenuKey);
  });
  onCleanup(() => {
    document.removeEventListener("click", onActionsMenuDocClick);
    document.removeEventListener("keydown", onActionsMenuKey);
  });

  const handleRename = async () => {
    const data = mosaic();
    if (!data) return;
    const name = editName().trim();
    if (!name) {
      showToast("Name cannot be empty", "error");
      return;
    }
    if (name === data.name) {
      setEditingName(false);
      return;
    }
    setSavingName(true);
    try {
      await api.updateMosaic(params.mosaicId, { name });
      setEditingName(false);
      await refetch();
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Rename failed"), "error", 5000);
    } finally {
      setSavingName(false);
    }
  };

  const handleDelete = async () => {
    const data = mosaic();
    setDeleteConfirm(false);
    if (!data) return;
    try {
      await api.deleteMosaic(params.mosaicId);
      showToast(`Deleted mosaic "${data.name}"`);
      navigate("/mosaics");
    } catch (e: unknown) {
      showToast(getErrorMessage(e, "Failed to delete mosaic"), "error", 5000);
    }
  };

  // Client-side CSV of the mosaic's panels built from already-loaded detail
  // data. No backend round-trip needed.
  const handleExportCsv = () => {
    const data = mosaic();
    if (!data) return;
    const esc = (v: string | number) => {
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const headers = ["panel_label", "target_name", "frames", "integration_seconds", "filters"];
    const lines = [headers.join(",")];
    const panels = [...data.panels].sort((a, b) => a.sort_order - b.sort_order);
    for (const p of panels) {
      const filters = Object.entries(p.filter_distribution)
        .map(([f, n]) => `${f}: ${n}`)
        .join("; ");
      lines.push([
        esc(p.panel_label),
        esc(p.target_name),
        esc(p.total_frames),
        esc(Math.round(p.total_integration_seconds)),
        esc(filters),
      ].join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.name.replace(/[^a-zA-Z0-9]/g, "_")}_panels.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  type SortKey = "panel" | "target" | "integration" | "frames" | "session";
  type SortDir = "asc" | "desc";
  // Panel sort persisted to localStorage (Dashboard pattern).
  const PANEL_SORT_LS = "mosaic_panel_sort";
  let initialPanelSort: { key: SortKey; dir: SortDir } = { key: "panel", dir: "asc" };
  try {
    const stored = localStorage.getItem(PANEL_SORT_LS);
    if (stored) initialPanelSort = JSON.parse(stored);
  } catch { /* ignore corrupt localStorage */ }
  const [sortKey, setSortKey] = createSignal<SortKey>(initialPanelSort.key);
  const [sortDir, setSortDir] = createSignal<SortDir>(initialPanelSort.dir);
  const persistPanelSort = (key: SortKey, dir: SortDir) => {
    try { localStorage.setItem(PANEL_SORT_LS, JSON.stringify({ key, dir })); } catch { /* ignore */ }
  };
  const [includingAll, setIncludingAll] = createSignal(false);
  const [selectedFilter, setSelectedFilter] = createSignal<string | null>(null);
  const [filterLoading, setFilterLoading] = createSignal(false);
  const [thumbnailOverrides, setThumbnailOverrides] = createSignal<Record<string, string | null> | null>(null);

  // Initialize selected filter from API response and fetch filter-specific thumbnails
  createEffect(() => {
    const data = mosaic();
    if (data && data.default_filter && selectedFilter() === null) {
      handleFilterChange(data.default_filter);
    }
  });

  const toggleSort = (key: SortKey) => {
    if (sortKey() === key) {
      const dir = sortDir() === "asc" ? "desc" : "asc";
      setSortDir(dir);
      persistPanelSort(key, dir);
    } else {
      setSortKey(key);
      setSortDir("asc");
      persistPanelSort(key, "asc");
    }
  };

  const sortedPanels = createMemo(() => {
    const m = mosaic();
    if (!m) return [];
    const panels = [...m.panels];
    const dir = sortDir() === "asc" ? 1 : -1;
    const key = sortKey();
    return panels.sort((a, b) => {
      switch (key) {
        case "panel": {
          const na = parseInt(a.panel_label.replace(/\D/g, "")) || a.sort_order;
          const nb = parseInt(b.panel_label.replace(/\D/g, "")) || b.sort_order;
          return (na - nb) * dir;
        }
        case "target": return a.target_name.localeCompare(b.target_name) * dir;
        case "integration": return (a.total_integration_seconds - b.total_integration_seconds) * dir;
        case "frames": return (a.total_frames - b.total_frames) * dir;
        case "session": return ((a.last_session_date || "").localeCompare(b.last_session_date || "")) * dir;
        default: return 0;
      }
    });
  });

  const sortIndicator = (key: SortKey) => sortKey() === key ? (sortDir() === "asc" ? " \u25B2" : " \u25BC") : "";

  const mosaicCustomColumns = () =>
    (ctx.customColumns() ?? []).filter(c => c.applies_to === "mosaic");

  const { notes, onInput: onNotesInput, saving: notesSaving } = useNotesAutosave({
    serverValue: () => mosaic()?.notes,
    save: async (text) => { await api.updateMosaic(params.mosaicId, { notes: text || undefined }); },
    errorLabel: "Failed to save notes",
  });

  // State for the delete-panel confirmation dialog.
  const [deletePanelConfirm, setDeletePanelConfirm] = createSignal<{
    panelId: string;
    panelLabel: string;
  } | null>(null);

  const handleFilterChange = async (filter: string) => {
    setSelectedFilter(filter);
    setFilterLoading(true);
    try {
      const thumbnails = await api.getMosaicPanelThumbnails(params.mosaicId, filter);
      const overrides: Record<string, string | null> = {};
      for (const t of thumbnails) {
        overrides[t.panel_id] = t.thumbnail_url;
      }
      setThumbnailOverrides(overrides);
    } catch (e) {
      showToast("Failed to load filter previews", "error", 5000);
    } finally {
      setFilterLoading(false);
    }
  };

  return (
    <div class={`page-enter min-h-[calc(100vh-57px)] bg-theme-base ${contentWidthClass(ctx.contentWidth())}`}>
      {/* Back nav */}
      <div class="px-4 py-3 border-b border-theme-border">
        <A href="/mosaics" class="text-theme-text-secondary hover:text-theme-text-primary text-sm transition-colors">
          ← Back to Mosaics
        </A>
      </div>

      <div class="p-4 space-y-4">

      <Show when={mosaic()} fallback={<div class="text-center text-theme-text-secondary py-8">Loading...</div>}>
        {(data) => (
          <div class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border p-4 space-y-6">
            {/* Header */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-start justify-between gap-3">
                <div class="flex items-center gap-2 min-w-0">
                  <Show
                    when={editingName()}
                    fallback={
                      <>
                        <h2 class="text-sm font-semibold text-theme-text-primary truncate">{data().name}</h2>
                        <button
                          class="text-theme-text-tertiary hover:text-theme-text-primary transition-colors text-base leading-none"
                          title="Rename mosaic"
                          aria-label="Rename mosaic"
                          disabled={savingName()}
                          onClick={() => {
                            setEditName(data().name);
                            setEditingName(true);
                          }}
                        >
                          &#9998;
                        </button>
                        <Show when={savingName()}>
                          <span class="text-xs text-theme-text-secondary">Saving...</span>
                        </Show>
                      </>
                    }
                  >
                    <input
                      type="text"
                      class="text-sm font-semibold bg-transparent border-b border-theme-accent text-theme-text-primary focus:outline-none min-w-0 flex-1"
                      value={editName()}
                      onInput={(e) => setEditName(e.currentTarget.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRename();
                        if (e.key === "Escape") setEditingName(false);
                      }}
                      ref={(el) => { setTimeout(() => el?.focus(), 0); }}
                      disabled={savingName()}
                    />
                    <button
                      class="text-theme-text-tertiary hover:text-green-400 transition-colors text-base leading-none"
                      title="Save"
                      aria-label="Save name"
                      onClick={handleRename}
                      disabled={savingName()}
                    >
                      &#10003;
                    </button>
                    <button
                      class="text-theme-text-tertiary hover:text-theme-danger transition-colors text-base leading-none"
                      title="Cancel"
                      aria-label="Cancel rename"
                      onClick={() => setEditingName(false)}
                      disabled={savingName()}
                    >
                      &#10005;
                    </button>
                  </Show>
                  <HelpPopover>
                    <p class="text-sm text-theme-text-secondary">
                      The Mosaic Detail page shows all panels belonging to this mosaic project along with their individual and combined statistics.
                    </p>
                    <ul class="list-disc list-inside space-y-1 text-sm text-theme-text-secondary">
                      <li>The <strong class="text-theme-text-primary">panel table</strong> lists each panel's target, integration time, frame count, and last session date. Click column headers to sort.</li>
                      <li>Click a panel's target name to navigate to its full Target Detail page.</li>
                      <li>Use <strong class="text-theme-text-primary">Composite</strong> to generate the combined mosaic image for the selected filter.</li>
                      <li>Use <strong class="text-theme-text-primary">Notes</strong> to record project-level information like imaging goals, completion status, or processing notes.</li>
                    </ul>
                  </HelpPopover>
                </div>
                <div class="flex items-center gap-4 shrink-0">
                  <For each={mosaicCustomColumns()}>
                    {(col) => (
                      <Show when={isColumnVisible(ctx.columnVisibility(), "mosaic_table", "custom", col.slug)}>
                        <div class="flex items-center gap-1.5 text-sm">
                          <span class="text-theme-text-tertiary text-xs">{col.name}:</span>
                          <InlineEditCell
                            columnType={col.column_type}
                            value={data().custom_values?.[col.slug]}
                            dropdownOptions={col.dropdown_options}
                            onSave={(val) =>
                              api.setCustomValue({
                                column_id: col.id,
                                mosaic_id: params.mosaicId,
                                value: val,
                              })
                            }
                          />
                        </div>
                      </Show>
                    )}
                  </For>
                  <div class="flex items-center gap-2">
                    <button
                      class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors"
                      onClick={() => setShowComposite(true)}
                    >
                      Composite
                    </button>
                    <div ref={actionsMenuRef} class="relative inline-flex">
                      <button
                        type="button"
                        aria-label="More actions"
                        aria-haspopup="menu"
                        aria-expanded={actionsMenuOpen()}
                        onClick={(e) => {
                          e.stopPropagation();
                          setActionsMenuOpen((v) => !v);
                        }}
                        class="inline-flex items-center justify-center w-8 h-8 rounded border border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer"
                      >
                        <span class="text-lg leading-none" aria-hidden="true">&#8943;</span>
                      </button>
                      <Show when={actionsMenuOpen()}>
                        <div
                          role="menu"
                          onClick={(e) => e.stopPropagation()}
                          class="absolute top-full right-0 mt-2 z-50 min-w-[12rem] bg-theme-elevated border border-theme-border rounded-[var(--radius-sm)] shadow-[var(--shadow-lg)] py-1"
                        >
                          <button
                            type="button"
                            role="menuitem"
                            class="w-full text-left px-3 py-1.5 text-sm text-theme-text-primary hover:bg-theme-hover transition-colors cursor-pointer"
                            onClick={() => {
                              setActionsMenuOpen(false);
                              handleExportCsv();
                            }}
                          >
                            Export panels (CSV)
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            class="w-full text-left px-3 py-1.5 text-sm text-theme-danger hover:bg-theme-hover transition-colors cursor-pointer"
                            onClick={() => {
                              setActionsMenuOpen(false);
                              setDeleteConfirm(true);
                            }}
                          >
                            Delete mosaic
                          </button>
                        </div>
                      </Show>
                    </div>
                  </div>
                </div>
              </div>
              <div class="flex gap-4 text-xs text-theme-text-secondary">
                <span>{data().panels.length} panels</span>
                <span>{formatIntegration(data().total_integration_seconds)} total</span>
                <span>{data().total_frames} frames</span>
              </div>
            </div>

            {/* Notes */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h3 class="text-sm font-semibold text-theme-text-primary">Notes</h3>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Free-form notes for the mosaic project. Content persists across sessions.
                  </p>
                  <p class="text-sm text-theme-text-secondary">
                    Example: record framing plans, capture progress, or processing decisions for the combined mosaic.
                  </p>
                </HelpPopover>
                <Show when={notesSaving()}>
                  <span class="ml-auto text-xs text-theme-text-secondary">Saving...</span>
                </Show>
              </div>
              <textarea
                class="block w-full bg-theme-surface border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
                placeholder="Add notes about this mosaic project..."
                value={notes()}
                onInput={(e) => onNotesInput(e.currentTarget.value)}
              />
            </div>

            {/* Needs Review Banner */}
            <Show when={mosaic()?.needs_review}>
              <div class="rounded-[var(--radius-sm)] bg-amber-500/10 border border-amber-500/30 p-4 flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-amber-400">Session review required</p>
                  <p class="text-xs text-theme-text-secondary mt-1">
                    This mosaic was created before session management. Select which sessions to include for each panel.
                  </p>
                </div>
                <button
                  disabled={includingAll()}
                  onClick={async () => {
                    const data = mosaic();
                    if (!data || includingAll()) return;
                    setIncludingAll(true);
                    try {
                      await Promise.all(
                        data.panels.map(async (panel) => {
                          const sessions = await api.getPanelSessions(data.id, panel.panel_id);
                          const available = sessions.sessions
                            .filter((s) => s.status === "available")
                            .map((s) => s.session_date);
                          if (available.length > 0) {
                            await api.updatePanelSessions(data.id, panel.panel_id, available, []);
                          }
                        }),
                      );
                      refetch();
                      showToast("All sessions included");
                    } catch (e: unknown) {
                      showToast(getErrorMessage(e, "Failed to include all sessions"), "error", 5000);
                    } finally {
                      setIncludingAll(false);
                    }
                  }}
                  class="px-4 py-2 text-sm bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-[var(--radius-sm)] hover:bg-amber-500/30 transition-colors whitespace-nowrap disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {includingAll() ? "Including..." : "Include All"}
                </button>
              </div>
            </Show>

            {/* Panel Thumbnails Grid */}
            <Show when={data().panels.some((p: PanelStats) => p.thumbnail_url)}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
                <div class="flex items-center gap-2">
                  <h2 class="text-sm font-semibold text-theme-text-primary">Panels</h2>
                  <HelpPopover>
                    <p class="text-sm text-theme-text-secondary">
                      Visual arrangement of the mosaic's constituent panels. Drag to reposition and drop a panel onto another to swap them.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Click a tile to select it (a highlighted outline marks the active tile), then use the <strong class="text-theme-text-primary">Rotate CW</strong> and <strong class="text-theme-text-primary">Flip H</strong> buttons to orient it. Right-clicking a tile rotates it directly. Click empty canvas or the same tile again to deselect.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      With a tile selected, lower the <strong class="text-theme-text-primary">Tile opacity</strong> slider to fade it and see the panels underneath while aligning. This is a visual aid only and is not saved.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Each tile shows total integration time (bottom-right) and, for panels below the maximum, a color-coded deficit (top-right) indicating how much more time is needed to match the leading panel. Green means within 20% of the max, amber within 60%, and red below that.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Use the <strong class="text-theme-text-primary">Labels</strong> button to toggle all text overlays on or off.
                    </p>
                    <p class="text-sm text-theme-text-secondary">
                      Auto-arrangement based on WCS headers is often unreliable, so manual layout is expected.
                    </p>
                  </HelpPopover>
                </div>
                <KonvaMosaicArranger
                  panels={data().panels}
                  rotationAngle={data().rotation_angle ?? 0}
                  pixelCoords={data().pixel_coords ?? false}
                  availableFilters={data().available_filters ?? []}
                  selectedFilter={selectedFilter()}
                  onFilterChange={handleFilterChange}
                  filterLoading={filterLoading()}
                  thumbnailOverrides={thumbnailOverrides()}
                  onSave={async (panels, rotationAngle) => {
                    try {
                      await api.batchUpdateMosaicPanels(params.mosaicId, panels, rotationAngle);
                    } catch (e) {
                      showToast("Failed to save panel layout", "error", 5000);
                      throw e;
                    }
                  }}
                  onPixelCoordsConverted={() => {
                    api.updateMosaic(params.mosaicId, { pixel_coords: true })
                      .catch(() => showToast("Failed to save coordinate conversion", "error", 5000));
                  }}
                />
              </div>
            </Show>

            {/* Per-Panel Session Management */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">Sessions</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    Manage which imaging sessions are included in each panel. Included sessions contribute to mosaic statistics and composites. Available sessions can be added at any time.
                  </p>
                </HelpPopover>
              </div>
              <For each={mosaic()?.panels ?? []}>
                {(panel) => {
                  // Sessions are fetched lazily and only for the expanded panel.
                  // Keying on stable primitives (id + panel id + expanded) means a
                  // mosaic refetch no longer restarts a fetch for every panel.
                  const [expanded, setExpanded] = createSignal(false);
                  const [panelSessions, { refetch: refetchSessions }] = createResource(
                    () => expanded() ? { mId: params.mosaicId, pId: panel.panel_id } : null,
                    (p) => api.getPanelSessions(p.mId, p.pId),
                  );
                  const included = () => panelSessions()?.sessions.filter((s) => s.status === "included") ?? [];
                  const available = () => panelSessions()?.sessions.filter((s) => s.status === "available") ?? [];

                  const handleInclude = async (dates: string[]) => {
                    const data = mosaic();
                    if (!data) return;
                    try {
                      await api.updatePanelSessions(data.id, panel.panel_id, dates, []);
                      refetchSessions();
                      refetch();
                    } catch (e: unknown) {
                      showToast(getErrorMessage(e, "Failed to include sessions"), "error", 5000);
                    }
                  };

                  const handleExclude = async (dates: string[]) => {
                    const data = mosaic();
                    if (!data) return;
                    try {
                      await api.updatePanelSessions(data.id, panel.panel_id, [], dates);
                      refetchSessions();
                      refetch();
                    } catch (e: unknown) {
                      showToast(getErrorMessage(e, "Failed to exclude sessions"), "error", 5000);
                    }
                  };

                  const suggestNextLabel = (label: string): string => {
                    const m = label.match(/^(.*) \(([a-z])\)$/i);
                    if (m) {
                      const nextChar = String.fromCharCode(m[2].charCodeAt(0) + 1);
                      return `${m[1]} (${nextChar})`;
                    }
                    return `${label} (b)`;
                  };

                  const handleIncludeAsNewPanel = async (sessionDate: string) => {
                    const data = mosaic();
                    if (!data) return;
                    const suggested = suggestNextLabel(panel.panel_label);
                    const newLabel = window.prompt("New panel label:", suggested);
                    if (!newLabel || !newLabel.trim()) return;
                    const label = newLabel.trim();
                    try {
                      const res = await api.addMosaicPanel(
                        data.id,
                        panel.target_id,
                        label,
                        panel.object_pattern ?? null,
                      );
                      await api.updatePanelSessions(data.id, res.panel_id, [sessionDate], []);
                      showToast(`Created panel '${label}' with session`);
                      refetch();
                    } catch (err) {
                      showToast(`Failed to create panel: ${err instanceof Error ? err.message : String(err)}`, "error", 5000);
                    }
                  };

                  return (
                    <div class="border border-theme-border rounded-[var(--radius-sm)] overflow-hidden">
                      <button
                        onClick={() => setExpanded(!expanded())}
                        class="w-full flex items-center justify-between p-3 hover:bg-theme-surface/50 transition-colors"
                      >
                        <div class="flex items-center gap-3">
                          <span class="text-sm font-medium text-theme-text-primary">{panel.panel_label}</span>
                          <span class="text-xs text-theme-text-secondary">{panel.target_name}</span>
                          <span class="text-xs text-theme-text-secondary">
                            {formatIntegration(panel.total_integration_seconds)} · {panel.total_frames} frames
                          </span>
                          <Show when={(panel.available_session_count ?? 0) > 0}>
                            <span class="text-xs text-amber-400">
                              {panel.available_session_count} available
                            </span>
                          </Show>
                        </div>
                        <span class="text-theme-text-secondary text-xs">{expanded() ? "\u25B2" : "\u25BC"}</span>
                      </button>

                      <div class={`grid transition-[grid-template-rows] duration-200 ${expanded() ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
                        <div class="overflow-hidden">
                          <div class="border-t border-theme-border">
                            {/* Included sessions */}
                            <Show when={included().length > 0}>
                              <div class="p-3 space-y-2">
                                <div class="text-xs font-medium text-theme-text-secondary">Included ({included().length})</div>
                                <table class="w-full text-xs">
                                  <thead>
                                    <tr class="text-theme-text-secondary">
                                      <th class="px-2 py-1 text-left">Date</th>
                                      <th class="px-2 py-1 text-left">Filters</th>
                                      <th class="px-2 py-1 text-right">Frames</th>
                                      <th class="px-2 py-1 text-right">Integration</th>
                                      <th class="px-2 py-1"></th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    <For each={included()}>
                                      {(sess) => (
                                        <tr class="border-t border-theme-border/30 hover:bg-theme-base/30">
                                          <td class="px-2 py-1 text-theme-text-primary">{sess.session_date}</td>
                                          <td class="px-2 py-1 text-theme-text-secondary">
                                            {Object.entries(sess.filters).map(([f, d]) => `${f}: ${d.frames}`).join(", ")}
                                          </td>
                                          <td class="px-2 py-1 text-right text-theme-text-secondary">{sess.total_frames}</td>
                                          <td class="px-2 py-1 text-right text-theme-text-secondary">{formatIntegration(sess.total_integration_seconds)}</td>
                                          <td class="px-2 py-1 text-right">
                                            <button
                                              onClick={() => handleExclude([sess.session_date])}
                                              class="text-xs text-theme-text-secondary hover:text-theme-danger transition-colors"
                                            >
                                              Remove
                                            </button>
                                          </td>
                                        </tr>
                                      )}
                                    </For>
                                  </tbody>
                                </table>
                              </div>
                            </Show>

                            {/* Available sessions */}
                            <Show when={available().length > 0}>
                              <div class="p-3 space-y-2 border-t border-theme-border/50">
                                <div class="flex items-center justify-between">
                                  <div class="text-xs font-medium text-amber-400">Available ({available().length})</div>
                                  <button
                                    onClick={() => handleInclude(available().map((s) => s.session_date))}
                                    class="text-xs text-theme-accent hover:underline"
                                  >
                                    Include all
                                  </button>
                                </div>
                                <table class="w-full text-xs">
                                  <thead>
                                    <tr class="text-theme-text-secondary">
                                      <th class="px-2 py-1 text-left">Date</th>
                                      <th class="px-2 py-1 text-left">Filters</th>
                                      <th class="px-2 py-1 text-right">Frames</th>
                                      <th class="px-2 py-1 text-right">Integration</th>
                                      <th class="px-2 py-1"></th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    <For each={available()}>
                                      {(sess) => (
                                        <tr class="border-t border-theme-border/30 hover:bg-theme-base/30 opacity-60">
                                          <td class="px-2 py-1 text-theme-text-primary">{sess.session_date}</td>
                                          <td class="px-2 py-1 text-theme-text-secondary">
                                            {Object.entries(sess.filters).map(([f, d]) => `${f}: ${d.frames}`).join(", ")}
                                          </td>
                                          <td class="px-2 py-1 text-right text-theme-text-secondary">{sess.total_frames}</td>
                                          <td class="px-2 py-1 text-right text-theme-text-secondary">{formatIntegration(sess.total_integration_seconds)}</td>
                                          <td class="px-2 py-1 text-right">
                                            <div class="flex gap-2 justify-end">
                                              <button
                                                onClick={() => handleInclude([sess.session_date])}
                                                class="text-xs text-theme-accent hover:underline"
                                              >
                                                Include
                                              </button>
                                              <button
                                                onClick={() => handleIncludeAsNewPanel(sess.session_date)}
                                                class="text-xs text-theme-accent hover:underline"
                                              >
                                                As new panel
                                              </button>
                                            </div>
                                          </td>
                                        </tr>
                                      )}
                                    </For>
                                  </tbody>
                                </table>
                              </div>
                            </Show>

                            <Show when={!panelSessions.loading && included().length === 0 && available().length === 0}>
                              <div class="p-3 text-xs text-theme-text-secondary">No sessions found for this panel.</div>
                            </Show>

                            <Show when={included().length === 0 && !panelSessions.loading}>
                              <div class="p-3 border-t border-theme-border/50 flex justify-end">
                                <button
                                  onClick={() =>
                                    setDeletePanelConfirm({
                                      panelId: panel.panel_id,
                                      panelLabel: panel.panel_label,
                                    })
                                  }
                                  class="text-xs text-theme-text-secondary hover:text-theme-danger transition-colors"
                                >
                                  Delete panel
                                </button>
                              </div>
                            </Show>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                }}
              </For>
            </div>
          </div>
        )}
      </Show>
      </div>

      <ConfirmDialog
        open={deletePanelConfirm() !== null}
        title="Delete panel"
        message={`Delete panel "${deletePanelConfirm()?.panelLabel}"? This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={async () => {
          const target = deletePanelConfirm();
          setDeletePanelConfirm(null);
          if (!target) return;
          const data = mosaic();
          if (!data) return;
          try {
            await api.removeMosaicPanel(data.id, target.panelId);
            showToast(`Deleted panel "${target.panelLabel}"`);
            refetch();
          } catch {
            showToast("Failed to delete panel", "error");
          }
        }}
        onCancel={() => setDeletePanelConfirm(null)}
      />

      <ConfirmDialog
        open={deleteConfirm()}
        title="Delete mosaic"
        message={`Delete mosaic "${mosaic()?.name ?? ""}"? This removes the mosaic and its panel layout. The underlying targets and frames are not affected. This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleteConfirm(false)}
      />

      <Show when={showComposite() && mosaic()}>
        <MosaicCompositeModal
          mosaicId={params.mosaicId}
          mosaicName={mosaic()!.name}
          filter={selectedFilter()}
          onClose={() => setShowComposite(false)}
        />
      </Show>
    </div>
  );
};

export default MosaicDetailPage;
