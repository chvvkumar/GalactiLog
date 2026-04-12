import { Component, Show, For, createResource, createSignal, createEffect } from "solid-js";
import { A, useParams, useSearchParams } from "@solidjs/router";
import { api } from "../api/client";
import type { TargetDetailResponse, SessionDetail } from "../types";
import SessionAccordionCard from "../components/SessionAccordionCard";
import { showToast } from "../components/Toast";
import FilterBadges from "../components/FilterBadges";
import TargetMetricsChart from "../components/TargetMetricsChart";
import ExportModal from "../components/ExportModal";
import AladinViewer from "../components/AladinViewer";
import { useSettingsContext } from "../components/SettingsProvider";
import { isFieldVisible } from "../utils/displaySettings";
import { contentWidthClass } from "../utils/format";
import HelpPopover from "../components/HelpPopover";
import { timezoneLabel } from "../utils/dateTime";

import { formatIntegration } from "../utils/format";

function formatCoord(val: number | null, label: string): string {
  if (val === null) return "";
  return `${label} ${val.toFixed(3)}°`;
}

function formatSize(major: number | null, minor: number | null): string {
  if (major === null) return "";
  if (minor === null) return `${major.toFixed(1)}'`;
  return `${major.toFixed(1)}' \u00d7 ${minor.toFixed(1)}'`;
}

const TargetDetailPage: Component = () => {
  const params = useParams<{ targetId: string }>();
  const [searchParams] = useSearchParams();
  const ctx = useSettingsContext();
  const { displaySettings, graphSettings, saveGraphSettings, timezone, contentWidth } = ctx;
  const tzLabel = () => timezoneLabel(timezone());
  const visible = (group: Parameters<typeof isFieldVisible>[1], field: string) =>
    isFieldVisible(displaySettings(), group, field);

  const [targetDetail] = createResource(
    () => params.targetId,
    (id) => api.getTargetDetail(id),
  );

  const [showExport, setShowExport] = createSignal(false);
  const [expandedSessions, setExpandedSessions] = createSignal<Set<string>>(new Set());
  const [sessionCache, setSessionCache] = createSignal<Record<string, SessionDetail>>({});
  const [targetChartExpanded, setTargetChartExpanded] = createSignal(graphSettings().target_chart_expanded);
  const [selectedChartDates, setSelectedChartDates] = createSignal<string[]>([]);

  const [skyViewExpanded, setSkyViewExpanded] = createSignal(false);
  const [notesExpanded, setNotesExpanded] = createSignal(false);
  const [targetNotes, setTargetNotes] = createSignal<string>("");
  const [notesSaving, setNotesSaving] = createSignal(false);
  let notesTimer: ReturnType<typeof setTimeout> | undefined;

  // Initialize notes when data loads
  createEffect(() => {
    const detail = targetDetail();
    if (detail?.notes) setTargetNotes(detail.notes);
  });

  const saveTargetNotes = (text: string) => {
    clearTimeout(notesTimer);
    notesTimer = setTimeout(async () => {
      setNotesSaving(true);
      try {
        await api.updateTargetNotes(params.targetId, text || null);
      } finally {
        setNotesSaving(false);
      }
    }, 1000);
  };

  let chartDatesInitialized = false;
  createEffect(() => {
    const detail = targetDetail();
    if (detail && !chartDatesInitialized) {
      chartDatesInitialized = true;
      setSelectedChartDates(detail.sessions.slice(0, 1).map((s) => s.session_date));
    }
  });

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

  const loadSessionDetail = async (date: string) => {
    if (sessionCache()[date]) return;
    try {
      const detail = await api.getSessionDetail(params.targetId, date);
      setSessionCache((prev) => ({ ...prev, [date]: detail }));
    } catch (e: any) {
      showToast(
        e?.message ?? `Failed to load session ${date}`,
        "error",
      );
      setExpandedSessions((prev) => {
        const next = new Set(prev);
        next.delete(date);
        return next;
      });
    }
  };

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
    <div class={`min-h-[calc(100vh-57px)] bg-theme-base ${contentWidthClass(contentWidth())}`}>
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

      <Show when={showExport() && targetDetail()}>
        <ExportModal
          targetId={params.targetId}
          targetName={targetDetail()!.primary_name}
          sessions={targetDetail()!.sessions}
          onClose={() => setShowExport(false)}
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
                  <div class="flex items-center gap-2">
                    <h1 class="text-2xl font-semibold tracking-tight text-theme-text-primary">
                      {detail().primary_name}
                    </h1>
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
                        <li>Use the <strong class="text-theme-text-primary">Export</strong> button to generate AstroBin-compatible CSV files for your imaging data.</li>
                      </ul>
                    </HelpPopover>
                  </div>
                  <div class="text-xs text-theme-text-secondary mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
                    <Show when={detail().object_category}>
                      <span>{detail().object_category}</span>
                      <span>·</span>
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
              <div class="flex flex-wrap gap-3 mt-4 items-center">
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                  <div class="text-lg font-semibold text-metric-integration">{formatIntegration(detail().total_integration_seconds)}</div>
                  <div class="text-caption text-theme-text-secondary">Total Integration</div>
                </div>
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                  <div class="text-lg font-semibold text-metric-frames">{detail().total_frames.toLocaleString()}</div>
                  <div class="text-caption text-theme-text-secondary">Total Frames</div>
                </div>
                <Show when={visible("quality", "hfr")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-hfr">
                      {detail().avg_hfr?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-caption text-theme-text-secondary">Avg HFR</div>
                  </div>
                </Show>
                <Show when={visible("quality", "eccentricity")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-eccentricity">
                      {detail().avg_eccentricity?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-caption text-theme-text-secondary">Avg Eccentricity</div>
                  </div>
                </Show>
                <Show when={visible("quality", "fwhm")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                    <div class="text-lg font-semibold text-theme-info">
                      {detail().avg_fwhm?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-caption text-theme-text-secondary">Avg FWHM</div>
                  </div>
                </Show>
                <Show when={visible("quality", "detected_stars")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-stars">
                      {detail().avg_detected_stars?.toFixed(0) ?? "—"}
                    </div>
                    <div class="text-caption text-theme-text-secondary">Avg Stars</div>
                  </div>
                </Show>
                <Show when={visible("guiding", "rms_total")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[80px] sm:min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-guiding">
                      {detail().avg_guiding_rms_arcsec !== null ? `${detail().avg_guiding_rms_arcsec?.toFixed(2)}"` : "—"}
                    </div>
                    <div class="text-caption text-theme-text-secondary">Avg Guide RMS</div>
                  </div>
                </Show>
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center flex flex-col items-center justify-center min-w-[80px] sm:min-w-[100px]">
                  <div class="mb-1">
                    <FilterBadges distribution={Object.fromEntries(detail().filters_used.map(f => [f, 0]))} compact />
                  </div>
                  <div class="text-caption text-theme-text-secondary">Filters Used</div>
                </div>
                <div class="ml-auto flex flex-col items-start sm:items-end gap-2 shrink-0 self-center">
                  <button
                    class="px-4 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm font-medium hover:bg-theme-accent/25 transition-colors"
                    onClick={() => setShowExport(true)}
                  >
                    Export
                  </button>
                  <div class="text-left sm:text-right text-xs text-theme-text-secondary">
                    <div>{detail().session_count} sessions</div>
                    <div class="mt-0.5">
                      {detail().first_session_date} → {detail().last_session_date} ({tzLabel()})
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* SAC Observing Notes */}
            <Show when={detail().sac_description || detail().sac_notes}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border p-4">
                <div class="text-xs font-medium text-theme-text-tertiary mb-2">Observing Notes</div>
                <Show when={detail().sac_description}>
                  <p class="text-sm text-theme-text-primary">{detail().sac_description}</p>
                </Show>
                <Show when={detail().sac_notes}>
                  <p class="text-xs text-theme-text-secondary mt-1">{detail().sac_notes}</p>
                </Show>
              </div>
            </Show>

            {/* Sky View & Reference Thumbnail */}
            <Show when={detail().ra != null && detail().dec != null}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
                <button
                  class="flex items-center justify-between w-full py-2 cursor-pointer group"
                  onClick={() => setSkyViewExpanded((v) => !v)}
                >
                  <h3 class="text-xs font-semibold uppercase tracking-wider text-theme-text-secondary border-l-2 border-theme-accent pl-2 group-hover:text-theme-text-primary transition-colors">
                    Sky View
                  </h3>
                  <svg
                    class={`w-3.5 h-3.5 transition-transform duration-200 text-theme-text-tertiary ${skyViewExpanded() ? "rotate-180" : ""}`}
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                  </svg>
                </button>
                <Show when={skyViewExpanded()}>
                  <div class="mt-2 space-y-3">
                    <AladinViewer
                      ra={detail().ra!}
                      dec={detail().dec!}
                      fov={detail().size_major ? detail().size_major! * 1.5 / 60 : 0.5}
                    />
                    <Show when={detail().reference_thumbnail_path}>
                      <div class="mt-2">
                        <div class="text-xs font-medium text-theme-text-tertiary mb-1">DSS Reference</div>
                        <img
                          src={`/api/targets/${detail().target_id}/reference-thumbnail`}
                          alt="DSS reference"
                          class="rounded-[var(--radius-sm)] border border-theme-border max-w-xs"
                          loading="lazy"
                        />
                      </div>
                    </Show>
                  </div>
                </Show>
              </div>
            </Show>

            {/* Target Notes */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
              <button
                class="flex items-center justify-between w-full py-2 cursor-pointer group"
                onClick={() => setNotesExpanded((v) => !v)}
              >
                <h3 class="text-xs font-semibold uppercase tracking-wider text-theme-text-secondary border-l-2 border-theme-accent pl-2 group-hover:text-theme-text-primary transition-colors">
                  Notes
                  <Show when={targetNotes()}>
                    <span class="text-theme-text-tertiary font-normal normal-case tracking-normal ml-2">has content</span>
                  </Show>
                </h3>
                <div class="flex items-center gap-2">
                  <Show when={notesSaving()}>
                    <span class="text-xs text-theme-text-secondary">Saving...</span>
                  </Show>
                  <svg
                    class={`w-3.5 h-3.5 transition-transform duration-200 text-theme-text-tertiary ${notesExpanded() ? "rotate-180" : ""}`}
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                  </svg>
                </div>
              </button>
              <Show when={notesExpanded()}>
                <textarea
                  class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[60px] mt-2"
                  placeholder="Add notes about this target..."
                  value={targetNotes()}
                  onInput={(e) => {
                    const val = e.currentTarget.value;
                    setTargetNotes(val);
                    saveTargetNotes(val);
                  }}
                />
              </Show>
            </div>

            {/* Target Metrics Chart */}
            <Show when={targetDetail()}>
              <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4">
                <button
                  class="flex items-center justify-between w-full py-2 cursor-pointer group"
                  onClick={toggleTargetChart}
                >
                  <h3 class="text-xs font-semibold uppercase tracking-wider text-theme-text-secondary border-l-2 border-theme-accent pl-2 group-hover:text-theme-text-primary transition-colors">
                    Graphs
                  </h3>
                  <svg
                    class={`w-3.5 h-3.5 transition-transform duration-200 text-theme-text-tertiary ${targetChartExpanded() ? "rotate-180" : ""}`}
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
                  </svg>
                </button>
                <Show when={targetChartExpanded()}>
                  <TargetMetricsChart
                    selectedDates={selectedChartDates()}
                    sessionDetails={sessionCache()}
                    expanded={targetChartExpanded()}
                    onLoadSession={loadSessionDetail}
                    availableFilters={detail().filters_used ?? []}
                  />
                </Show>
              </div>
            </Show>

            {/* Session Table */}
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em p-4 space-y-4">
              <h2 class="text-sm font-semibold text-theme-text-primary">Sessions</h2>
              <div class="overflow-x-auto">
              <table class="w-full border-collapse min-w-[600px]">
                <thead>
                  <tr class="text-caption text-theme-text-tertiary uppercase tracking-wider border-b border-theme-border-em">
                    <Show when={targetChartExpanded()}>
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
                    </Show>
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
                <tbody>
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
                        showCheckbox={targetChartExpanded()}
                        checked={selectedChartDates().includes(session.session_date)}
                        onCheckChange={() => toggleChartDate(session.session_date)}
                        targetId={params.targetId}
                      />
                    )}
                  </For>
                </tbody>
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
