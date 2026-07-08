"""Shared structured-progress envelope helper.

Phase 3 of docs/retrofit-roadmap.md ("Structured progress envelope") unifies
the two existing progress mechanisms in scan_state.py (the scan counters and
the rebuild free-form message) behind a single wire shape:
{task, step, total_steps, percent, message} -- see
app.schemas.scan.ProgressEnvelope.

Design decisions made for Task 1 of that phase (SONNET design task, reviewed
before T2/T3 wire their call sites):

- No new Redis key scheme. ``set_progress``/``get_progress`` write/read four
  fields -- ``task``, ``step``, ``total_steps``, ``message`` -- directly onto
  whichever hash the caller already owns: scan_state.SCAN_KEY ("scan:state")
  for scan progress, scan_state.REBUILD_KEY ("rebuild:status") for rebuild
  progress. A second, separate hash per running job would risk drifting out
  of sync with the mechanism-specific state fields (state/completed/failed
  for scan, state/mode/details for rebuild) that already live on those keys.
  On rebuild:status this also means the envelope's ``message`` field *is*
  the same field RebuildStatus.message already reads/writes -- one message,
  not two copies of it.
- ``percent`` is never persisted. It is derived at read time from
  step/total_steps (0.0 when total_steps <= 0), so the DataJob model's
  "derived, not stored" docstring (app/models/data_job.py) and the roadmap's
  literal {task, step, total_steps, percent, message} field list are both
  satisfied: percent is a real field in the emitted envelope, just never a
  stored Redis field or DB column.
- percent is on a 0-100 scale, float, rounded to one decimal place.
- Existing granular scan counters (completed/failed/total in
  scan_state.ScanStateSnapshot) are untouched by this module -- T3 decides
  separately how/whether scan call sites populate step/total_steps.

``set_progress`` is sync-only because both scan and rebuild progress writers
run inside Celery workers (see scan_state.py's "Sync API" section). Two
reader variants are provided, mirroring scan_state.py's existing
async-for-FastAPI / sync-for-Celery split:

- ``get_progress`` (async) for FastAPI request handlers.
- ``get_progress_sync`` for Celery workers or other sync callers.

This task defines the schema and helper only. Wiring scan/rebuild call
sites in worker/tasks.py and the scan/rebuild-status API responses is
deliberately out of scope here (separate roadmap tasks).
"""

import redis.asyncio as aioredis
import redis as sync_redis

from app.schemas.scan import ProgressEnvelope

__all__ = ["set_progress", "get_progress", "get_progress_sync"]


def _envelope_from_hash(data: dict | None) -> ProgressEnvelope:
    data = data or {}
    return ProgressEnvelope.for_progress(
        task=data.get("task", ""),
        step=int(data.get("step", 0) or 0),
        total_steps=int(data.get("total_steps", 0) or 0),
        message=data.get("message", ""),
    )


# ── Sync API (for Celery worker) ─────────────────────────────────────────

def set_progress(
    r: sync_redis.Redis,
    key: str,
    task: str,
    step: int,
    total_steps: int,
    message: str,
) -> None:
    """Write task/step/total_steps/message onto an existing progress hash.

    ``key`` is the caller's own Redis hash key (e.g. scan_state.SCAN_KEY or
    scan_state.REBUILD_KEY) -- this layers the generic envelope fields onto
    whichever hash the caller already maintains, rather than introducing a
    new key scheme. Any other fields already on that hash are left alone.
    """
    r.hset(key, mapping={
        "task": task,
        "step": step,
        "total_steps": total_steps,
        "message": message,
    })


def get_progress_sync(r: sync_redis.Redis, key: str) -> ProgressEnvelope:
    return _envelope_from_hash(r.hgetall(key))


# ── Async API (for FastAPI) ──────────────────────────────────────────────

async def get_progress(r: aioredis.Redis, key: str) -> ProgressEnvelope:
    data = await r.hgetall(key)
    return _envelope_from_hash(data)
