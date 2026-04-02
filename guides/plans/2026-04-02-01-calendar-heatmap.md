# Imaging Calendar Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub-contributions-style calendar heatmap as an alternative to the existing imaging timeline on the Statistics page.

**Architecture:** New backend endpoint returns per-night aggregation of integration data. New frontend component renders the heatmap grid. A toggle switch lets the user flip between Timeline and Calendar views, persisted in graph settings.

**Tech Stack:** FastAPI + SQLAlchemy (backend), SolidJS + vanilla SVG/HTML (frontend), Chart.js not needed for this feature.

---

### Task 1: Backend — Calendar Stats Endpoint

**Files:**
- Modify: `backend/app/schemas/stats.py`
- Modify: `backend/app/api/stats.py`

- [ ] **Step 1: Add Pydantic schema for calendar entries**

In `backend/app/schemas/stats.py`, add at the end of the file:

```python
class CalendarEntry(BaseModel):
    date: str
    integration_seconds: float
    target_count: int
    frame_count: int
```

- [ ] **Step 2: Add the calendar endpoint**

In `backend/app/api/stats.py`, add a new endpoint. Import `CalendarEntry` from schemas and add:

```python
from app.schemas.stats import CalendarEntry

@router.get("/calendar", response_model=list[CalendarEntry])
async def get_calendar(
    year: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Per-night integration summary for heatmap display."""
    date_col = cast(Image.capture_date, Date)
    q = (
        select(
            date_col.label("night"),
            func.sum(Image.exposure_time).label("integration"),
            func.count(func.distinct(Image.resolved_target_id)).label("targets"),
            func.count(Image.id).label("frames"),
        )
        .where(Image.image_type == "LIGHT")
        .where(Image.capture_date.is_not(None))
        .group_by(date_col)
        .order_by(date_col)
    )
    if year:
        q = q.where(func.extract("year", Image.capture_date) == year)
    else:
        # Default: trailing 12 months
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=365)
        q = q.where(Image.capture_date >= cutoff)

    rows = (await session.execute(q)).all()
    return [
        CalendarEntry(
            date=str(r.night),
            integration_seconds=r.integration or 0,
            target_count=r.targets,
            frame_count=r.frames,
        )
        for r in rows
    ]
```

Note: The `stats.py` router is defined as `router = APIRouter(prefix="/stats", tags=["stats"])`. The `Query`, `Depends`, `cast`, `Date`, `func` imports are already present in that file.

- [ ] **Step 3: Test the endpoint manually**

Run: `cd backend && uvicorn app.main:app --reload`

Then in another terminal:
```bash
curl -s http://localhost:8000/api/stats/calendar | python -m json.tool | head -20
```

Expected: JSON array of `{date, integration_seconds, target_count, frame_count}` objects (may need auth cookie — test via browser).

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/stats.py backend/app/api/stats.py
git commit -m "feat: add calendar heatmap stats endpoint"
```

---

### Task 2: Frontend — Calendar Entry Type and API Method

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add TypeScript type**

In `frontend/src/types/index.ts`, add after the `StatsResponse` interface:

```typescript
// === Calendar Heatmap ===

export interface CalendarEntry {
  date: string;
  integration_seconds: number;
  target_count: number;
  frame_count: number;
}
```

- [ ] **Step 2: Add API method**

In `frontend/src/api/client.ts`, add to the `api` object (after `getStats`):

```typescript
  getCalendar: (year?: number) => {
    const params = year ? `?year=${year}` : "";
    return fetchJson<import("../types").CalendarEntry[]>(`/stats/calendar${params}`);
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: add calendar heatmap API client and types"
```

---

### Task 3: Frontend — ImagingCalendar Component

**Files:**
- Create: `frontend/src/components/ImagingCalendar.tsx`

- [ ] **Step 1: Create the heatmap component**

Create `frontend/src/components/ImagingCalendar.tsx`:

```typescript
import { Component, For, Show, createSignal, createResource, createMemo } from "solid-js";
import { api } from "../api/client";
import type { CalendarEntry } from "../types";

const CELL_SIZE = 14;
const CELL_GAP = 3;
const DAYS_IN_WEEK = 7;
const DAY_LABELS = ["Mon", "", "Wed", "", "Fri", "", "Sun"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function getColorForHours(hours: number, maxHours: number): string {
  if (hours === 0 || maxHours === 0) return "var(--color-theme-border)";
  const intensity = Math.min(hours / maxHours, 1);
  // 4-step scale
  if (intensity < 0.25) return "var(--color-calendar-l1, #0e4429)";
  if (intensity < 0.5) return "var(--color-calendar-l2, #006d32)";
  if (intensity < 0.75) return "var(--color-calendar-l3, #26a641)";
  return "var(--color-calendar-l4, #39d353)";
}

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return h < 1 ? `${Math.round(h * 60)}m` : `${h.toFixed(1)}h`;
}

const ImagingCalendar: Component = () => {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = createSignal<number | undefined>(undefined);
  const [data] = createResource(year, (y) => api.getCalendar(y));
  const [tooltip, setTooltip] = createSignal<{ x: number; y: number; entry: CalendarEntry } | null>(null);

  const calendarData = createMemo(() => {
    const entries = data() || [];
    const map = new Map<string, CalendarEntry>();
    for (const e of entries) map.set(e.date, e);

    // Build grid: determine date range
    const now = new Date();
    const startDate = year()
      ? new Date(year()!, 0, 1)
      : new Date(now.getFullYear() - 1, now.getMonth(), now.getDate() + 1);
    const endDate = year()
      ? new Date(year()!, 11, 31)
      : now;

    // Align start to Monday
    const start = new Date(startDate);
    const dayOfWeek = start.getDay();
    const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
    start.setDate(start.getDate() + mondayOffset);

    const weeks: { date: Date; entry: CalendarEntry | null }[][] = [];
    let currentWeek: { date: Date; entry: CalendarEntry | null }[] = [];
    const d = new Date(start);
    let maxSeconds = 0;

    while (d <= endDate || currentWeek.length > 0) {
      const dateStr = d.toISOString().slice(0, 10);
      const entry = map.get(dateStr) || null;
      if (entry && entry.integration_seconds > maxSeconds) {
        maxSeconds = entry.integration_seconds;
      }
      currentWeek.push({ date: new Date(d), entry });
      if (currentWeek.length === 7) {
        weeks.push(currentWeek);
        currentWeek = [];
      }
      d.setDate(d.getDate() + 1);
      if (d > endDate && currentWeek.length === 0) break;
    }
    if (currentWeek.length > 0) {
      while (currentWeek.length < 7) {
        currentWeek.push({ date: new Date(d), entry: null });
        d.setDate(d.getDate() + 1);
      }
      weeks.push(currentWeek);
    }

    return { weeks, maxSeconds };
  });

  // Month labels
  const monthLabels = createMemo(() => {
    const { weeks } = calendarData();
    const labels: { text: string; col: number }[] = [];
    let lastMonth = -1;
    for (let w = 0; w < weeks.length; w++) {
      const firstDay = weeks[w][0];
      const month = firstDay.date.getMonth();
      if (month !== lastMonth) {
        labels.push({ text: MONTH_NAMES[month], col: w });
        lastMonth = month;
      }
    }
    return labels;
  });

  // Year options
  const years = createMemo(() => {
    const y = currentYear;
    return [y, y - 1, y - 2, y - 3];
  });

  const LEFT_PAD = 30;
  const TOP_PAD = 20;
  const svgWidth = () => LEFT_PAD + calendarData().weeks.length * (CELL_SIZE + CELL_GAP);
  const svgHeight = TOP_PAD + DAYS_IN_WEEK * (CELL_SIZE + CELL_GAP);

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-theme-text-primary">Imaging Calendar</h3>
        <div class="flex items-center gap-2">
          <select
            class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary"
            value={year() ?? ""}
            onChange={(e) => setYear(e.currentTarget.value ? Number(e.currentTarget.value) : undefined)}
          >
            <option value="">Last 12 months</option>
            <For each={years()}>
              {(y) => <option value={y}>{y}</option>}
            </For>
          </select>
        </div>
      </div>

      <Show when={!data.loading} fallback={<div class="text-xs text-theme-text-secondary py-8 text-center">Loading...</div>}>
        <div class="overflow-x-auto relative" onMouseLeave={() => setTooltip(null)}>
          <svg width={svgWidth()} height={svgHeight} class="block">
            {/* Month labels */}
            <For each={monthLabels()}>
              {(label) => (
                <text
                  x={LEFT_PAD + label.col * (CELL_SIZE + CELL_GAP)}
                  y={12}
                  class="fill-theme-text-secondary"
                  font-size="10"
                >
                  {label.text}
                </text>
              )}
            </For>

            {/* Day labels */}
            <For each={DAY_LABELS}>
              {(label, i) => (
                <Show when={label}>
                  <text
                    x={0}
                    y={TOP_PAD + i() * (CELL_SIZE + CELL_GAP) + CELL_SIZE - 2}
                    class="fill-theme-text-secondary"
                    font-size="10"
                  >
                    {label}
                  </text>
                </Show>
              )}
            </For>

            {/* Cells */}
            <For each={calendarData().weeks}>
              {(week, wi) => (
                <For each={week}>
                  {(day, di) => {
                    const hours = (day.entry?.integration_seconds || 0) / 3600;
                    const maxHours = calendarData().maxSeconds / 3600;
                    return (
                      <rect
                        x={LEFT_PAD + wi() * (CELL_SIZE + CELL_GAP)}
                        y={TOP_PAD + di() * (CELL_SIZE + CELL_GAP)}
                        width={CELL_SIZE}
                        height={CELL_SIZE}
                        rx={2}
                        fill={getColorForHours(hours, maxHours)}
                        class="cursor-pointer"
                        onMouseEnter={(e) => {
                          if (day.entry) {
                            setTooltip({ x: e.clientX, y: e.clientY, entry: day.entry });
                          }
                        }}
                        onMouseLeave={() => setTooltip(null)}
                      />
                    );
                  }}
                </For>
              )}
            </For>
          </svg>

          {/* Tooltip */}
          <Show when={tooltip()}>
            {(t) => (
              <div
                class="fixed z-50 bg-theme-elevated border border-theme-border rounded px-2 py-1 text-xs shadow-[var(--shadow-md)] pointer-events-none"
                style={{ left: `${t().x + 10}px`, top: `${t().y - 40}px` }}
              >
                <div class="font-medium text-theme-text-primary">{t().entry.date}</div>
                <div class="text-theme-text-secondary">
                  {formatHours(t().entry.integration_seconds)} &middot; {t().entry.target_count} target{t().entry.target_count !== 1 ? "s" : ""} &middot; {t().entry.frame_count} frames
                </div>
              </div>
            )}
          </Show>
        </div>

        {/* Legend */}
        <div class="flex items-center gap-2 mt-3 text-xs text-theme-text-secondary">
          <span>Less</span>
          <div class="flex gap-1">
            <div class="w-3 h-3 rounded-sm" style={{ background: "var(--color-theme-border)" }} />
            <div class="w-3 h-3 rounded-sm" style={{ background: "var(--color-calendar-l1, #0e4429)" }} />
            <div class="w-3 h-3 rounded-sm" style={{ background: "var(--color-calendar-l2, #006d32)" }} />
            <div class="w-3 h-3 rounded-sm" style={{ background: "var(--color-calendar-l3, #26a641)" }} />
            <div class="w-3 h-3 rounded-sm" style={{ background: "var(--color-calendar-l4, #39d353)" }} />
          </div>
          <span>More</span>
        </div>
      </Show>
    </div>
  );
};

export default ImagingCalendar;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ImagingCalendar.tsx
git commit -m "feat: add ImagingCalendar heatmap component"
```

---

### Task 4: Frontend — Toggle Between Timeline and Calendar on Stats Page

**Files:**
- Modify: `frontend/src/pages/StatisticsPage.tsx`
- Modify: `frontend/src/types/index.ts` (GraphSettings if needed)

- [ ] **Step 1: Add toggle state and render both views**

In `frontend/src/pages/StatisticsPage.tsx`, add the import for the calendar and a toggle:

```typescript
import { Component, Show, createSignal } from "solid-js";
```

Add import:
```typescript
import ImagingCalendar from "../components/ImagingCalendar";
```

Replace the `<ImagingTimeline ... />` block (currently around line 44-48) with:

```typescript
            {(() => {
              const [view, setView] = createSignal<"timeline" | "calendar">("timeline");
              return (
                <div>
                  <div class="flex items-center gap-2 mb-2">
                    <button
                      class={`text-xs px-2.5 py-1 rounded-[var(--radius-sm)] transition-colors ${
                        view() === "timeline"
                          ? "bg-theme-elevated text-theme-text-primary font-medium"
                          : "text-theme-text-secondary hover:text-theme-text-primary"
                      }`}
                      onClick={() => setView("timeline")}
                    >
                      Timeline
                    </button>
                    <button
                      class={`text-xs px-2.5 py-1 rounded-[var(--radius-sm)] transition-colors ${
                        view() === "calendar"
                          ? "bg-theme-elevated text-theme-text-primary font-medium"
                          : "text-theme-text-secondary hover:text-theme-text-primary"
                      }`}
                      onClick={() => setView("calendar")}
                    >
                      Calendar
                    </button>
                  </div>
                  <Show when={view() === "timeline"}>
                    <ImagingTimeline
                      monthly={data().timeline_monthly}
                      weekly={data().timeline_weekly}
                      daily={data().timeline_daily}
                    />
                  </Show>
                  <Show when={view() === "calendar"}>
                    <ImagingCalendar />
                  </Show>
                </div>
              );
            })()}
```

- [ ] **Step 2: Verify in browser**

Run: `cd frontend && npm run dev`

Navigate to `/statistics`. Verify:
- Toggle buttons appear above the timeline area
- "Timeline" shows the existing bar chart
- "Calendar" shows the heatmap grid
- Hovering cells shows tooltip with date, hours, targets, frames
- Year selector works

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/StatisticsPage.tsx
git commit -m "feat: add timeline/calendar toggle on statistics page"
```
