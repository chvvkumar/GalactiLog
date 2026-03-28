import { Component, Show, For, createResource, createSignal, createEffect } from "solid-js";
import { A, useParams, useSearchParams } from "@solidjs/router";
import { api } from "../api/client";
import type { TargetDetailResponse, SessionDetail } from "../types";
import SessionAccordionCard from "../components/SessionAccordionCard";
import FilterBadges from "../components/FilterBadges";
import TargetMetricsChart, { MetricsTrendButton } from "../components/TargetMetricsChart";
import { useSettingsContext } from "../components/SettingsProvider";
import { isFieldVisible } from "../utils/displaySettings";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

function formatCoord(val: number | null, label: string): string {
  if (val === null) return "";
  return `${label} ${val.toFixed(3)}°`;
}

const TargetDetailPage: Component = () => {
  const params = useParams<{ targetId: string }>();
  const [searchParams] = useSearchParams();
  const { displaySettings, graphSettings, saveGraphSettings } = useSettingsContext();
  const visible = (group: Parameters<typeof isFieldVisible>[1], field: string) =>
    isFieldVisible(displaySettings(), group, field);

  const [targetDetail] = createResource(
    () => params.targetId,
    (id) => api.getTargetDetail(id),
  );

  const [expandedSessions, setExpandedSessions] = createSignal<Set<string>>(new Set());
  const [sessionCache, setSessionCache] = createSignal<Record<string, SessionDetail>>({});
  const [targetChartExpanded, setTargetChartExpanded] = createSignal(graphSettings().target_chart_expanded);
  const [selectedChartDates, setSelectedChartDates] = createSignal<string[]>([]);

  let chartDatesInitialized = false;
  createEffect(() => {
    const detail = targetDetail();
    if (detail && !chartDatesInitialized) {
      chartDatesInitialized = true;
      setSelectedChartDates(detail.sessions.map((s) => s.session_date));
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
    const detail = await api.getSessionDetail(params.targetId, date);
    setSessionCache((prev) => ({ ...prev, [date]: detail }));
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
    <div class="min-h-[calc(100vh-57px)] bg-theme-base">
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

      <Show when={targetDetail()}>
        {(detail) => (
          <>
            {/* Target Hero */}
            <div class="px-6 py-5 border-b border-theme-border">
              <div class="flex justify-between items-start">
                <div>
                  <h1 class="text-2xl font-semibold tracking-tight text-theme-text-primary">
                    {detail().primary_name}
                  </h1>
                  <div class="text-xs text-theme-text-secondary mt-1 space-x-2">
                    <Show when={detail().object_type}>
                      <span>{detail().object_type}</span>
                      <span>·</span>
                    </Show>
                    <Show when={detail().ra !== null}>
                      <span>{formatCoord(detail().ra, "RA")}</span>
                    </Show>
                    <Show when={detail().dec !== null}>
                      <span>{formatCoord(detail().dec, "Dec")}</span>
                    </Show>
                    <Show when={detail().aliases.length > 1}>
                      <span>· Aliases: {detail().aliases.slice(1).join(", ")}</span>
                    </Show>
                  </div>
                </div>
                <div class="text-right text-xs text-theme-text-secondary">
                  <div>{detail().session_count} sessions</div>
                  <div class="mt-0.5">
                    {detail().first_session_date} → {detail().last_session_date}
                  </div>
                </div>
              </div>

              {/* Cumulative stats bar */}
              <div class="flex flex-wrap gap-3 mt-4 items-center">
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                  <div class="text-lg font-semibold text-metric-integration">{formatHours(detail().total_integration_seconds)}</div>
                  <div class="text-[10px] text-theme-text-secondary">Total Integration</div>
                </div>
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                  <div class="text-lg font-semibold text-metric-frames">{detail().total_frames.toLocaleString()}</div>
                  <div class="text-[10px] text-theme-text-secondary">Total Frames</div>
                </div>
                <Show when={visible("quality", "hfr")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-hfr">
                      {detail().avg_hfr?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-[10px] text-theme-text-secondary">Avg HFR</div>
                  </div>
                </Show>
                <Show when={visible("quality", "eccentricity")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-eccentricity">
                      {detail().avg_eccentricity?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-[10px] text-theme-text-secondary">Avg Eccentricity</div>
                  </div>
                </Show>
                <Show when={visible("quality", "fwhm")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                    <div class="text-lg font-semibold text-theme-info">
                      {detail().avg_fwhm?.toFixed(2) ?? "—"}
                    </div>
                    <div class="text-[10px] text-theme-text-secondary">Avg FWHM</div>
                  </div>
                </Show>
                <Show when={visible("quality", "detected_stars")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-stars">
                      {detail().avg_detected_stars?.toFixed(0) ?? "—"}
                    </div>
                    <div class="text-[10px] text-theme-text-secondary">Avg Stars</div>
                  </div>
                </Show>
                <Show when={visible("guiding", "rms_total")}>
                  <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center min-w-[100px]">
                    <div class="text-lg font-semibold text-metric-guiding">
                      {detail().avg_guiding_rms_arcsec !== null ? `${detail().avg_guiding_rms_arcsec?.toFixed(2)}"` : "—"}
                    </div>
                    <div class="text-[10px] text-theme-text-secondary">Avg Guide RMS</div>
                  </div>
                </Show>
                <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-3 text-center flex flex-col items-center justify-center min-w-[100px]">
                  <div class="mb-1">
                    <FilterBadges distribution={Object.fromEntries(detail().filters_used.map(f => [f, 0]))} compact />
                  </div>
                  <div class="text-[10px] text-theme-text-secondary">Filters Used</div>
                </div>
                <MetricsTrendButton expanded={targetChartExpanded()} onToggle={toggleTargetChart} />
              </div>
            </div>

            {/* Target Metrics Chart */}
            <Show when={targetDetail()}>
              <TargetMetricsChart
                selectedDates={selectedChartDates()}
                sessionDetails={sessionCache()}
                expanded={targetChartExpanded()}
                onLoadSession={loadSessionDetail}
              />
            </Show>

            {/* Session Table */}
            <div class="px-6 py-4">
              <table class="w-full border-collapse">
                <thead>
                  <tr class="text-[10px] text-theme-text-tertiary uppercase tracking-wider border-b border-theme-border-em">
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
                    <th class="py-2 px-4 text-left font-medium">Date</th>
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
                      />
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

export default TargetDetailPage;
