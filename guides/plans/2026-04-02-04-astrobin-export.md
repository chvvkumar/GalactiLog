# AstroBin Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export target acquisition data as AstroBin-compatible CSV and copyable text, with selectable sessions and configurable filter ID mappings.

**Architecture:** New backend export endpoint returns per-date-per-filter aggregated data with calibration frame counts. Frontend modal on Target Detail page with session checkboxes, copy-to-clipboard, and CSV download. AstroBin filter ID mapping stored in UserSettings.general.

**Tech Stack:** FastAPI + SQLAlchemy (backend), SolidJS (frontend)

---

### Task 1: Backend — Export Schemas

**Files:**
- Create: `backend/app/schemas/export.py`

- [ ] **Step 1: Create export schemas**

Create `backend/app/schemas/export.py`:

```python
from pydantic import BaseModel


class ExportFilterRow(BaseModel):
    date: str
    filter_name: str
    astrobin_filter_id: int | None = None
    frames: int
    exposure: float
    total_seconds: float
    gain: int | None = None
    sensor_temp: int | None = None
    fwhm: float | None = None
    sky_quality: float | None = None
    ambient_temp: float | None = None


class ExportEquipment(BaseModel):
    telescope: str | None
    camera: str | None


class ExportCalibration(BaseModel):
    darks: int
    flats: int
    bias: int


class ExportResponse(BaseModel):
    target_name: str
    catalog_id: str | None
    equipment: list[ExportEquipment]
    dates: list[str]
    rows: list[ExportFilterRow]
    calibration: ExportCalibration
    total_integration_seconds: float
    bortle: int | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/export.py
git commit -m "feat: add AstroBin export schemas"
```

---

### Task 2: Backend — Export Endpoint

**Files:**
- Modify: `backend/app/api/targets.py`

- [ ] **Step 1: Add the export endpoint**

In `backend/app/api/targets.py`, add imports:

```python
from app.schemas.export import ExportResponse, ExportFilterRow, ExportEquipment, ExportCalibration
```

Add the endpoint (place it before the dynamic `/{target_id:path}` routes so it doesn't get shadowed):

```python
@router.get("/{target_id}/export", response_model=ExportResponse)
async def export_target(
    target_id: uuid.UUID,
    sessions: str | None = Query(None, description="Comma-separated dates to include"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(404, "Target not found")

    # Get settings for AstroBin filter IDs and bortle
    from app.models import UserSettings, SETTINGS_ROW_ID
    settings_row = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings_row.general if settings_row else {}
    astrobin_filter_ids = general.get("astrobin_filter_ids", {})
    bortle = general.get("astrobin_bortle")

    # Fetch LIGHT frames for this target
    q = (
        select(Image)
        .where(Image.resolved_target_id == target_id)
        .where(Image.image_type == "LIGHT")
        .where(Image.capture_date.is_not(None))
        .order_by(Image.capture_date)
    )
    images = (await session.execute(q)).scalars().all()

    # Filter by selected sessions
    selected_dates = None
    if sessions:
        selected_dates = set(sessions.split(","))

    # Group by (date, filter)
    from collections import defaultdict
    import statistics as stats_mod
    groups: dict[tuple[str, str], list] = defaultdict(list)
    equip_set: set[tuple] = set()

    for img in images:
        date_key = img.capture_date.strftime("%Y-%m-%d")
        if selected_dates and date_key not in selected_dates:
            continue
        filter_name = img.filter_used or "Unknown"
        groups[(date_key, filter_name)].append(img)
        equip_set.add((img.telescope, img.camera))

    rows = []
    all_dates = set()
    total_seconds = 0.0

    for (date_key, filter_name), imgs in sorted(groups.items()):
        all_dates.add(date_key)
        frame_count = len(imgs)
        exposure = imgs[0].exposure_time or 0
        integration = sum(i.exposure_time or 0 for i in imgs)
        total_seconds += integration

        gains = [i.camera_gain for i in imgs if i.camera_gain is not None]
        temps = [i.sensor_temp for i in imgs if i.sensor_temp is not None]
        fwhms = [i.fwhm for i in imgs if i.fwhm is not None]
        sqms = [i.sky_quality for i in imgs if i.sky_quality is not None]
        amb_temps = [i.ambient_temp for i in imgs if i.ambient_temp is not None]

        # Normalize filter name for AstroBin ID lookup
        from app.services.normalization import load_alias_maps, normalize_filter
        alias_maps = await load_alias_maps(session)
        canonical_filter = normalize_filter(filter_name, alias_maps.get("filters", {}))
        ab_id = astrobin_filter_ids.get(canonical_filter) or astrobin_filter_ids.get(filter_name)

        rows.append(ExportFilterRow(
            date=date_key,
            filter_name=filter_name,
            astrobin_filter_id=ab_id,
            frames=frame_count,
            exposure=round(exposure, 4),
            total_seconds=round(integration, 1),
            gain=max(set(gains), key=gains.count) if gains else None,  # mode
            sensor_temp=round(stats_mod.median(temps)) if temps else None,
            fwhm=round(stats_mod.median(fwhms), 2) if fwhms else None,
            sky_quality=round(stats_mod.median(sqms), 2) if sqms else None,
            ambient_temp=round(stats_mod.median(amb_temps), 2) if amb_temps else None,
        ))

    # Calibration frame counts
    # Darks: match camera + gain + sensor_temp (±2°C) + exposure
    camera_names = {e[1] for e in equip_set if e[1]}
    gains_used = {r.gain for r in rows if r.gain is not None}
    temps_used = {r.sensor_temp for r in rows if r.sensor_temp is not None}
    exposures_used = {r.exposure for r in rows}

    dark_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "DARK")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    dark_count = (await session.execute(dark_q)).scalar() or 0

    flat_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "FLAT")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    flat_count = (await session.execute(flat_q)).scalar() or 0

    bias_q = (
        select(func.count(Image.id))
        .where(Image.image_type == "BIAS")
        .where(Image.camera.in_(camera_names) if camera_names else True)
    )
    bias_count = (await session.execute(bias_q)).scalar() or 0

    return ExportResponse(
        target_name=target.primary_name,
        catalog_id=target.catalog_id,
        equipment=[ExportEquipment(telescope=t, camera=c) for t, c in equip_set],
        dates=sorted(all_dates),
        rows=rows,
        calibration=ExportCalibration(darks=dark_count, flats=flat_count, bias=bias_count),
        total_integration_seconds=total_seconds,
        bortle=bortle,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/targets.py
git commit -m "feat: add AstroBin export endpoint"
```

---

### Task 3: Backend — AstroBin Settings Fields

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/api/settings.py`

- [ ] **Step 1: Add AstroBin fields to GeneralSettings schema**

In `backend/app/schemas/settings.py`, add to `GeneralSettings`:

```python
    astrobin_filter_ids: dict[str, int] = {}
    astrobin_bortle: int | None = None
```

No migration needed — these are stored in the existing `general` JSONB column.

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/settings.py
git commit -m "feat: add AstroBin settings fields to GeneralSettings"
```

---

### Task 4: Frontend — Export Types and API

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add export types**

In `frontend/src/types/index.ts`, add:

```typescript
// === AstroBin Export ===

export interface ExportFilterRow {
  date: string;
  filter_name: string;
  astrobin_filter_id: number | null;
  frames: number;
  exposure: number;
  total_seconds: number;
  gain: number | null;
  sensor_temp: number | null;
  fwhm: number | null;
  sky_quality: number | null;
  ambient_temp: number | null;
}

export interface ExportEquipment {
  telescope: string | null;
  camera: string | null;
}

export interface ExportCalibration {
  darks: number;
  flats: number;
  bias: number;
}

export interface ExportResponse {
  target_name: string;
  catalog_id: string | null;
  equipment: ExportEquipment[];
  dates: string[];
  rows: ExportFilterRow[];
  calibration: ExportCalibration;
  total_integration_seconds: number;
  bortle: number | null;
}
```

- [ ] **Step 2: Add API method**

In `frontend/src/api/client.ts`, add to the `api` object:

```typescript
  getExport: (targetId: string, sessions?: string[]) => {
    const params = sessions?.length ? `?sessions=${sessions.join(",")}` : "";
    return fetchJson<import("../types").ExportResponse>(
      `/targets/${encodeURIComponent(targetId)}/export${params}`
    );
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: add AstroBin export API client and types"
```

---

### Task 5: Frontend — Export Modal Component

**Files:**
- Create: `frontend/src/components/ExportModal.tsx`

- [ ] **Step 1: Create the export modal**

Create `frontend/src/components/ExportModal.tsx`:

```typescript
import { Component, For, Show, createSignal, createResource, createMemo } from "solid-js";
import { api } from "../api/client";
import type { ExportResponse, SessionOverview } from "../types";

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  return hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
}

function generateTextExport(data: ExportResponse): string {
  const lines: string[] = [];
  const name = data.catalog_id ? `${data.target_name} (${data.catalog_id})` : data.target_name;
  lines.push(name);

  const equipStr = data.equipment.map((e) => `${e.telescope || "?"} + ${e.camera || "?"}`).join(", ");
  lines.push(`Equipment: ${equipStr}`);
  lines.push(`Dates: ${data.dates.join(", ")}`);
  lines.push("");

  // Aggregate by filter across all dates
  const byFilter = new Map<string, { frames: number; exposure: number; total: number; gain: number | null; temp: number | null }>();
  for (const row of data.rows) {
    const existing = byFilter.get(row.filter_name);
    if (existing) {
      existing.frames += row.frames;
      existing.total += row.total_seconds;
    } else {
      byFilter.set(row.filter_name, {
        frames: row.frames,
        exposure: row.exposure,
        total: row.total_seconds,
        gain: row.gain,
        temp: row.sensor_temp,
      });
    }
  }

  for (const [filter, info] of byFilter) {
    let line = `${filter}: ${info.frames} x ${info.exposure}s (${formatHours(info.total)})`;
    if (info.gain != null) line += ` | Gain ${info.gain}`;
    if (info.temp != null) line += ` | ${info.temp}°C`;
    lines.push(line);
  }

  lines.push("");
  lines.push(`Total integration: ${formatHours(data.total_integration_seconds)}`);
  return lines.join("\n");
}

function generateCsvExport(data: ExportResponse): string {
  const headers = ["date", "number", "duration", "filter", "gain", "sensorCooling", "meanFwhm", "meanSqm", "temperature", "darks", "flats", "bias", "bortle"];
  const lines = [headers.join(",")];

  for (const row of data.rows) {
    const vals = [
      row.date,
      row.frames,
      row.exposure,
      row.astrobin_filter_id ?? "",
      row.gain ?? "",
      row.sensor_temp ?? "",
      row.fwhm ?? "",
      row.sky_quality ?? "",
      row.ambient_temp ?? "",
      data.calibration.darks,
      data.calibration.flats,
      data.calibration.bias,
      data.bortle ?? "",
    ];
    lines.push(vals.join(","));
  }

  return lines.join("\n");
}

interface Props {
  targetId: string;
  targetName: string;
  sessions: SessionOverview[];
  onClose: () => void;
}

const ExportModal: Component<Props> = (props) => {
  const [selectedDates, setSelectedDates] = createSignal<Set<string>>(
    new Set(props.sessions.map((s) => s.session_date))
  );
  const [copied, setCopied] = createSignal(false);

  const sessionList = () => selectedDates().size > 0 ? [...selectedDates()] : undefined;
  const [exportData] = createResource(
    () => sessionList()?.join(",") ?? "all",
    () => api.getExport(props.targetId, sessionList()),
  );

  const toggleDate = (date: string) => {
    const s = new Set(selectedDates());
    if (s.has(date)) s.delete(date);
    else s.add(date);
    setSelectedDates(s);
  };

  const toggleAll = () => {
    if (selectedDates().size === props.sessions.length) {
      setSelectedDates(new Set());
    } else {
      setSelectedDates(new Set(props.sessions.map((s) => s.session_date)));
    }
  };

  const copyText = async () => {
    const data = exportData();
    if (!data) return;
    await navigator.clipboard.writeText(generateTextExport(data));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadCsv = () => {
    const data = exportData();
    if (!data) return;
    const csv = generateCsvExport(data);
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${props.targetName.replace(/[^a-zA-Z0-9]/g, "_")}_acquisition.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={props.onClose}>
      <div
        class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-lg)] max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="p-4 border-b border-theme-border flex items-center justify-between">
          <h2 class="text-sm font-medium text-theme-text-primary">Export — {props.targetName}</h2>
          <button class="text-theme-text-secondary hover:text-theme-text-primary" onClick={props.onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
        </div>

        <div class="p-4 space-y-3">
          {/* Session selection */}
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-medium text-theme-text-secondary uppercase tracking-wide">Sessions</span>
              <button class="text-xs text-theme-accent hover:underline" onClick={toggleAll}>
                {selectedDates().size === props.sessions.length ? "Deselect all" : "Select all"}
              </button>
            </div>
            <div class="space-y-1 max-h-40 overflow-y-auto">
              <For each={props.sessions}>
                {(s) => (
                  <label class="flex items-center gap-2 text-xs text-theme-text-primary cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedDates().has(s.session_date)}
                      onChange={() => toggleDate(s.session_date)}
                    />
                    {s.session_date} — {formatHours(s.integration_seconds)} ({s.frame_count} frames)
                  </label>
                )}
              </For>
            </div>
          </div>

          {/* Preview */}
          <Show when={exportData()}>
            {(data) => (
              <div class="bg-theme-elevated rounded p-3 text-xs text-theme-text-primary font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                {generateTextExport(data())}
              </div>
            )}
          </Show>

          <Show when={exportData.loading}>
            <div class="text-xs text-theme-text-secondary text-center py-4">Loading...</div>
          </Show>
        </div>

        <div class="p-4 border-t border-theme-border flex gap-2 justify-end">
          <button
            class="text-xs px-3 py-1.5 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary disabled:opacity-50"
            disabled={!exportData() || selectedDates().size === 0}
            onClick={copyText}
          >
            {copied() ? "Copied!" : "Copy to Clipboard"}
          </button>
          <button
            class="text-xs px-3 py-1.5 bg-theme-accent text-white rounded hover:opacity-90 transition-opacity disabled:opacity-50"
            disabled={!exportData() || selectedDates().size === 0}
            onClick={downloadCsv}
          >
            Download CSV
          </button>
        </div>
      </div>
    </div>
  );
};

export default ExportModal;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ExportModal.tsx
git commit -m "feat: add AstroBin export modal component"
```

---

### Task 6: Frontend — Wire Export Button on Target Detail Page

**Files:**
- Modify: `frontend/src/pages/TargetDetailPage.tsx`

- [ ] **Step 1: Add export button and modal**

In `TargetDetailPage.tsx`, add import:

```typescript
import ExportModal from "../components/ExportModal";
```

Add state:

```typescript
  const [showExport, setShowExport] = createSignal(false);
```

Add the Export button next to the target name in the hero section (find the `<h2>` with the target name):

```typescript
  <button
    class="text-xs px-2.5 py-1 bg-theme-elevated border border-theme-border rounded hover:bg-theme-surface transition-colors text-theme-text-primary"
    onClick={() => setShowExport(true)}
  >
    Export
  </button>
```

Add the modal at the bottom of the component JSX (before the final closing `</div>`):

```typescript
  <Show when={showExport() && targetDetail()}>
    <ExportModal
      targetId={params.targetId}
      targetName={targetDetail()!.primary_name}
      sessions={targetDetail()!.sessions}
      onClose={() => setShowExport(false)}
    />
  </Show>
```

- [ ] **Step 2: Verify in browser**

Navigate to a target detail page. Verify:
- Export button appears near the target name
- Clicking opens modal with session checkboxes
- Text preview shows formatted acquisition summary
- Copy to Clipboard works
- Download CSV produces a file with correct AstroBin headers
- Deselecting sessions updates the preview

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TargetDetailPage.tsx
git commit -m "feat: wire export button and modal on target detail page"
```

---

### Task 7: Frontend — AstroBin Settings Tab

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx` (or the appropriate settings tab component)

- [ ] **Step 1: Add AstroBin Integration section**

In the Settings page, add a new section (in the General tab or as a new tab) for AstroBin configuration. This should show:

- A table of discovered filter names (from the existing filter settings) with a numeric input field for each AstroBin equipment database ID
- A Bortle class input (1-9)
- Help text explaining where to find AstroBin filter IDs

The exact component structure depends on how the Settings page tabs are organized. Add after existing general settings fields:

```typescript
  {/* AstroBin Integration */}
  <div class="space-y-3">
    <h3 class="text-sm font-medium text-theme-text-primary">AstroBin Integration</h3>
    <p class="text-xs text-theme-text-secondary">
      Map your filters to AstroBin equipment database IDs for CSV import.
      Find IDs in the URL when viewing a filter on AstroBin (e.g., astrobin.com/equipment/filter/1234).
    </p>
    {/* Filter ID mapping table */}
    <div class="space-y-2">
      <For each={Object.keys(settings().filters || {})}>
        {(filterName) => (
          <div class="flex items-center gap-3">
            <span class="text-xs text-theme-text-primary w-24">{filterName}</span>
            <input
              type="number"
              class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 w-32 text-theme-text-primary"
              placeholder="AstroBin ID"
              value={settings().general.astrobin_filter_ids?.[filterName] ?? ""}
              onChange={(e) => {
                const val = e.currentTarget.value ? Number(e.currentTarget.value) : undefined;
                const ids = { ...settings().general.astrobin_filter_ids };
                if (val) ids[filterName] = val;
                else delete ids[filterName];
                saveGeneral({ ...settings().general, astrobin_filter_ids: ids });
              }}
            />
          </div>
        )}
      </For>
    </div>
    <div class="flex items-center gap-3">
      <span class="text-xs text-theme-text-primary w-24">Bortle Class</span>
      <input
        type="number"
        min="1"
        max="9"
        class="text-xs bg-theme-elevated border border-theme-border rounded px-2 py-1 w-20 text-theme-text-primary"
        placeholder="1-9"
        value={settings().general.astrobin_bortle ?? ""}
        onChange={(e) => {
          const val = e.currentTarget.value ? Number(e.currentTarget.value) : undefined;
          saveGeneral({ ...settings().general, astrobin_bortle: val });
        }}
      />
    </div>
  </div>
```

Adjust the exact integration point based on how the settings page tabs are structured. The `saveGeneral` function should already exist from the general settings tab — it calls `api.updateGeneral()`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add AstroBin filter ID and bortle settings"
```
