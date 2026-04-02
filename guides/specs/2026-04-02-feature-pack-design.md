# Feature Pack: Calendar Heatmap, Conditions Analysis, Session Notes, AstroBin Export, Mosaic Tracking

Date: 2026-04-02

## Overview

Five features that evolve GalactiLog from a data catalog into a tool for reflecting on and managing one's astrophotography journey. Ordered by implementation independence — features 1-3 have no dependencies on each other, feature 4 benefits from calibration awareness in feature 3's model work, and feature 5 is fully standalone.

---

## Feature 1: Imaging Calendar Heatmap

### Location

Stats page. Toggle switch replacing the current timeline view — user chooses between "Timeline" (existing bar chart) and "Calendar" (heatmap). Persisted in `UserSettings.graph` so the preference sticks.

### Layout

GitHub-contributions-style grid:
- Rows = days of the week (Mon–Sun)
- Columns = weeks
- Each cell = one night
- Color intensity = total integration hours that night
- Empty/gray cells for nights with no imaging

Default view: trailing 12 months. Year selector dropdown to view prior years.

### Color Scale

Single-hue gradient, dark-theme friendly (e.g., deep blue → bright cyan). Legend showing hour ranges. Scale is relative to the user's own data — max color = their most productive night.

### Hover Tooltip

- Date
- Integration hours
- Number of targets imaged
- Number of frames

### Backend

New endpoint: `GET /api/stats/calendar?year=2025`

Response:
```json
[
  {"date": "2025-06-15", "integration_seconds": 14400, "target_count": 2, "frame_count": 48},
  ...
]
```

Query groups images by astronomical night (date derived from `capture_date`, accounting for sessions spanning midnight — same logic used in existing session grouping). Lightweight aggregation, no new models.

### Frontend

New `ImagingCalendar` component in `frontend/src/components/stats/`. Toggle state stored in graph settings. Reuses the existing `ImagingTimeline` container — the toggle swaps which component renders.

---

## Feature 2: Conditions Correlation Analysis

### Location

New "Analysis" page added to the navigation bar, alongside Statistics.

### Page Layout (top to bottom)

**1. Equipment combo selector** — dropdown at the top of the page for telescope + camera combination. All charts below are scoped to the selected combo. Same combo list as the existing equipment performance breakdown on Stats.

**2. Frame/Session toggle** — switch between per-frame data points and per-session medians. Applies to all charts on the page.

**3. Three pre-built insight charts:**

| Chart | X Axis | Y Axis | Insight |
|-------|--------|--------|---------|
| 1 | Humidity (%) | HFR (px) | "When is it too humid to image?" |
| 2 | Wind Speed | HFR (px) | "What's my site's wind tolerance?" |
| 3 | Wind Speed | Guiding RMS (arcsec) | "When does wind wreck my guiding?" |

Each chart: scatter plot with trend line overlay.

**4. Custom correlation explorer** — two dropdowns below the pre-built charts:

X axis options (environmental/equipment):
- Humidity, wind speed, ambient temp, dew point, pressure, cloud cover, sky quality, focuser temp, airmass, sensor temp

Y axis options (quality):
- HFR, FWHM, eccentricity, guiding RMS (total/RA/DEC), detected stars, ADU mean, ADU median, ADU stdev

Same frame/session toggle and equipment combo scope apply.

### Scatter Plot Behavior

**Per-frame mode:** Individual data points with reduced opacity (0.3–0.5) to handle density. Trend line overlay (linear regression). Potentially thousands of points.

**Per-session mode:** One dot per session, using median of both X and Y metrics for that session. Larger dots, full opacity. Trend line overlay.

### Backend

New endpoint: `GET /api/analysis/correlation`

Query parameters:
- `x_metric` (string) — field name for X axis
- `y_metric` (string) — field name for Y axis
- `telescope` (string) — telescope filter
- `camera` (string) — camera filter
- `granularity` (string) — `frame` or `session`
- `date_from` (string, optional) — YYYY-MM-DD, start of date range
- `date_to` (string, optional) — YYYY-MM-DD, end of date range

Response:
```json
{
  "points": [
    {"x": 65.2, "y": 1.8, "date": "2025-06-15", "target_name": "Veil Nebula"},
    ...
  ],
  "trend": {"slope": 0.023, "intercept": 0.5, "r_squared": 0.34}
}
```

When `granularity=session`, the backend computes session medians server-side. Trend line coefficients computed server-side (simple linear regression).

Metric name validation: backend maps allowed metric names to `Image` model columns. Rejects unknown metrics.

### Frontend

New page: `frontend/src/pages/Analysis.tsx`
New components in `frontend/src/components/analysis/`:
- `CorrelationChart` — reusable scatter plot with trend line
- `CorrelationExplorer` — custom X/Y selector
- `EquipmentComboSelect` — shared with Stats page (extract if not already shared)

New nav link in `NavBar`.

---

## Feature 3: Session Notes & Annotations

### Data Model

**Target notes:** New nullable `notes` text column on the existing `targets` table.

**Session notes:** New `session_notes` table:

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `target_id` | UUID | FK → targets, NOT NULL |
| `session_date` | Date | NOT NULL |
| `notes` | Text | NOT NULL |
| `updated_at` | DateTime | NOT NULL |

Composite unique constraint on `(target_id, session_date)`.

Sessions are not a first-class entity in the current schema — they're derived by grouping images by target + date. `SessionNote` bridges this by keying on the same pair.

### Migration

New Alembic migration:
- `op.add_column('targets', Column('notes', Text, nullable=True))` — with `_add_column_if_not_exists` guard
- `op.create_table('session_notes', ...)` — with existence guard

### API

**Target notes:**
- `PUT /api/targets/{target_id}/notes` — body: `{"notes": "string or null"}`
- Notes also returned in existing `TargetDetailResponse` (add `notes` field)

**Session notes:**
- `PUT /api/targets/{target_id}/sessions/{date}/notes` — body: `{"notes": "string or null"}`
- `GET` not needed separately — notes included in existing session detail response (add `notes` field to `SessionDetailResponse`)
- Sending `null` or empty string deletes the note

### Frontend

**Target notes:** Collapsible "Notes" section on Target Detail page, below the hero/stats area. Simple textarea. Auto-saves on blur with 1s debounce. Shows placeholder text ("Add notes about this target...") when empty.

**Session notes:** On each `SessionAccordionCard`:
- Small note icon on the collapsed card header — filled when a note exists, outlined when empty
- Clicking the icon (or expanding the session) reveals a textarea inline within the session detail
- Same auto-save behavior
- Note indicator visible even when session is collapsed, so you can scan which sessions have annotations

### Behavior

- Plain text, no markdown rendering in v1
- No character limit
- Auto-save with visual feedback (subtle "Saved" indicator that fades)

---

## Feature 4: Export for AstroBin

### Location

Target Detail page. "Export" button in the header area near the target name.

### Workflow

1. User clicks Export → modal/drawer opens
2. All sessions listed with checkboxes, all selected by default
3. User can deselect sessions to exclude
4. Two action buttons at bottom: "Copy to Clipboard" and "Download CSV"

### Copyable Text Format

Human-readable acquisition summary for pasting into AstroBin image descriptions:

```
Veil Nebula (NGC 6960)
Equipment: Esprit 120ED + ASI2600MM Pro
Dates: 2025-06-15, 2025-07-02, 2025-07-18

Ha: 45 x 300s (3h 45m) | Gain 100 | -10°C
OIII: 38 x 300s (3h 10m) | Gain 100 | -10°C
SII: 30 x 300s (2h 30m) | Gain 100 | -10°C

Total integration: 9h 25m
```

Grouped by filter. Per-filter: frame count, sub-exposure duration, total integration (human-readable), gain (mode across frames), sensor temp (median, rounded to whole number). Dates listed chronologically. Equipment from sessions (if mixed, list all combos).

### CSV Format (AstroBin-Importable)

Follows the AstroBin CSV import specification (https://welcome.astrobin.com/importing-acquisitions-from-csv).

**One row per filter per session date.** Header row required.

Columns:
```
date,number,duration,filter,gain,sensorCooling,meanFwhm,meanSqm,temperature,darks,flats,bias,bortle
```

Field mapping from GalactiLog data:

| AstroBin Field | Source | Format |
|----------------|--------|--------|
| `date` | Session date | YYYY-MM-DD |
| `number` | Frame count for that filter+date | Whole number |
| `duration` | `exposure_time` | Decimal seconds |
| `filter` | AstroBin equipment DB ID | Numeric (from user config) |
| `gain` | `camera_gain` | Decimal, max 2 places |
| `sensorCooling` | `sensor_temp` median | Whole number, °C |
| `meanFwhm` | `fwhm` median | Decimal, max 2 places |
| `meanSqm` | `sky_quality` median | Decimal, max 2 places |
| `temperature` | `ambient_temp` median | Decimal, max 2 places, −88 to 58°C |
| `darks` | Count of matching DARK frames (same gain+temp+exposure) | Whole number |
| `flats` | Count of matching FLAT frames (same camera+filter) | Whole number |
| `bias` | Count of matching BIAS frames (same camera+gain) | Whole number |
| `bortle` | From user settings (if configured) | 1–9 |

**Filter ID handling:** The `filter` column requires AstroBin's numeric equipment database ID, not a filter name. If the user has configured filter ID mappings, populate the column. If not, leave it blank — AstroBin ignores invalid/empty filter values and the user can assign filters manually after import.

**Calibration frame matching:**
- Darks: match by camera + gain + sensor temp (±2°C) + exposure time
- Flats: match by camera + filter (any date — flats are reused)
- Bias: match by camera + gain

### AstroBin Filter ID Settings

New section in Settings page: "AstroBin Integration"

A table mapping each discovered filter name to its AstroBin equipment database ID:

| Filter | AstroBin ID |
|--------|-------------|
| Ha | (numeric input) |
| OIII | (numeric input) |
| L | (numeric input) |

Help text linking to AstroBin's equipment database explaining how to find IDs. Optional `bortle` field for the user's site Bortle class.

Stored in `UserSettings.general` as `astrobin_filter_ids: {filter_name: numeric_id}` and `astrobin_bortle: number`.

### Backend

New endpoint: `GET /api/targets/{target_id}/export?sessions=2025-06-15,2025-07-02`

Response — grouped by `(date, filter)` to match AstroBin's one-row-per-filter-per-date requirement:
```json
{
  "target_name": "Veil Nebula",
  "catalog_id": "NGC 6960",
  "equipment": [{"telescope": "Esprit 120ED", "camera": "ASI2600MM Pro"}],
  "dates": ["2025-06-15", "2025-07-02"],
  "rows": [
    {
      "date": "2025-06-15",
      "filter": "Ha",
      "astrobin_filter_id": 1234,
      "frames": 20,
      "exposure": 300.0,
      "total_seconds": 6000,
      "gain": 100,
      "sensor_temp": -10,
      "fwhm": 2.1,
      "sky_quality": null,
      "ambient_temp": 15.3
    },
    {
      "date": "2025-06-15",
      "filter": "OIII",
      "astrobin_filter_id": 1235,
      "frames": 18,
      "exposure": 300.0,
      "total_seconds": 5400,
      "gain": 100,
      "sensor_temp": -10,
      "fwhm": 2.0,
      "sky_quality": null,
      "ambient_temp": 14.8
    }
  ],
  "calibration": {
    "darks": 30,
    "flats": 20,
    "bias": 50
  },
  "total_integration_seconds": 28500,
  "bortle": 5
}
```

Frontend formats `rows` into both the AstroBin CSV (one row per entry) and the copyable text (aggregated across dates, grouped by filter).

---

## Feature 5: Mosaic Panel Tracking

### Data Model

**Mosaic table:**

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `name` | String | NOT NULL, UNIQUE |
| `notes` | Text | Nullable |
| `created_at` | DateTime | NOT NULL |
| `updated_at` | DateTime | NOT NULL |

**Mosaic panels table:**

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `mosaic_id` | UUID | FK → mosaics, NOT NULL |
| `target_id` | UUID | FK → targets, NOT NULL, UNIQUE |
| `panel_label` | String | NOT NULL (e.g., "Panel 1", "P3") |
| `sort_order` | Integer | NOT NULL, default 0 |

Unique constraint on `(mosaic_id, target_id)`. A target can belong to at most one mosaic (UNIQUE on `target_id`).

### Auto-Detection

**Configuration:** New field in `UserSettings.general`: `mosaic_keywords` — array of strings, default `["Panel", "P"]`.

**Detection logic:** During target resolution (or as a background task), if a target's `primary_name` or any alias matches the pattern `{base_name} {keyword} {number}` (case-insensitive, with optional separators like `_`, `-`, ` `), extract the base name and panel number. Group all targets sharing the same base name into a suggested mosaic.

**Suggestion flow:** New `mosaic_suggestions` table (not reusing `MergeCandidate` — different schema needs):

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | UUID | PK |
| `suggested_name` | String | NOT NULL — the detected base name |
| `target_ids` | ARRAY of UUID | NOT NULL — targets that matched |
| `panel_labels` | ARRAY of String | NOT NULL — extracted labels per target |
| `status` | String | "pending", "accepted", "rejected" |
| `created_at` | DateTime | NOT NULL |

- Surfaced in Settings → Mosaics section
- User reviews and accepts/rejects
- Accepting creates the `Mosaic` and `MosaicPanel` records

**Manual grouping:** User can also:
- Create a mosaic from scratch (name it, then add targets as panels)
- Add/remove panels from an existing mosaic
- Edit panel labels and sort order

### Mosaic Detail View

Accessible via:
- Direct navigation from a "Mosaics" list/section
- Link from Target Detail page when a target belongs to a mosaic

**Layout (top to bottom):**

**Header:** Mosaic name, total integration across all panels, total frames, notes field (same auto-save textarea as Feature 3).

**Spatial grid:** Panels arranged by relative RA/Dec offsets.
- Compute each panel's center position from median RA/Dec of its images
- Compute mosaic center as the mean of all panel centers
- Render panels as rectangles positioned by their offset from center
- Panel size based on target's `size_major`/`size_minor` if available, else uniform squares
- Color-coded by integration completeness relative to the most-complete panel:
  - Green: >80% of max panel integration
  - Yellow: 40–80%
  - Red: <40%
- Panel label displayed inside each rectangle
- Hover tooltip: panel name, integration hours, frame count

**Per-panel table:** Below the grid, a table with one row per panel:

| Panel | Integration | Frames | Filters | Last Session | Actions |
|-------|-------------|--------|---------|--------------|---------|
| Panel 1 | 8h 30m | 102 | Ha: 5h, OIII: 3.5h | 2025-07-18 | → Detail |
| Panel 2 | 4h 15m | 51 | Ha: 4.25h | 2025-07-02 | → Detail |

"→ Detail" links to the panel's Target Detail page.

### API

- `GET /api/mosaics` — list all mosaics with summary stats (total integration, panel count, completion percentage)
- `POST /api/mosaics` — create mosaic: `{name, notes?, target_ids?: [{target_id, panel_label}]}`
- `GET /api/mosaics/{id}` — full detail: panels with RA/Dec offsets, per-panel stats, grid data
- `PUT /api/mosaics/{id}` — update name, notes
- `DELETE /api/mosaics/{id}` — dissolve mosaic (panels become standalone targets, no data lost)
- `POST /api/mosaics/{id}/panels` — add panel: `{target_id, panel_label}`
- `PUT /api/mosaics/{id}/panels/{panel_id}` — update label, sort_order
- `DELETE /api/mosaics/{id}/panels/{panel_id}` — remove panel from mosaic
- `GET /api/mosaics/suggestions` — auto-detected mosaic grouping suggestions

### Dashboard Integration

- Targets belonging to a mosaic show a small mosaic icon badge in the target feed
- Clicking the icon navigates to the mosaic detail view
- Optional "Mosaics" filter in the sidebar to show only mosaic project targets

### Settings Integration

New subsection in Settings: "Mosaics"
- Configure `mosaic_keywords` — editable list of panel-detection keywords
- Trigger re-detection scan
- Review/accept/reject mosaic suggestions

### Frontend

New page: `frontend/src/pages/MosaicDetail.tsx`
New components in `frontend/src/components/mosaics/`:
- `MosaicGrid` — spatial RA/Dec panel layout with color coding
- `MosaicPanelTable` — per-panel stats table
- `MosaicManager` — create/edit mosaic, add/remove panels
- `MosaicSuggestions` — review auto-detected groupings

---

## Migration Summary

| Feature | New Tables | Altered Tables | New Settings Fields |
|---------|------------|----------------|---------------------|
| 1. Calendar Heatmap | None | None | `graph.default_timeline_view` |
| 2. Analysis | None | None | None |
| 3. Session Notes | `session_notes` | `targets` (+notes) | None |
| 4. AstroBin Export | None | None | `general.astrobin_filter_ids`, `general.astrobin_bortle` |
| 5. Mosaic Tracking | `mosaics`, `mosaic_panels`, `mosaic_suggestions` | None | `general.mosaic_keywords` |

Single Alembic migration covering all schema changes (or split per feature if implementing incrementally).

## New Pages Summary

| Page | Route | Nav Position |
|------|-------|-------------|
| Analysis | `/analysis` | Between Dashboard and Statistics |
| Mosaic Detail | `/mosaics/{id}` | Linked from targets/dashboard |

## DATA_VERSION

Features 3 and 5 add new tables but no derived data changes. No DATA_VERSION bump needed — these are user-authored data (notes) and user-configured groupings (mosaics), not computed derivations.
