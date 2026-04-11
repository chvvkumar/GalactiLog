import { Component, Show, For, createResource, createSignal, createMemo } from "solid-js";
import { A, useParams } from "@solidjs/router";
import { api } from "../api/client";
import type { PanelStats } from "../types";
import { formatIntegration, contentWidthClass } from "../utils/format";
import { useSettingsContext } from "../components/SettingsProvider";
import HelpPopover from "../components/HelpPopover";

const MosaicDetailPage: Component = () => {
  const ctx = useSettingsContext();
  const params = useParams<{ mosaicId: string }>();
  const [mosaic, { refetch }] = createResource(() => params.mosaicId, (id) => api.getMosaicDetail(id));

  type SortKey = "panel" | "target" | "integration" | "frames" | "session";
  type SortDir = "asc" | "desc";
  const [sortKey, setSortKey] = createSignal<SortKey>("panel");
  const [sortDir, setSortDir] = createSignal<SortDir>("asc");

  const toggleSort = (key: SortKey) => {
    if (sortKey() === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
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

  const [notes, setNotes] = createSignal("");
  const [notesSaving, setNotesSaving] = createSignal(false);
  let notesTimer: ReturnType<typeof setTimeout> | undefined;

  const saveNotes = (text: string) => {
    clearTimeout(notesTimer);
    notesTimer = setTimeout(async () => {
      setNotesSaving(true);
      try {
        await api.updateMosaic(params.mosaicId, { notes: text || undefined });
      } finally {
        setNotesSaving(false);
      }
    }, 1000);
  };

  return (
    <div class={`min-h-[calc(100vh-57px)] bg-theme-base ${contentWidthClass(ctx.contentWidth())}`}>
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
              <div class="flex items-center gap-2">
                <h2 class="text-sm font-semibold text-theme-text-primary">{data().name}</h2>
                <HelpPopover>
                  <p class="text-sm text-theme-text-secondary">
                    The Mosaic Detail page shows all panels belonging to this mosaic project along with their individual and combined statistics.
                  </p>
                  <ul class="list-disc list-inside space-y-1 text-sm text-theme-text-secondary">
                    <li>The <strong class="text-theme-text-primary">panel table</strong> lists each panel's target, integration time, frame count, and last session date. Click column headers to sort.</li>
                    <li>Click a panel's target name to navigate to its full Target Detail page.</li>
                    <li>Use <strong class="text-theme-text-primary">Notes</strong> to record project-level information like imaging goals, completion status, or processing notes.</li>
                  </ul>
                </HelpPopover>
              </div>
              <div class="flex gap-4 text-xs text-theme-text-secondary">
                <span>{data().panels.length} panels</span>
                <span>{formatIntegration(data().total_integration_seconds)} total</span>
                <span>{data().total_frames} frames</span>
              </div>
            </div>

            {/* Notes */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
              <Show when={notesSaving()}>
                <div class="flex justify-end mb-2">
                  <span class="text-xs text-theme-text-secondary">Saving...</span>
                </div>
              </Show>
              <textarea
                class="block w-full bg-theme-surface border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
                placeholder="Add notes about this mosaic project..."
                value={notes() || data().notes || ""}
                onInput={(e) => {
                  const val = e.currentTarget.value;
                  setNotes(val);
                  saveNotes(val);
                }}
              />
            </div>

            {/* Panel Thumbnails Grid */}
            <Show when={data().panels.some((p: PanelStats) => p.thumbnail_url)}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
                <h2 class="text-sm font-semibold text-theme-text-primary">Panels</h2>
                {(() => {
                  const n = data().panels.length;
                  const maxIntegration = Math.max(...data().panels.map((p: PanelStats) => p.total_integration_seconds));
                  const containerMax = Math.min(n * 280, 1680);
                  return (
                    <div
                      class="grid gap-2 mx-auto"
                      style={{ "grid-template-columns": `repeat(auto-fit, minmax(220px, 1fr))`, "max-width": `${containerMax}px` }}
                    >
                      <For each={[...data().panels].sort((a: PanelStats, b: PanelStats) => {
                        const na = parseInt(a.panel_label.replace(/\D/g, "")) || a.sort_order;
                        const nb = parseInt(b.panel_label.replace(/\D/g, "")) || b.sort_order;
                        return na - nb;
                      })}>
                        {(panel: PanelStats) => {
                          const diff = panel.total_integration_seconds - maxIntegration;
                          return (
                            <div>
                              <div class="relative">
                                <Show
                                  when={panel.thumbnail_url}
                                  fallback={
                                    <div class="aspect-square bg-theme-elevated border border-theme-border rounded flex items-center justify-center text-theme-text-secondary text-xs">
                                      {panel.panel_label}
                                    </div>
                                  }
                                >
                                  <img
                                    src={api.thumbnailUrl(panel.thumbnail_url!)}
                                    alt={panel.panel_label}
                                    class="w-full aspect-square object-cover rounded border border-theme-border"
                                  />
                                </Show>
                                <span class="absolute bottom-1 left-1 bg-black/60 text-white text-caption px-1.5 py-0.5 rounded">
                                  {panel.panel_label}
                                </span>
                              </div>
                              <div
                                class="text-center text-caption mt-1 text-theme-text-secondary"
                                title={diff < 0
                                  ? `${formatIntegration(Math.abs(diff))} less than the most-imaged panel`
                                  : "Most integration time across all panels"}
                              >
                                {formatIntegration(panel.total_integration_seconds)}
                                <Show when={diff < 0}>
                                  <span class="ml-1 text-amber-400">(-{formatIntegration(Math.abs(diff))})</span>
                                </Show>
                              </div>
                            </div>
                          );
                        }}
                      </For>
                    </div>
                  );
                })()}
              </div>
            </Show>

            {/* Panel Table */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h2 class="text-sm font-semibold text-theme-text-primary">Sessions</h2>
              <div class="overflow-hidden rounded border border-theme-border">
                <table class="w-full text-xs">
                  <thead>
                    <tr class="bg-theme-surface text-theme-text-secondary">
                      <th class="px-3 py-2 text-left cursor-pointer select-none hover:text-theme-text-primary" onClick={() => toggleSort("panel")}>Panel{sortIndicator("panel")}</th>
                      <th class="px-3 py-2 text-left cursor-pointer select-none hover:text-theme-text-primary" onClick={() => toggleSort("target")}>Target{sortIndicator("target")}</th>
                      <th class="px-3 py-2 text-right cursor-pointer select-none hover:text-theme-text-primary" onClick={() => toggleSort("integration")}>Integration{sortIndicator("integration")}</th>
                      <th class="px-3 py-2 text-right cursor-pointer select-none hover:text-theme-text-primary" onClick={() => toggleSort("frames")}>Frames{sortIndicator("frames")}</th>
                      <th class="px-3 py-2 text-left">Filters</th>
                      <th class="px-3 py-2 text-left cursor-pointer select-none hover:text-theme-text-primary" onClick={() => toggleSort("session")}>Session Date{sortIndicator("session")}</th>
                      <th class="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <For each={sortedPanels()}>
                      {(panel) => (
                        <tr class="border-t border-theme-border hover:bg-theme-surface/50">
                          <td class="px-3 py-2 text-theme-text-primary">{panel.panel_label}</td>
                          <td class="px-3 py-2 text-theme-text-primary">{panel.target_name}</td>
                          <td class="px-3 py-2 text-right text-theme-text-primary">{formatIntegration(panel.total_integration_seconds)}</td>
                          <td class="px-3 py-2 text-right text-theme-text-secondary">{panel.total_frames}</td>
                          <td class="px-3 py-2 text-theme-text-secondary">
                            {Object.entries(panel.filter_distribution)
                              .map(([f, s]) => `${f}: ${formatIntegration(s)}`)
                              .join(", ")}
                          </td>
                          <td class="px-3 py-2 text-theme-text-secondary">{panel.last_session_date || "\u2014"}</td>
                          <td class="px-3 py-2">
                            <A
                              href={`/targets/${encodeURIComponent(panel.target_id)}`}
                              class="text-theme-accent hover:underline"
                            >
                              Detail
                            </A>
                          </td>
                        </tr>
                      )}
                    </For>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </Show>
      </div>
    </div>
  );
};

export default MosaicDetailPage;
