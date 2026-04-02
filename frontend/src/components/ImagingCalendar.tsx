import { Component, For, createSignal, createResource, createMemo, Show } from "solid-js";
import { api } from "../api/client";
import type { CalendarEntry } from "../types";

const CELL = 13;
const GAP = 3;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLORS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"];

function intensity(hours: number): string {
  if (hours <= 0) return COLORS[0];
  if (hours < 1) return COLORS[1];
  if (hours < 3) return COLORS[2];
  if (hours < 6) return COLORS[3];
  return COLORS[4];
}

function buildWeeks(entries: CalendarEntry[], year: number | null): { date: string; hours: number; targets: number; frames: number }[][] {
  const map = new Map<string, CalendarEntry>();
  for (const e of entries) map.set(e.date, e);

  let start: Date;
  let end: Date;

  if (year) {
    start = new Date(year, 0, 1);
    end = new Date(year, 11, 31);
  } else {
    end = new Date();
    start = new Date();
    start.setFullYear(start.getFullYear() - 1);
    start.setDate(start.getDate() + 1);
  }

  // Align start to Monday
  const dayOfWeek = start.getDay();
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
  start.setDate(start.getDate() + mondayOffset);

  const weeks: { date: string; hours: number; targets: number; frames: number }[][] = [];
  let current = new Date(start);

  while (current <= end || weeks.length === 0) {
    const week: { date: string; hours: number; targets: number; frames: number }[] = [];
    for (let d = 0; d < 7; d++) {
      const iso = current.toISOString().slice(0, 10);
      const entry = map.get(iso);
      week.push({
        date: iso,
        hours: entry ? entry.integration_seconds / 3600 : 0,
        targets: entry ? entry.target_count : 0,
        frames: entry ? entry.frame_count : 0,
      });
      current.setDate(current.getDate() + 1);
    }
    weeks.push(week);
  }

  return weeks;
}

const ImagingCalendar: Component = () => {
  const currentYear = new Date().getFullYear();
  const yearOptions = () => {
    const years: (number | null)[] = [null];
    for (let y = currentYear; y >= currentYear - 5; y--) years.push(y);
    return years;
  };

  const [selectedYear, setSelectedYear] = createSignal<number | null>(null);
  const [tooltip, setTooltip] = createSignal<{ x: number; y: number; text: string } | null>(null);

  const [data] = createResource(
    () => selectedYear(),
    (year) => api.getCalendar(year ?? undefined),
  );

  const weeks = createMemo(() => {
    const entries = data();
    if (!entries) return [];
    return buildWeeks(entries, selectedYear());
  });

  const months = createMemo(() => {
    const w = weeks();
    if (w.length === 0) return [];
    const labels: { label: string; col: number }[] = [];
    let lastMonth = "";
    for (let i = 0; i < w.length; i++) {
      const d = new Date(w[i][0].date);
      const m = d.toLocaleString("en", { month: "short" });
      if (m !== lastMonth) {
        labels.push({ label: m, col: i });
        lastMonth = m;
      }
    }
    return labels;
  });

  const svgWidth = createMemo(() => {
    return 30 + weeks().length * (CELL + GAP);
  });

  const handleCellHover = (e: MouseEvent, day: { date: string; hours: number; targets: number; frames: number }) => {
    if (day.hours <= 0) {
      setTooltip(null);
      return;
    }
    const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
    setTooltip({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top - 10,
      text: `${day.date}: ${day.hours.toFixed(1)}h, ${day.targets} target${day.targets !== 1 ? "s" : ""}, ${day.frames} frame${day.frames !== 1 ? "s" : ""}`,
    });
  };

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-2">
      <div class="flex items-center justify-between">
        <h3 class="text-white font-medium text-sm">Imaging Calendar</h3>
        <select
          class="bg-theme-bg border border-theme-border rounded px-2 py-1 text-xs text-theme-text-secondary"
          value={selectedYear() ?? ""}
          onChange={(e) => setSelectedYear(e.currentTarget.value ? Number(e.currentTarget.value) : null)}
        >
          <For each={yearOptions()}>
            {(y) => <option value={y ?? ""}>{y ?? "Last 12 months"}</option>}
          </For>
        </select>
      </div>

      <Show when={data.loading}>
        <div class="text-center text-theme-text-secondary py-4 text-sm">Loading...</div>
      </Show>

      <Show when={!data.loading && weeks().length > 0}>
        <div class="overflow-x-auto scrollbar-thin" style={{ position: "relative" }}>
          <svg width={svgWidth()} height={7 * (CELL + GAP) + 30} class="block">
            {/* Month labels */}
            <For each={months()}>
              {(m) => (
                <text
                  x={30 + m.col * (CELL + GAP)}
                  y={10}
                  class="fill-theme-text-secondary"
                  font-size="10"
                >
                  {m.label}
                </text>
              )}
            </For>

            {/* Day labels */}
            <For each={DAYS}>
              {(label, i) => (
                <Show when={i() % 2 === 0}>
                  <text
                    x={0}
                    y={20 + i() * (CELL + GAP) + CELL - 2}
                    class="fill-theme-text-secondary"
                    font-size="10"
                  >
                    {label}
                  </text>
                </Show>
              )}
            </For>

            {/* Cells */}
            <For each={weeks()}>
              {(week, wi) => (
                <For each={week}>
                  {(day, di) => (
                    <rect
                      x={30 + wi() * (CELL + GAP)}
                      y={18 + di() * (CELL + GAP)}
                      width={CELL}
                      height={CELL}
                      rx={2}
                      fill={intensity(day.hours)}
                      onMouseEnter={(e) => handleCellHover(e, day)}
                      onMouseLeave={() => setTooltip(null)}
                    />
                  )}
                </For>
              )}
            </For>
          </svg>

          {/* Tooltip */}
          <Show when={tooltip()}>
            {(t) => (
              <div
                class="absolute pointer-events-none bg-theme-bg border border-theme-border rounded px-2 py-1 text-xs text-white whitespace-nowrap z-50"
                style={{
                  left: `${t().x}px`,
                  top: `${t().y - 28}px`,
                  transform: "translateX(-50%)",
                }}
              >
                {t().text}
              </div>
            )}
          </Show>
        </div>

        {/* Legend */}
        <div class="flex items-center gap-1 text-xs text-theme-text-secondary mt-1">
          <span>Less</span>
          <For each={COLORS}>
            {(color) => (
              <div
                style={{ width: `${CELL}px`, height: `${CELL}px`, background: color, "border-radius": "2px" }}
              />
            )}
          </For>
          <span>More</span>
        </div>
      </Show>
    </div>
  );
};

export default ImagingCalendar;
