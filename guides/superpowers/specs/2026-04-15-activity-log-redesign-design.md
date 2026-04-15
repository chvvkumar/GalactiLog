# Activity Log Redesign

Date: 2026-04-15
Status: approved for planning

## Problem

The Dashboard Activity Log mixes three concerns in one card: live scan progress, live rebuild status, and a 20-entry historical list. Many user-relevant events never reach the log (per-file ingest failures, thumbnail failures, mosaic detection results, mosaic composite failures, Gaia and VizieR failures, migration progress, filename candidate failures, scan filter errors). Toasts are a disconnected channel with ad-hoc firing rules. The result is a surface that feels random: some events appear, some do not, and live status feels bolted on.

## Goals

1. Every user-relevant event reaches a single durable store with severity and category.
2. Live in-progress jobs render in a clearly separated region from history.
3. Toasts follow a predictable rule rather than per-callsite judgement.
4. Historical entries are filterable by severity and category.
5. Retention is bounded and admin-configurable.

## Non-goals (v1)

- Websocket or SSE push. Polling is retained.
- Per-target activity view on target detail pages.
- Text search or target filter in the History region.
- Activity surface visible outside the Dashboard.
- Activity export (CSV etc).
- Cancel controls for Celery-tracked jobs beyond current behavior.

## Architecture

Backend additions:

- `backend/app/models/activity_event.py`: new SQLAlchemy model.
- `backend/app/services/activity.py`: `emit()` and `emit_sync()` helpers. Single source of truth for activity writes.
- `backend/app/api/activity.py`: `GET /activity` (paginated, filterable), `DELETE /activity` (admin).
- `backend/app/worker/prune_activity.py`: nightly Celery beat task.
- Alembic migration creating `activity_events` with defensive `IF NOT EXISTS` guards per project rules.

Backend retained unchanged:

- `/scan/status`, `/scan/rebuild-status`, `/tasks/{id}/status` endpoints and their Redis-backed state.

Frontend additions:

- `frontend/src/store/activeJobs.ts`: adapter merging scan status, rebuild status, and tracked Celery tasks into one `ActiveJob[]` observable.
- Extension to `frontend/src/store/taskPoller.ts`: `track({id, category, label, cancelable})` method registers Celery tasks with the active-jobs adapter.
- `frontend/src/api/client.ts`: new functions for `/activity` endpoints.

Frontend rewritten:

- `frontend/src/components/ActivityFeed.tsx`: single card with Now Running and History regions.
- Toast firing rules codified in a helper `emitWithToast()`; per-callsite ad-hoc toast code in `MergesTab.tsx`, `MosaicsTab.tsx`, and `MaintenanceActions.tsx` is replaced.

## Data model

Table `activity_events`:

```
id              bigserial primary key
timestamp       timestamptz not null default now()
severity        varchar(16) not null   -- 'info' | 'warning' | 'error'
category        varchar(32) not null
event_type      varchar(64) not null
message         text not null
details         jsonb                  -- nullable
target_id       integer                -- nullable, fk targets(id) ON DELETE SET NULL
actor           varchar(64)            -- nullable
duration_ms     integer                -- nullable

indexes:
  idx_activity_timestamp_desc  on (timestamp DESC)
  idx_activity_severity_ts     on (severity, timestamp DESC)
  idx_activity_category_ts     on (category, timestamp DESC)
  idx_activity_target          on (target_id) where target_id is not null
```

Categories (fixed set, validated in `emit()`):

- `scan`: file discovery, ingest, delta scans, orphan cleanup, stalls
- `rebuild`: target rebuild (smart, full, cancelled)
- `thumbnail`: thumbnail purge, regeneration, DSS reference fetch
- `enrichment`: SIMBAD, VizieR, Gaia, xMatch
- `mosaic`: mosaic detection, composite generation
- `migration`: data migration runs (DATA_VERSION bumps)
- `user_action`: merges accepted, filename candidates accepted, manual deletions
- `system`: auth, startup, pruner output, catch-all

Severity is `info`, `warning`, or `error`. Validated in the emit helper, not as a DB enum, so future values do not require a migration.

## Emit helper

```python
async def emit(
    db: AsyncSession,
    *,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict | None = None,
    target_id: int | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
) -> None:
    ...
```

Behavior:

- Validates `severity` and `category` at runtime; raises on invalid values during development, logs and skips in production.
- Inserts one row into `activity_events`.
- Publishes a JSON payload to Redis pubsub channel `activity:new` for future push-based UI. Not subscribed to in v1.
- Never raises to the caller. Emit failures are logged to Python logging only.

`emit_sync()` mirrors the signature for Celery tasks using sync sessions.

## Event backfill

All existing activity writes (17 sites across `scan_state.py`, `scan.py`, `worker/tasks.py`) are refactored to call `emit()` in place of the current Redis-list push. The Redis key `scan:activity` is deleted on startup by the new code.

New emit sites with aggregation where needed:

| Site | event_type | severity | Aggregation |
|------|-----------|----------|-------------|
| Per-file ingest failures | `scan_files_failed` | warning | one summary per scan, `details.failed_files: [{path, reason}, ...]` |
| Thumbnail regen failures | `thumbnail_regen_failed` | warning | one summary per rebuild |
| Mosaic detection run | `mosaic_detection_complete` | info | one entry per run, `details.candidates: N` |
| Mosaic composite failures | `mosaic_composite_failed` | error | one per mosaic |
| Gaia, VizieR failures | `enrichment_query_failed` | warning | one summary per rebuild, `details.failed_targets: [...]` |
| Migration progress ticks | (skipped) | n/a | only `data_upgrade_complete` and `data_upgrade_failed` survive |
| Filename candidate failures | `filename_candidate_failed` | warning | one summary per ingest batch |
| Scan filter invalid | `scan_filter_rejected` | error | one per occurrence |

## API

### `GET /activity`

Auth: user.

Query params:

- `severity`: optional, repeatable. Values: `info`, `warning`, `error`.
- `category`: optional, repeatable. Values from the fixed category set.
- `limit`: optional, default 50, max 200.
- `cursor`: optional, keyset pagination token encoding `(timestamp, id)` of the last row of the previous page.
- `since`: optional ISO timestamp. Returns only rows with `timestamp > since`. Used by the error-toast poller.

Response:

```json
{
  "items": [
    {
      "id": 42,
      "timestamp": "2026-04-15T16:42:10Z",
      "severity": "warning",
      "category": "scan",
      "event_type": "scan_stalled",
      "message": "Scan stalled after 5 min idle",
      "details": null,
      "target_id": null,
      "actor": "system",
      "duration_ms": null
    }
  ],
  "next_cursor": "2026-04-15T15:20:00Z:31",
  "total": 1284
}
```

### `DELETE /activity`

Auth: admin. Clears all rows. Replaces existing `DELETE /scan/activity`.

### Settings

One new admin setting:

- `activity_retention_days`: integer, default 90, min 1, max 3650. Stored in the existing `settings` table.

Exposed via the existing Settings page under an Activity Log section, alongside the Clear button.

## Active Jobs adapter

`frontend/src/store/activeJobs.ts`:

```ts
type ActiveJob = {
  id: string;                 // 'scan', 'rebuild', or `celery:${taskId}`
  category: 'scan' | 'rebuild' | 'thumbnail' | 'enrichment' | 'mosaic';
  label: string;
  subLabel?: string;
  progress?: number;          // 0..1, undefined = indeterminate
  startedAt: number;
  detail?: string;
  cancelable: boolean;
  onCancel?: () => Promise<void>;
};
```

Adapters:

- `scanStatusToJob(ScanStatus)`: returns null when state is idle, complete, or stalled. Progress is `completed/total`. Cancel calls existing `POST /scan/stop`.
- `rebuildStatusToJob(RebuildStatus)`: returns null when idle, complete, error, or cancelled. Progress is indeterminate. Cancel calls existing rebuild stop endpoint.
- `celeryTaskToJob(trackedTask)`: returns an entry while Celery state is PENDING or STARTED. Not cancelable in v1.

The store exposes `activeJobs: Accessor<ActiveJob[]>` and `hasActiveJobs: Accessor<boolean>`. Existing 2-second polling for scan and Celery is retained. Rebuild poll is aligned to 2 seconds if not already.

`taskPoller.track()` is called by:

- `MergesTab.tsx`: duplicate detection.
- `MosaicsTab.tsx`: mosaic detection.
- `MaintenanceActions.tsx`: xMatch enrichment, DSS reference thumbnails, thumbnail regen, smart rebuild, full rebuild, SIMBAD re-resolve.

## Dashboard card layout

```
┌─────────────────────────────────────────────────────────┐
│  Activity                                     [ 2 live ]│
├─────────────────────────────────────────────────────────┤
│  NOW RUNNING                                            │
│                                                         │
│  Scanning /mnt/fits                          [  Stop ]  │
│  2,341 / 5,892 files, 42 files/sec                      │
│  ████████████░░░░░░░░░░░░░░░░  42%                      │
│                                                         │
│  Mosaic composite: NGC 7000 (indeterminate)             │
│  started 00:42 ago                                      │
│  ▓▓░░░▓▓░░░▓▓░░                                         │
├─────────────────────────────────────────────────────────┤
│  HISTORY                                                │
│  [ all ]  [ info ]  [ warn ]  [ error ]                 │
│  [all] [scan] [rebuild] [thumb] [enrich] [mosaic] [migr]│
│                                                         │
│  16:42  warn   scan    Scan stalled after 5 min idle  > │
│  15:20  ok     reb     Rebuild complete, 42 targets     │
│  15:20  warn   scan    Scan complete, 12 failures     > │
│                        expanded:                        │
│                          file1.fits, header parse error │
│                          file2.fits, SIP ctype mismatch │
│                          (10 more)                      │
│  14:55  ok     user    Merge accepted: NGC 7000 ← NAm   │
│  14:12  info   migr    Data upgrade v7 → v8 complete    │
│                                                         │
│          [ Load older ]                                 │
└─────────────────────────────────────────────────────────┘
```

Behavior:

- The Now Running region collapses to zero height when `activeJobs.length === 0`. No empty-state placeholder text.
- The header badge is hidden at zero, visible otherwise.
- History initial load is 50 entries. `Load older` paginates by 50 using the keyset cursor. Filter changes reset pagination.
- Row structure: time, severity icon, category label, message, chevron if `details` is present.
- If `target_id` is set, the target name in the message renders as a link to that target detail page.
- Expandable rows render `details` via category-aware renderers: `FailedFilesList`, `EnrichmentFailureList`, generic JSON fallback.
- Styling uses existing theme tokens. Severity icons reuse the existing icon set. Now Running uses a subtly tinted background via `--color-bg-subtle` to distinguish the region without adding a heavy border.
- Now Running has `role="status" aria-live="polite"`. Rows are keyboard-focusable.
- New history entries do not auto-scroll. If new entries arrive while the user is scrolled down, a "N new" pill appears at the top and jumps to them on click.

## Toast rules

1. User-initiated action: toast on completion. Applies to merge accept, filename candidate accept, image delete, all maintenance buttons, manual scan start and stop.
2. Background event: no toast. Includes scheduled scans, migration runs, mosaic detection after ingest.
3. Exception: any event with severity `error` always toasts, regardless of source. Error toasts persist until dismissed.

Implementation:

- Frontend helper `emitWithToast()` wraps an API call, shows a pending toast, tracks the resulting Celery task via `activeJobs`, and replaces the toast on completion.
- Background error channel: frontend polls `GET /activity?severity=error&since=<lastSeenErrorTs>` every 10 seconds. New rows trigger error toasts. `lastSeenErrorTs` persists in localStorage.
- Error toasts include a "View in activity log" link that scrolls the Dashboard card to the matching row. Info and success toasts retain the 3-second auto-dismiss.

## Pruner

New Celery beat task `prune_activity_events`:

- Runs daily at 03:00 local time.
- Executes `DELETE FROM activity_events WHERE timestamp < now() - interval 'N days'` where N is `activity_retention_days`.
- Emits one `system` `info` event with `event_type=activity_pruned` and `details.deleted_count=N` only if N > 0.

## Rollout

- Alembic migration creates `activity_events` with defensive guards. No data backfill from the old Redis list; entries there are ephemeral by design.
- On first startup after deploy, `scan:activity` Redis key is deleted to reclaim memory.
- Old endpoints `GET /scan/activity` and `DELETE /scan/activity` are removed in the same release. Frontend is updated in the same PR.
- No feature flag. No `DATA_VERSION` bump (no change to target data derivation).

## Open risks

- High-volume emit during a bad scan: aggregation patterns mitigate, but a pathological scan with thousands of per-file failures still produces one large `details.failed_files` array. Cap `details.failed_files` at 500 entries with a trailing `truncated: true` flag.
- Retention `min=1` allows an admin to accidentally set retention so short that errors disappear before they are seen. Acceptable: the setting is admin-only.
- The error toast poller adds one HTTP request every 10 seconds per client. Negligible at expected scale.

## Acceptance checklist

- Every existing activity write site calls `emit()` rather than pushing to the Redis list.
- Every event site identified in the backfill table writes through `emit()`.
- The Dashboard Activity card renders Now Running and History regions as specified, with severity and category filters.
- Active jobs from scan, rebuild, and at least one Celery task (merges duplicate detection) appear in Now Running simultaneously without visual regression.
- User-initiated actions toast on completion; background non-error events do not toast.
- Background errors trigger a toast regardless of current page.
- Admin Settings page exposes `activity_retention_days` and the Clear button.
- Pruner runs nightly and deletes rows older than the configured window.
- Old `/scan/activity` endpoints are removed. Old Redis key is deleted on startup.
