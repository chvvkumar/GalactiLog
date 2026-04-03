import { Component, Show, For, createResource, createSignal } from "solid-js";
import { A, useParams } from "@solidjs/router";
import { api } from "../api/client";
import MosaicGrid from "../components/mosaics/MosaicGrid";

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return h < 1 ? `${Math.round(h * 60)}m` : `${h.toFixed(1)}h`;
}

const MosaicDetailPage: Component = () => {
  const params = useParams<{ mosaicId: string }>();
  const [mosaic, { refetch }] = createResource(() => params.mosaicId, (id) => api.getMosaicDetail(id));

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
    <div class="p-4 space-y-4 max-w-7xl mx-auto">
      <A href="/mosaics" class="text-xs text-theme-accent hover:underline">&larr; Mosaics</A>

      <Show when={mosaic()} fallback={<div class="text-center text-theme-text-secondary py-8">Loading...</div>}>
        {(data) => (
          <>
            {/* Header */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <h2 class="text-lg font-bold text-theme-text-primary">{data().name}</h2>
              <div class="flex gap-4 mt-2 text-xs text-theme-text-secondary">
                <span>{data().panels.length} panels</span>
                <span>{formatHours(data().total_integration_seconds)} total</span>
                <span>{data().total_frames} frames</span>
              </div>
            </div>

            {/* Notes */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <div class="flex items-center justify-between mb-2">
                <h3 class="text-sm font-medium text-theme-text-primary">Notes</h3>
                <Show when={notesSaving()}>
                  <span class="text-xs text-theme-text-secondary">Saving...</span>
                </Show>
              </div>
              <textarea
                class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
                placeholder="Add notes about this mosaic project..."
                value={notes() || data().notes || ""}
                onInput={(e) => {
                  const val = e.currentTarget.value;
                  setNotes(val);
                  saveNotes(val);
                }}
              />
            </div>

            {/* Spatial Grid */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <h3 class="text-sm font-medium text-theme-text-primary mb-3">Panel Layout</h3>
              <MosaicGrid panels={data().panels} />
            </div>

            {/* Panel Table */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] overflow-hidden">
              <table class="w-full text-xs">
                <thead>
                  <tr class="bg-theme-elevated text-theme-text-secondary">
                    <th class="px-3 py-2 text-left">Panel</th>
                    <th class="px-3 py-2 text-left">Target</th>
                    <th class="px-3 py-2 text-right">Integration</th>
                    <th class="px-3 py-2 text-right">Frames</th>
                    <th class="px-3 py-2 text-left">Filters</th>
                    <th class="px-3 py-2 text-left">Last Session</th>
                    <th class="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  <For each={data().panels}>
                    {(panel) => (
                      <tr class="border-t border-theme-border hover:bg-theme-elevated/50">
                        <td class="px-3 py-2 text-theme-text-primary font-medium">{panel.panel_label}</td>
                        <td class="px-3 py-2 text-theme-text-primary">{panel.target_name}</td>
                        <td class="px-3 py-2 text-right text-theme-text-primary">{formatHours(panel.total_integration_seconds)}</td>
                        <td class="px-3 py-2 text-right text-theme-text-secondary">{panel.total_frames}</td>
                        <td class="px-3 py-2 text-theme-text-secondary">
                          {Object.entries(panel.filter_distribution)
                            .map(([f, s]) => `${f}: ${formatHours(s)}`)
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
          </>
        )}
      </Show>
    </div>
  );
};

export default MosaicDetailPage;
