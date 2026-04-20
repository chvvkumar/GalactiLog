# Target Health Redesign

## Problem

Target duplicate management, resolution of unknown FITS names, and post-scan maintenance are spread across multiple disconnected UI surfaces with overlapping backend operations. The Settings "Target Management" tab mixes three unrelated concerns (duplicate suggestions, merge history, unresolved files) and the Library tab maintenance buttons ("Fix Orphans", "Re-resolve", "Catalog Match", "Fetch DSS") are cryptically named with no explanation of what they do. One of them (Catalog Match) writes nothing to the database.

Users cannot:
- See at a glance what needs attention after a scan
- Preview what a merge will do before committing
- Rename a target without merging it into another
- Understand why the system flagged two targets as duplicates
- Tell which maintenance operations are automatic vs manual-only

## Scope

### In scope
- Replace the MergesTab (Target Management) with a unified Target Health view
- Add merge preview modal with side-by-side comparison and winner selection
- Add inline rename and re-resolve on TargetDetail page
- Add `name_locked` column to prevent smart rebuild from overwriting user renames
- Add post-scan summary banner
- Reorganize maintenance buttons: remove redundant/broken ones, rename survivors, add descriptions
- Remove the backfill-targets and xmatch-enrichment endpoints

### Out of scope
- Scanning pipeline (file discovery, FITS extraction, SIMBAD resolution)
- Target creation during ingest (`_create_target` pipeline)
- Data enrichment pipeline (OpenNGC, VizieR, SAC)
- Underlying merge mechanics (soft delete, alias transfer, image reassignment)
- Session grouping, statistics computation, mosaic detection
- Coordinate editing

---

## Design

### 1. Target Health View

Replaces the current "Target Management" tab in Settings. The tab is renamed to "Target Health."

#### 1.1 Post-Scan Summary Banner

A banner at the top of the Target Health view summarizing the most recent scan outcome. Rendered when scan_summary data exists; dismissed on next scan or manually.

Content: files ingested count, new targets created, targets updated (aliases added by smart rebuild), duplicates found, unresolved names, errors. Each non-zero count is a clickable filter that narrows the issue list below.

Data source: after the post-scan chain completes (scan + smart_rebuild + detect_duplicates), the backend writes a JSON blob to Redis key `galactilog:scan_summary`. The frontend fetches this via a new `GET /scan/summary` endpoint.

#### 1.2 Issue List

A single prioritized list of all target health issues, replacing the three sub-views (Suggestions, Merged, Unresolved Files).

Filter pills at the top: "All Issues" (default), "Duplicates", "Unresolved", "Recent Merges". Each pill shows a count badge.

Issue types in priority order:

**Potential Duplicate.** Source: `MergeCandidate` rows with status "pending" and method in ("simbad", "trigram", "duplicate"). Each card shows:
- The two target names (or target + unresolved name)
- Plain-English explanation replacing method badges:
  - simbad: "SIMBAD resolves both names to the same object"
  - trigram: "Names are N% similar" (using the similarity_score)
  - duplicate: "These targets share the alias X" (derived from the alias overlap found during detection)
- Image counts for each side
- Actions: [Preview Merge] [Not a Duplicate]

**Unresolved FITS Name.** Source: `MergeCandidate` rows with method "orphan", plus any unresolved OBJECT names not yet represented as candidates. Each card shows:
- The raw FITS OBJECT value
- Number of LIGHT frames with this name
- Nearest match if trigram found one (with similarity percentage)
- Actions: [Assign to X] (if a near match exists), [Create New Target], [Retry SIMBAD], [Dismiss]

When unresolved items exist, a contextual banner appears above the list: "N files couldn't be identified. [Retry Failed Lookups] to check SIMBAD again." This replaces the old "Re-resolve" maintenance button.

**Recent Merge.** Source: `MergeCandidate` rows with status "accepted", filtered to the last 30 days by default. Muted card styling. Shows:
- Which target was merged into which
- Image count that moved
- When the merge occurred
- Action: [Undo Merge]
- A "Show older" link to load merges beyond 30 days

#### 1.3 Advanced Maintenance Section

A collapsible section at the bottom of Target Health, collapsed by default. Contains the remaining manual maintenance operations with clear descriptions:

**Repair Target Links** (was "Fix Orphans" / smart_rebuild_targets)
Description: "Repairs image-to-target links and re-derives target names using cached data. Runs automatically after every scan. Use manually if data looks inconsistent."

**Full Rebuild** (unchanged name, rebuild_targets)
Description: "Deletes all targets and re-resolves everything from scratch via SIMBAD. Use only if target data is badly corrupted. Takes several minutes for large libraries."
Requires a confirmation dialog before execution.

**Retry Failed Lookups** (was "Re-resolve" / retry_unresolved)
Description: "Clears failed SIMBAD lookup caches and retries all unresolved names against live SIMBAD. Use after an extended offline period or if SIMBAD was down during a previous scan."
Also accessible as the contextual banner action in the issue list (Section 1.2).

Each button shows inline progress while running (reusing the existing active-jobs polling). After completion, the issue list refreshes.

#### 1.4 Buttons Removed

**"Catalog Match"** (xmatch-enrichment): Removed from UI and backend. The current implementation queries CDS xMatch but discards results without writing to the database.

**"Fetch DSS"** (generate-reference-thumbnails): Moved to the Library tab alongside other thumbnail operations. Renamed to "Fetch Reference Images" with subtitle: "Downloads survey images from NASA SkyView for sky view comparison." Retains the existing "Missing only" / "Re-fetch all" sub-actions.

**Backfill Targets endpoint** (`POST /scan/backfill-targets`): Removed. Its functionality is a subset of what scan + smart_rebuild already do.

---

### 2. Merge Preview Modal

Replaces the current MergeTargetModal (search + confirm) with a two-step flow: search, then preview.

#### 2.1 Entry Points

- "Preview Merge" on a duplicate issue card in Target Health
- "Assign to [target]" on an unresolved issue card in Target Health
- "Merge" button on TargetDetail page (admin only)

#### 2.2 Layout

Side-by-side comparison of both targets (or target + unresolved name):

Left panel and right panel each show:
- Primary name
- Object type and constellation
- Image count and session count
- Total integration time
- All aliases

A radio button on each side: "Keep as primary." The system pre-selects the target with more images as the default winner, but the user can flip it.

Below the comparison, a "What will happen" summary computed by the backend:
- N images will move from [loser] to [winner]
- Alias "X" will be added to [winner]
- N mosaic panels will be reassigned (if applicable)
- "[Loser]" will be soft-deleted

Footer: [Cancel] [Merge]

#### 2.3 For Unresolved Name Assignment

When assigning an unresolved name to an existing target, the left panel shows the existing target and the right panel shows:
- The raw FITS OBJECT value
- Image count
- Any FITS-header-extracted coordinates (if available)
- No aliases, object type, or other metadata (since it's unresolved)

The existing target is always the winner. No radio buttons needed.

#### 2.4 Backend Endpoint

`POST /targets/merge-preview`

Request body: `{ winner_id: UUID, loser_id?: UUID, loser_name?: string }`

Response:
```json
{
  "winner": { "id", "primary_name", "object_type", "constellation", "image_count", "session_count", "integration_seconds", "aliases" },
  "loser": { "id", "primary_name", "object_type", "constellation", "image_count", "session_count", "integration_seconds", "aliases" },
  "images_to_move": 3,
  "mosaic_panels_to_move": 1,
  "aliases_to_add": ["NORTH AMERICA NEBULA"]
}
```

When `loser_name` is provided instead of `loser_id`, the `loser` object contains only `primary_name` (the raw FITS value), `image_count`, and `aliases: []`.

Read-only endpoint, no mutations.

#### 2.5 After Merge

The issue card in the Target Health list updates in-place to show "Merged just now" with an undo button. No full page reload. The filter pill badge counts update.

When triggered from TargetDetail, the page refreshes to show the updated target (with new aliases, updated image count).

---

### 3. Target Rename and Identity Editing

#### 3.1 UI on TargetDetail Page

The primary name in the hero section becomes editable for admin users. Two actions next to the name:

- Edit icon: clicking it turns the name into an inline text input. On save (Enter or blur), calls `PUT /targets/{id}/identity` with `{ primary_name: "new name" }`. Sets `name_locked = true` on the backend.
- Re-resolve icon: calls `PUT /targets/{id}/identity` with `{ re_resolve: true }`. Clears negative caches for this target's aliases, queries SIMBAD fresh, re-runs curation, and updates catalog_id / common_name / primary_name. Clears `name_locked`.

Object type is also editable via a dropdown of the existing category list (Emission Nebula, Reflection Nebula, Dark Nebula, Planetary Nebula, Supernova Remnant, Galaxy, Open Cluster, Globular Cluster, Star, Other). Saves via the same identity endpoint.

When `name_locked` is true, a subtle lock indicator appears next to the name with a tooltip: "Name set manually. Automatic processes will not rename this target."

#### 3.2 Backend Endpoint

`PUT /targets/{id}/identity`

Request body (all fields optional):
```json
{
  "primary_name": "My Custom Name",
  "object_type": "Emission Nebula",
  "re_resolve": false
}
```

Behavior:
- If `primary_name` is provided: update `target.primary_name`, set `target.name_locked = True`.
- If `object_type` is provided: map the display category back to the corresponding SIMBAD type code using the inverse of `_SIMBAD_CATEGORY_MAP` and store the SIMBAD code in `target.object_type`. This keeps the storage format consistent with SIMBAD-derived targets.
- If `re_resolve` is true: clear `simbad_cache` negative entries for this target's aliases, call `resolve_target_name_cached` with the target's catalog_id or primary_name, run `curate_simbad_result`, update catalog_id / common_name / primary_name / object_type, set `name_locked = False`.

#### 3.3 Schema Change

New column on `Target` model:
- `name_locked: Boolean, default=False, server_default=false, NOT NULL`

Alembic migration adds the column with `_add_column_if_not_exists` pattern per project conventions.

#### 3.4 Smart Rebuild Guard

`smart_rebuild_targets` Phase 4 (re-derive from SIMBAD cache) and Phase 5 (rebuild primary_name formula) skip targets where `name_locked = True`. This is a WHERE clause addition to the existing queries.

---

### 4. Post-Scan Summary

#### 4.1 Data Collection

After the automatic post-scan chain completes (smart_rebuild + detect_duplicates), the final task in the chain writes a summary to Redis:

```json
{
  "completed_at": "2026-04-20T03:42:00Z",
  "files_ingested": 12,
  "targets_created": 3,
  "targets_updated": 1,
  "duplicates_found": 2,
  "unresolved_names": 1,
  "errors": 0
}
```

Key: `galactilog:scan_summary`. No TTL (persists until next scan overwrites it).

`targets_created`: count of new Target rows created during this scan's ingest tasks.
`targets_updated`: count of targets that gained new aliases during smart rebuild Phase 3.
`duplicates_found`: count of new MergeCandidate rows created by detect_duplicate_targets.
`unresolved_names`: count of distinct OBJECT values still unresolved after the full chain.
`errors`: count of ingest failures.

#### 4.2 API Endpoint

`GET /scan/summary`

Returns the Redis blob or `null` if no scan has completed yet.

#### 4.3 Frontend

The Target Health tab fetches the summary on mount. Renders the banner described in Section 1.1. Each non-zero metric is a clickable link that sets the corresponding filter pill in the issue list.

---

### 5. Maintenance Button Reorganization Summary

| Current | Action | New Name | New Location |
|---|---|---|---|
| Fix Orphans | Rename, move | Repair Target Links | Target Health > Advanced |
| Re-resolve | Rename, move | Retry Failed Lookups | Target Health > contextual banner + Advanced |
| Catalog Match | Remove | (deleted) | (deleted) |
| Fetch DSS | Rename, move | Fetch Reference Images | Library tab |
| Run Detection | Remove from UI | (automatic) | Results surface in Target Health issue list |
| Smart Rebuild | Already in Advanced | Repair Target Links | Target Health > Advanced (same as Fix Orphans) |
| Full Rebuild | Move | Full Rebuild | Target Health > Advanced |
| Backfill Targets | Remove | (deleted) | (deleted) |

The MaintenanceActions component in the Library tab is replaced by a single "Fetch Reference Images" button with its existing "Missing only" / "Re-fetch all" sub-actions and a clear description.

---

### 6. Backend Changes Summary

| Change | Type |
|---|---|
| `POST /targets/merge-preview` | New endpoint |
| `PUT /targets/{id}/identity` | New endpoint |
| `GET /scan/summary` | New endpoint |
| `Target.name_locked` column | New migration |
| `smart_rebuild_targets` Phases 4-5 | Add `name_locked` guard |
| `POST /scan/xmatch-enrichment` | Remove endpoint |
| `POST /scan/backfill-targets` | Remove endpoint |
| `run_xmatch_enrichment` task | Remove task |
| Post-scan chain | Write scan_summary to Redis after detect_duplicates completes |
| `detect_duplicate_targets` | Add plain-English reason string to MergeCandidate rows |

### 7. Frontend Changes Summary

| Change | Type |
|---|---|
| MergesTab | Replace with TargetHealthTab |
| MergeTargetModal | Replace with MergePreviewModal |
| MaintenanceActions | Reduce to single "Fetch Reference Images" button |
| TargetDetailPage hero | Add inline rename, re-resolve, object type edit |
| TargetDetailPage | Update MergeTargetModal to use MergePreviewModal |
| Settings nav | Rename "Target Management" tab to "Target Health" |

### 8. MergeCandidate Model Change

Add a `reason_text` column (String, nullable) to `MergeCandidate`. Populated by `detect_duplicate_targets` with human-readable explanation:
- "SIMBAD resolves both names to NGC 7000"
- "Names are 87% similar"
- "Both targets share the alias NGC 7000"
- "No match found in SIMBAD or catalogs" (for orphans)

Existing rows with null `reason_text` render the current method badge as a fallback until the next detection run populates the field.
