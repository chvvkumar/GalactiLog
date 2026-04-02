# Conditions Correlation Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new Analysis page with scatter plots correlating environmental conditions to image quality metrics, scoped by equipment combo, with both pre-built charts and a custom explorer.

**Architecture:** New backend router with a correlation endpoint that returns (x, y) data points + trend line. New frontend page with equipment selector, frame/session toggle, three pre-built charts, and a custom explorer with axis dropdowns.

**Tech Stack:** FastAPI + SQLAlchemy + numpy (backend trend line), SolidJS + Chart.js scatter plugin (frontend)

---

### Task 1: Backend — Correlation Schemas

**Files:**
- Create: `backend/app/schemas/analysis.py`

- [ ] **Step 1: Create the analysis schemas**

Create `backend/app/schemas/analysis.py`:

```python
from pydantic import BaseModel


class CorrelationPoint(BaseModel):
    x: float
    y: float
    date: str
    target_name: str | None = None


class TrendLine(BaseModel):
    slope: float
    intercept: float
    r_squared: float


class CorrelationResponse(BaseModel):
    points: list[CorrelationPoint]
    trend: TrendLine | None = None
    x_metric: str
    y_metric: str
    granularity: str
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/analysis.py
git commit -m "feat: add correlation analysis schemas"
```

---

### Task 2: Backend — Analysis Router

**Files:**
- Create: `backend/app/api/analysis.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: Create the analysis router with correlation endpoint**

Create `backend/app/api/analysis.py`:

```python
import statistics
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Image, Target, User
from app.schemas.analysis import CorrelationPoint, CorrelationResponse, TrendLine
from app.services.normalization import load_alias_maps, expand_canonical
from app.api.auth import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Allowed metric names mapped to Image model columns
METRIC_MAP = {
    # Environmental / equipment (X axis candidates)
    "humidity": Image.humidity,
    "wind_speed": Image.wind_speed,
    "ambient_temp": Image.ambient_temp,
    "dew_point": Image.dew_point,
    "pressure": Image.pressure,
    "cloud_cover": Image.cloud_cover,
    "sky_quality": Image.sky_quality,
    "focuser_temp": Image.focuser_temp,
    "airmass": Image.airmass,
    "sensor_temp": Image.sensor_temp,
    # Quality (Y axis candidates)
    "hfr": Image.median_hfr,
    "fwhm": Image.fwhm,
    "eccentricity": Image.eccentricity,
    "guiding_rms": Image.guiding_rms_arcsec,
    "guiding_rms_ra": Image.guiding_rms_ra_arcsec,
    "guiding_rms_dec": Image.guiding_rms_dec_arcsec,
    "detected_stars": Image.detected_stars,
    "adu_mean": Image.adu_mean,
    "adu_median": Image.adu_median,
    "adu_stdev": Image.adu_stdev,
}


def _compute_trend(points: list[CorrelationPoint]) -> TrendLine | None:
    """Simple linear regression."""
    if len(points) < 3:
        return None
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # R-squared
    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return TrendLine(
        slope=round(slope, 6),
        intercept=round(intercept, 6),
        r_squared=round(r_squared, 4),
    )


@router.get("/correlation", response_model=CorrelationResponse)
async def get_correlation(
    x_metric: str = Query(..., description="X axis metric name"),
    y_metric: str = Query(..., description="Y axis metric name"),
    telescope: str | None = Query(None),
    camera: str | None = Query(None),
    granularity: str = Query("frame", regex="^(frame|session)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if x_metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown x_metric: {x_metric}")
    if y_metric not in METRIC_MAP:
        raise HTTPException(400, f"Unknown y_metric: {y_metric}")

    x_col = METRIC_MAP[x_metric]
    y_col = METRIC_MAP[y_metric]

    q = (
        select(
            x_col.label("x_val"),
            y_col.label("y_val"),
            cast(Image.capture_date, Date).label("night"),
            Image.resolved_target_id,
        )
        .where(Image.image_type == "LIGHT")
        .where(x_col.is_not(None))
        .where(y_col.is_not(None))
        .where(Image.capture_date.is_not(None))
    )

    # Equipment filtering with alias expansion
    if telescope or camera:
        alias_maps = await load_alias_maps(session)
    if telescope:
        variants = expand_canonical(telescope, alias_maps.get("telescopes", {}))
        q = q.where(Image.telescope.in_(variants))
    if camera:
        variants = expand_canonical(camera, alias_maps.get("cameras", {}))
        q = q.where(Image.camera.in_(variants))

    if date_from:
        q = q.where(Image.capture_date >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.where(Image.capture_date <= datetime.fromisoformat(date_to + "T23:59:59"))

    rows = (await session.execute(q)).all()

    if granularity == "frame":
        # Resolve target names in batch
        target_ids = {r.resolved_target_id for r in rows if r.resolved_target_id}
        target_names = {}
        if target_ids:
            tq = select(Target.id, Target.primary_name).where(Target.id.in_(target_ids))
            target_names = {t.id: t.primary_name for t in (await session.execute(tq)).all()}

        points = [
            CorrelationPoint(
                x=float(r.x_val),
                y=float(r.y_val),
                date=str(r.night),
                target_name=target_names.get(r.resolved_target_id),
            )
            for r in rows
        ]
    else:
        # Session medians: group by (night, target_id)
        session_groups: dict[tuple, dict] = defaultdict(lambda: {"xs": [], "ys": [], "target_id": None})
        for r in rows:
            key = (str(r.night), r.resolved_target_id)
            session_groups[key]["xs"].append(float(r.x_val))
            session_groups[key]["ys"].append(float(r.y_val))
            session_groups[key]["target_id"] = r.resolved_target_id

        target_ids = {g["target_id"] for g in session_groups.values() if g["target_id"]}
        target_names = {}
        if target_ids:
            tq = select(Target.id, Target.primary_name).where(Target.id.in_(target_ids))
            target_names = {t.id: t.primary_name for t in (await session.execute(tq)).all()}

        points = []
        for (night, _), g in session_groups.items():
            points.append(CorrelationPoint(
                x=statistics.median(g["xs"]),
                y=statistics.median(g["ys"]),
                date=night,
                target_name=target_names.get(g["target_id"]),
            ))

    trend = _compute_trend(points)

    return CorrelationResponse(
        points=points,
        trend=trend,
        x_metric=x_metric,
        y_metric=y_metric,
        granularity=granularity,
    )
```

- [ ] **Step 2: Register the router**

In `backend/app/api/router.py`, add after the existing imports:

```python
from .analysis import router as analysis_router
```

And after the last `include_router` call:

```python
api_router.include_router(analysis_router)
```

- [ ] **Step 3: Test the endpoint**

```bash
curl -s "http://localhost:8000/api/analysis/correlation?x_metric=humidity&y_metric=hfr&granularity=frame" | python -m json.tool | head -30
```

Expected: JSON with `points` array and `trend` object (may need auth).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/analysis.py backend/app/api/router.py
git commit -m "feat: add correlation analysis endpoint"
```

---

### Task 3: Frontend — Analysis Types and API Method

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add TypeScript types**

In `frontend/src/types/index.ts`, add:

```typescript
// === Correlation Analysis ===

export interface CorrelationPoint {
  x: number;
  y: number;
  date: string;
  target_name: string | null;
}

export interface TrendLine {
  slope: number;
  intercept: number;
  r_squared: number;
}

export interface CorrelationResponse {
  points: CorrelationPoint[];
  trend: TrendLine | null;
  x_metric: string;
  y_metric: string;
  granularity: string;
}
```

- [ ] **Step 2: Add API method**

In `frontend/src/api/client.ts`, add to the `api` object:

```typescript
  getCorrelation: (params: {
    x_metric: string;
    y_metric: string;
    telescope?: string;
    camera?: string;
    granularity?: "frame" | "session";
    date_from?: string;
    date_to?: string;
  }) => {
    const qs = new URLSearchParams();
    qs.set("x_metric", params.x_metric);
    qs.set("y_metric", params.y_metric);
    if (params.telescope) qs.set("telescope", params.telescope);
    if (params.camera) qs.set("camera", params.camera);
    if (params.granularity) qs.set("granularity", params.granularity);
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    return fetchJson<import("../types").CorrelationResponse>(`/analysis/correlation?${qs}`);
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: add correlation analysis API client and types"
```

---

### Task 4: Frontend — CorrelationChart Component

**Files:**
- Create: `frontend/src/components/analysis/CorrelationChart.tsx`

- [ ] **Step 1: Create the scatter chart component**

Create directory and file `frontend/src/components/analysis/CorrelationChart.tsx`:

```typescript
import { Component, createEffect, onCleanup } from "solid-js";
import {
  Chart,
  ScatterController,
  LinearScale,
  PointElement,
  Tooltip,
  LineElement,
} from "chart.js";
import type { CorrelationResponse } from "../../types";

Chart.register(ScatterController, LinearScale, PointElement, Tooltip, LineElement);

const METRIC_LABELS: Record<string, string> = {
  humidity: "Humidity (%)",
  wind_speed: "Wind Speed",
  ambient_temp: "Ambient Temp (°C)",
  dew_point: "Dew Point (°C)",
  pressure: "Pressure (hPa)",
  cloud_cover: "Cloud Cover (%)",
  sky_quality: "Sky Quality (SQM)",
  focuser_temp: "Focuser Temp (°C)",
  airmass: "Airmass",
  sensor_temp: "Sensor Temp (°C)",
  hfr: "HFR (px)",
  fwhm: "FWHM",
  eccentricity: "Eccentricity",
  guiding_rms: "Guiding RMS (\")",
  guiding_rms_ra: "Guiding RA RMS (\")",
  guiding_rms_dec: "Guiding DEC RMS (\")",
  detected_stars: "Detected Stars",
  adu_mean: "ADU Mean",
  adu_median: "ADU Median",
  adu_stdev: "ADU StDev",
};

interface Props {
  data: CorrelationResponse | undefined;
  loading: boolean;
  title?: string;
}

const CorrelationChart: Component<Props> = (props) => {
  let canvasRef: HTMLCanvasElement | undefined;
  let chartInstance: Chart | undefined;

  const renderChart = () => {
    if (!canvasRef || !props.data) return;
    chartInstance?.destroy();

    const { points, trend, x_metric, y_metric, granularity } = props.data;
    const isSession = granularity === "session";

    const datasets: any[] = [
      {
        label: "Data",
        data: points.map((p) => ({ x: p.x, y: p.y })),
        backgroundColor: isSession
          ? "rgba(99, 132, 255, 0.8)"
          : "rgba(99, 132, 255, 0.3)",
        pointRadius: isSession ? 5 : 3,
        pointHoverRadius: isSession ? 7 : 5,
      },
    ];

    // Add trend line
    if (trend && points.length >= 3) {
      const xs = points.map((p) => p.x).sort((a, b) => a - b);
      const xMin = xs[0];
      const xMax = xs[xs.length - 1];
      datasets.push({
        label: `Trend (R²=${trend.r_squared.toFixed(2)})`,
        data: [
          { x: xMin, y: trend.slope * xMin + trend.intercept },
          { x: xMax, y: trend.slope * xMax + trend.intercept },
        ],
        type: "line" as const,
        borderColor: "rgba(255, 99, 132, 0.7)",
        borderWidth: 2,
        pointRadius: 0,
        fill: false,
      });
    }

    chartInstance = new Chart(canvasRef, {
      type: "scatter",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            title: { display: true, text: METRIC_LABELS[x_metric] || x_metric, color: "rgb(var(--text-secondary))" },
            ticks: { color: "rgb(var(--text-secondary))" },
            grid: { color: "rgba(var(--text-secondary), 0.1)" },
          },
          y: {
            title: { display: true, text: METRIC_LABELS[y_metric] || y_metric, color: "rgb(var(--text-secondary))" },
            ticks: { color: "rgb(var(--text-secondary))" },
            grid: { color: "rgba(var(--text-secondary), 0.1)" },
          },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const pt = points[ctx.dataIndex];
                if (!pt) return `(${ctx.parsed.x}, ${ctx.parsed.y})`;
                return `${pt.target_name || "Unknown"} (${pt.date}): ${ctx.parsed.x.toFixed(1)}, ${ctx.parsed.y.toFixed(2)}`;
              },
            },
          },
        },
      },
    });
  };

  createEffect(() => {
    // Reactive dependencies
    const _ = props.data;
    renderChart();
  });

  onCleanup(() => chartInstance?.destroy());

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
      {props.title && <h3 class="text-sm font-medium text-theme-text-primary mb-2">{props.title}</h3>}
      <div class="relative" style={{ height: "300px" }}>
        {props.loading && (
          <div class="absolute inset-0 flex items-center justify-center text-xs text-theme-text-secondary">
            Loading...
          </div>
        )}
        <canvas ref={canvasRef} />
      </div>
      {props.data?.trend && (
        <div class="text-xs text-theme-text-secondary mt-1">
          R² = {props.data.trend.r_squared.toFixed(3)} &middot; {props.data.points.length} points
        </div>
      )}
    </div>
  );
};

export default CorrelationChart;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/analysis/CorrelationChart.tsx
git commit -m "feat: add CorrelationChart scatter plot component"
```

---

### Task 5: Frontend — Analysis Page

**Files:**
- Create: `frontend/src/pages/AnalysisPage.tsx`
- Modify: `frontend/src/index.tsx` (add route)
- Modify: `frontend/src/components/NavBar.tsx` (add nav link)

- [ ] **Step 1: Create the Analysis page**

Create `frontend/src/pages/AnalysisPage.tsx`:

```typescript
import { Component, Show, createSignal, createResource } from "solid-js";
import { api } from "../api/client";
import CorrelationChart from "../components/analysis/CorrelationChart";
import type { CorrelationResponse, EquipmentList } from "../types";

const PREBUILT_CHARTS = [
  { x: "humidity", y: "hfr", title: "HFR vs Humidity — When is it too humid to image?" },
  { x: "wind_speed", y: "hfr", title: "HFR vs Wind Speed — What's your site's wind tolerance?" },
  { x: "wind_speed", y: "guiding_rms", title: "Guiding RMS vs Wind Speed — When does wind wreck guiding?" },
];

const X_OPTIONS = [
  { value: "humidity", label: "Humidity" },
  { value: "wind_speed", label: "Wind Speed" },
  { value: "ambient_temp", label: "Ambient Temp" },
  { value: "dew_point", label: "Dew Point" },
  { value: "pressure", label: "Pressure" },
  { value: "cloud_cover", label: "Cloud Cover" },
  { value: "sky_quality", label: "Sky Quality" },
  { value: "focuser_temp", label: "Focuser Temp" },
  { value: "airmass", label: "Airmass" },
  { value: "sensor_temp", label: "Sensor Temp" },
];

const Y_OPTIONS = [
  { value: "hfr", label: "HFR" },
  { value: "fwhm", label: "FWHM" },
  { value: "eccentricity", label: "Eccentricity" },
  { value: "guiding_rms", label: "Guiding RMS" },
  { value: "guiding_rms_ra", label: "Guiding RA RMS" },
  { value: "guiding_rms_dec", label: "Guiding DEC RMS" },
  { value: "detected_stars", label: "Detected Stars" },
  { value: "adu_mean", label: "ADU Mean" },
  { value: "adu_median", label: "ADU Median" },
  { value: "adu_stdev", label: "ADU StDev" },
];

const AnalysisPage: Component = () => {
  const [equipment] = createResource(() => api.getEquipment());
  const [telescope, setTelescope] = createSignal<string | undefined>(undefined);
  const [camera, setCamera] = createSignal<string | undefined>(undefined);
  const [granularity, setGranularity] = createSignal<"frame" | "session">("frame");

  // Pre-built chart data
  const fetchChart = (x: string, y: string) => {
    const tel = telescope();
    const cam = camera();
    const gran = granularity();
    return api.getCorrelation({
      x_metric: x,
      y_metric: y,
      telescope: tel,
      camera: cam,
      granularity: gran,
    });
  };

  const chartKey = () => `${telescope()}-${camera()}-${granularity()}`;

  const [chart1] = createResource(chartKey, () => fetchChart("humidity", "hfr"));
  const [chart2] = createResource(chartKey, () => fetchChart("wind_speed", "hfr"));
  const [chart3] = createResource(chartKey, () => fetchChart("wind_speed", "guiding_rms"));

  // Custom explorer
  const [customX, setCustomX] = createSignal("humidity");
  const [customY, setCustomY] = createSignal("hfr");
  const customKey = () => `${chartKey()}-${customX()}-${customY()}`;
  const [customData] = createResource(customKey, () =>
    fetchChart(customX(), customY())
  );

  // Build equipment combo list
  const combos = () => {
    const eq = equipment();
    if (!eq) return [];
    const result: { telescope: string; camera: string; label: string }[] = [];
    for (const t of eq.telescopes) {
      for (const c of eq.cameras) {
        result.push({ telescope: t.name, camera: c.name, label: `${t.name} + ${c.name}` });
      }
    }
    return result;
  };

  const selectClass = "text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 text-theme-text-primary";
  const toggleClass = (active: boolean) =>
    `text-xs px-2.5 py-1 rounded-[var(--radius-sm)] transition-colors ${
      active
        ? "bg-theme-elevated text-theme-text-primary font-medium"
        : "text-theme-text-secondary hover:text-theme-text-primary"
    }`;

  return (
    <div class="p-4 space-y-4 max-w-7xl mx-auto">
      {/* Controls */}
      <div class="flex flex-wrap items-center gap-3">
        <select
          class={selectClass}
          onChange={(e) => {
            const val = e.currentTarget.value;
            if (!val) {
              setTelescope(undefined);
              setCamera(undefined);
            } else {
              const [t, c] = val.split("|||");
              setTelescope(t);
              setCamera(c);
            }
          }}
        >
          <option value="">All equipment</option>
          {combos().map((c) => (
            <option value={`${c.telescope}|||${c.camera}`}>{c.label}</option>
          ))}
        </select>

        <div class="flex items-center gap-1">
          <button class={toggleClass(granularity() === "frame")} onClick={() => setGranularity("frame")}>
            Per Frame
          </button>
          <button class={toggleClass(granularity() === "session")} onClick={() => setGranularity("session")}>
            Per Session
          </button>
        </div>
      </div>

      {/* Pre-built charts */}
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <CorrelationChart data={chart1()} loading={chart1.loading} title={PREBUILT_CHARTS[0].title} />
        <CorrelationChart data={chart2()} loading={chart2.loading} title={PREBUILT_CHARTS[1].title} />
        <CorrelationChart data={chart3()} loading={chart3.loading} title={PREBUILT_CHARTS[2].title} />
      </div>

      {/* Custom explorer */}
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
        <h3 class="text-sm font-medium text-theme-text-primary mb-3">Custom Correlation Explorer</h3>
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <label class="text-xs text-theme-text-secondary">X Axis:</label>
          <select class={selectClass} value={customX()} onChange={(e) => setCustomX(e.currentTarget.value)}>
            {X_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
          <label class="text-xs text-theme-text-secondary">Y Axis:</label>
          <select class={selectClass} value={customY()} onChange={(e) => setCustomY(e.currentTarget.value)}>
            {Y_OPTIONS.map((o) => <option value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ height: "400px" }} class="relative">
          <CorrelationChart data={customData()} loading={customData.loading} />
        </div>
      </div>
    </div>
  );
};

export default AnalysisPage;
```

- [ ] **Step 2: Add route**

In `frontend/src/index.tsx`, add import:

```typescript
import AnalysisPage from "./pages/AnalysisPage";
```

Add route before the `</Router>` close, after the statistics route:

```typescript
          <Route path="/analysis" component={Protected(AnalysisPage)} />
```

- [ ] **Step 3: Add nav link (desktop)**

In `frontend/src/components/NavBar.tsx`, add after the Statistics `<A>` block (after line 38) in the desktop nav:

```typescript
        <A
          href="/analysis"
          class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors"
          activeClass="text-theme-text-primary font-medium bg-theme-elevated rounded-[var(--radius-sm)] px-2.5 py-1"
        >
          Analysis
        </A>
```

- [ ] **Step 4: Add nav link (mobile)**

In the mobile nav section of `NavBar.tsx`, add after the Statistics `<A>` block (after line 128):

```typescript
            <A
              href="/analysis"
              class="text-sm text-theme-text-secondary hover:text-theme-text-primary transition-colors py-2 px-3 rounded-[var(--radius-sm)]"
              activeClass="text-theme-text-primary font-medium bg-theme-elevated"
              onClick={() => setMenuOpen(false)}
            >
              Analysis
            </A>
```

- [ ] **Step 5: Verify in browser**

Navigate to `/analysis`. Verify:
- Equipment combo dropdown populates
- Frame/Session toggle works
- Three pre-built charts render scatter plots
- Custom explorer dropdowns change the chart
- Trend lines appear when data exists

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AnalysisPage.tsx frontend/src/index.tsx frontend/src/components/NavBar.tsx
git commit -m "feat: add Analysis page with correlation charts and explorer"
```
