"""Redis-backed scan state manager.

Keys used:
  scan:state   - hash with fields: state, total, completed, failed, started_at, completed_at
  scan:state is set to expire after 24h on completion so old results don't linger forever.

Phase 3 of docs/retrofit-roadmap.md ("Structured progress envelope") layers
task/step/total_steps/message onto this same scan:state hash via
app.services.progress_envelope.set_progress, additively alongside the
counters above (completed/failed/total etc. stay the source of truth for
the scan_complete activity summary - see check_complete_sync). percent is
never stored; it's derived at read time in parse_snapshot. The discovery
phase (start_scanning_sync/set_discovered_sync) has no fixed total, so it
reports an indeterminate 0/0 rather than a fake total - the real total
appears once set_ingesting_sync runs.
"""

import logging
import time
from dataclasses import dataclass

import redis.asyncio as aioredis
import redis as sync_redis
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _SyncSession

from app.services.activity import emit_sync

logger = logging.getLogger(__name__)

SCAN_KEY = "scan:state"
SCAN_PROGRESS_KEY = "scan:last_progress"
SCAN_FAILED_KEY = "scan:failed_files"
SCAN_CANCEL_KEY = "scan:cancel"
SCAN_ACTIVITY_KEY = "scan:activity"
SCAN_ACTIVITY_MAX = 20
SCAN_SKIPPED_PATHS_KEY = "scan:skipped_paths"
# Backstop TTL for the skipped-paths set. Membership is normally kept accurate
# by rebuild_skipped_paths_sync() on every full scan (dropping entries for
# files no longer on disk), but the TTL guarantees the set cannot grow
# unbounded forever even if a scan is never re-run with calibration excluded.
SCAN_SKIPPED_PATHS_TTL = 7 * 86400  # 7 days
# Short-lived marker set inside trigger_scan's lock, between the idle/active
# check and the `run_scan.delay()` dispatch (AUD-016). Closes the window where
# a second POST arrives after the dispatch lock is released but before the
# queued run_scan task is picked up and calls start_scanning_sync - without
# this, get_scan_state() would still report "idle"/"complete" and a second
# scan would be dispatched. TTL is generous vs. typical worker pickup latency
# but short enough not to wedge scan state if the broker/worker never picks
# the task up at all.
SCAN_DISPATCHED_KEY = "scan:dispatched"
SCAN_DISPATCHED_TTL = 60  # seconds
EXPIRE_AFTER_COMPLETE = 86400  # 24 hours
STALE_TIMEOUT = 300  # 5 minutes with no progress → consider stuck


@dataclass
class ScanStateSnapshot:
    state: str  # idle | scanning | ingesting | complete
    total: int
    completed: int
    failed: int
    started_at: float | None
    completed_at: float | None
    csv_enriched: int = 0
    discovered: int = 0
    removed: int = 0
    skipped_calibration: int = 0
    new_files: int = 0
    changed_files: int = 0
    # Phase 3 structured progress envelope (task/step/total_steps/percent/
    # message) - additive fields layered onto this same hash, alongside the
    # counters above which stay the source of truth for the scan_complete
    # activity summary. percent is always derived from step/total_steps at
    # read time, never stored (see app.services.progress_envelope).
    task: str = ""
    step: int = 0
    total_steps: int = 0
    percent: float = 0.0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "csv_enriched": self.csv_enriched,
            "discovered": self.discovered,
            "removed": self.removed,
            "skipped_calibration": self.skipped_calibration,
            "new_files": self.new_files,
            "changed_files": self.changed_files,
            "task": self.task,
            "step": self.step,
            "total_steps": self.total_steps,
            "percent": self.percent,
            "message": self.message,
        }


def parse_snapshot(data: dict | None) -> ScanStateSnapshot:
    if not data or "state" not in data:
        return ScanStateSnapshot(
            state="idle", total=0, completed=0, failed=0,
            started_at=None, completed_at=None,
        )
    from app.schemas.scan import ProgressEnvelope

    step = int(data.get("step", 0) or 0)
    total_steps = int(data.get("total_steps", 0) or 0)
    task = data.get("task", "")
    message = data.get("message", "")
    percent = ProgressEnvelope.for_progress(
        task=task, step=step, total_steps=total_steps, message=message,
    ).percent

    return ScanStateSnapshot(
        state=data.get("state", "idle"),
        total=int(data.get("total", 0)),
        completed=int(data.get("completed", 0)),
        failed=int(data.get("failed", 0)),
        started_at=float(data["started_at"]) if data.get("started_at") else None,
        completed_at=float(data["completed_at"]) if data.get("completed_at") else None,
        csv_enriched=int(data.get("csv_enriched", 0)),
        discovered=int(data.get("discovered", 0)),
        removed=int(data.get("removed", 0)),
        skipped_calibration=int(data.get("skipped_calibration", 0)),
        new_files=int(data.get("new_files", 0)),
        changed_files=int(data.get("changed_files", 0)),
        task=task,
        step=step,
        total_steps=total_steps,
        percent=percent,
        message=message,
    )


def _ingest_progress_message(kind: str, step: int, total: int) -> str:
    """Human-readable ingest-progress message; unit depends on ``kind``.

    ``kind`` distinguishes a real directory scan ("scan") from other work
    reusing this same hash (currently only "csv_backfill") - see
    set_ingesting_sync's docstring. Shared by set_ingesting_sync (initial
    0/total message) and check_complete_sync (each incremental update).
    """
    if kind == "csv_backfill":
        noun = "directory" if total == 1 else "directories"
        return f"Backfilling CSV metrics: {step}/{total} {noun}"
    noun = "file" if total == 1 else "files"
    return f"Ingesting {step}/{total} {noun}"


# ── Async API (for FastAPI) ──────────────────────────────────────────────

async def get_scan_state(r: aioredis.Redis) -> ScanStateSnapshot:
    data = await r.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    # Detect stale ingestion: no progress for STALE_TIMEOUT seconds
    if snap.state in ("scanning", "ingesting"):
        last_progress = await r.get(SCAN_PROGRESS_KEY)
        if last_progress:
            elapsed = time.time() - float(last_progress)
            if elapsed > STALE_TIMEOUT:
                snap.state = "stalled"
    elif await r.exists(SCAN_DISPATCHED_KEY):
        # A scan was just dispatched (inside trigger_scan's lock) but the
        # worker hasn't picked it up yet, so scan:state still reads
        # idle/complete. Report it as active so a second request doesn't
        # race in and dispatch a duplicate scan (AUD-016).
        snap.state = "scanning"
    return snap


async def mark_scan_dispatched(r: aioredis.Redis) -> None:
    """Record that a scan was just queued, before the worker has started it.

    Set inside trigger_scan's dispatch lock, immediately before
    ``run_scan.delay()``. Cleared (implicitly, via TTL) once
    ``start_scanning_sync`` writes the real "scanning" state, or after
    ``SCAN_DISPATCHED_TTL`` seconds if the task is never picked up.
    """
    await r.set(SCAN_DISPATCHED_KEY, "1", ex=SCAN_DISPATCHED_TTL)


async def get_failed_files(r: aioredis.Redis) -> list[dict]:
    """Return list of {file, error} dicts for files that failed during this scan."""
    import json
    raw = await r.lrange(SCAN_FAILED_KEY, 0, -1)
    return [json.loads(item) for item in raw]


async def start_scanning(r: aioredis.Redis) -> None:
    await r.hset(SCAN_KEY, mapping={
        "state": "scanning",
        "total": 0,
        "completed": 0,
        "failed": 0,
        "started_at": time.time(),
        "completed_at": "",
    })
    await r.set(SCAN_PROGRESS_KEY, str(time.time()))
    await r.persist(SCAN_KEY)  # remove any previous TTL
    await r.delete(SCAN_FAILED_KEY)  # clear previous failures


async def set_ingesting(r: aioredis.Redis, total: int) -> None:
    await r.hset(SCAN_KEY, mapping={
        "state": "ingesting",
        "total": total,
    })


async def set_complete_if_done(r: aioredis.Redis) -> None:
    """Check if all tasks finished and transition to complete."""
    data = await r.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    if snap.state == "ingesting" and snap.total > 0 and (snap.completed + snap.failed) >= snap.total:
        await r.hset(SCAN_KEY, mapping={
            "state": "complete",
            "completed_at": time.time(),
        })
        await r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)


async def request_cancel(r: aioredis.Redis) -> None:
    """Set the cancel flag so the worker stops processing."""
    await r.set(SCAN_CANCEL_KEY, "1", ex=600)  # auto-expire after 10 min


async def reset_scan(r: aioredis.Redis) -> None:
    """Force-clear scan state back to idle. Used when scan is stalled."""
    await r.delete(SCAN_KEY)
    await r.delete(SCAN_PROGRESS_KEY)
    await r.delete(SCAN_FAILED_KEY)
    await r.delete(SCAN_CANCEL_KEY)
    # Also clear any stuck rebuild/reference-thumbnail state so a rebuild that
    # was hard-killed mid-run (leaving REBUILD_KEY at "running" with no TTL) has
    # a recovery path from the UI instead of requiring a manual Redis edit
    # (AUD-003).
    await r.delete(REBUILD_KEY)
    await r.delete(REBUILD_PROGRESS_KEY)


async def get_activity(r: aioredis.Redis) -> list[dict]:
    """Return activity log entries (newest first)."""
    import json
    raw = await r.lrange(SCAN_ACTIVITY_KEY, 0, -1)
    return [json.loads(item) for item in raw]


async def clear_activity(r: aioredis.Redis) -> None:
    """Clear the activity log."""
    await r.delete(SCAN_ACTIVITY_KEY)


async def append_activity(r: aioredis.Redis, entry: dict) -> None:
    """Append an activity entry (newest first) and cap at SCAN_ACTIVITY_MAX."""
    import json
    await r.lpush(SCAN_ACTIVITY_KEY, json.dumps(entry))
    await r.ltrim(SCAN_ACTIVITY_KEY, 0, SCAN_ACTIVITY_MAX - 1)


async def set_idle(r: aioredis.Redis) -> None:
    """Mark scan as complete with zero files (nothing to do)."""
    await r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "total": 0,
        "completed_at": time.time(),
    })
    await r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)


# ── Sync API (for Celery worker) ─────────────────────────────────────────

def increment_completed_sync(r: sync_redis.Redis) -> None:
    r.hincrby(SCAN_KEY, "completed", 1)
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    check_complete_sync(r)


def increment_skipped_calibration_sync(r: sync_redis.Redis) -> None:
    r.hincrby(SCAN_KEY, "skipped_calibration", 1)


def increment_failed_sync(r: sync_redis.Redis, file_path: str = "", error: str = "") -> None:
    r.hincrby(SCAN_KEY, "failed", 1)
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    if file_path:
        import json
        r.rpush(SCAN_FAILED_KEY, json.dumps({"file": file_path, "error": error}))
    check_complete_sync(r)


def check_complete_sync(r: sync_redis.Redis) -> None:
    from app.services.progress_envelope import set_progress

    data = r.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    if snap.state != "ingesting" or snap.total <= 0:
        return
    kind = data.get("kind", "scan")
    step = snap.completed + snap.failed
    if step < snap.total:
        # Not done yet - just move the envelope's step forward so the
        # frontend progress bar tracks completed+failed incrementally
        # (called on every increment_completed_sync/increment_failed_sync).
        set_progress(
            r, SCAN_KEY, task=kind, step=step, total_steps=snap.total,
            message=_ingest_progress_message(kind, step, snap.total),
        )
        return
    r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "completed_at": time.time(),
    })
    r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)
    if kind != "scan":
        # Non-scan ingestion (e.g. CSV metrics backfill) reuses this same
        # progress hash to track its own total/completed/failed counts,
        # but reaching "complete" here is not a real scan finishing: it
        # must not emit the scan_complete activity or dispatch the
        # post-scan maintenance cascade (smart_rebuild, reference
        # thumbnails, mosaic/duplicate detection, dark-hours backfill).
        # See AUD-030.
        try:
            r.delete("galactilog:stats:cache", "galactilog:fits_keys")
        except Exception:
            logger.debug("scan_state: Redis stats cache invalidation failed", exc_info=True)
        set_progress(
            r, SCAN_KEY, task=kind, step=snap.total, total_steps=snap.total,
            message=_ingest_progress_message(kind, snap.total, snap.total),
        )
        return
    parts = []
    actual_new = max(0, snap.new_files - snap.skipped_calibration)
    if actual_new:
        parts.append(f"{actual_new} new file{'s' if actual_new != 1 else ''} added")
    if snap.skipped_calibration:
        parts.append(f"{snap.skipped_calibration} calibration frame{'s' if snap.skipped_calibration != 1 else ''} skipped")
    if snap.changed_files:
        parts.append(f"{snap.changed_files} changed file{'s' if snap.changed_files != 1 else ''} re-ingested")
    if snap.failed:
        parts.append(f"{snap.failed} failed")
    if snap.csv_enriched:
        parts.append(f"{snap.csv_enriched} CSV enriched")
    if snap.removed:
        parts.append(f"{snap.removed} deleted file{'s' if snap.removed != 1 else ''} purged")
    msg = "Scan complete: " + (", ".join(parts) if parts else "no changes")
    # Envelope reaches 100% here, reusing the exact same human-readable
    # summary as the scan_complete activity below - one message, not two
    # divergent copies (roadmap: "notification text unchanged in readability").
    set_progress(
        r, SCAN_KEY, task="scan", step=snap.total, total_steps=snap.total,
        message=msg,
    )
    scan_activity_id = None
    try:
        from app.config import settings as _cfg
        _engine = create_engine(
            _cfg.database_url.replace("+asyncpg", "+psycopg2"),
            pool_pre_ping=True,
        )
        with _SyncSession(_engine) as _db:
            scan_activity_id = emit_sync(
                _db, redis=r, category="scan", severity="info",
                event_type="scan_complete", message=msg,
                details={
                    "completed": snap.completed, "failed": snap.failed,
                    "skipped_calibration": snap.skipped_calibration,
                    "csv_enriched": snap.csv_enriched, "total": snap.total,
                    "removed": snap.removed, "new_files": snap.new_files,
                    "changed_files": snap.changed_files,
                },
                actor="system",
            )
            if snap.failed > 0:
                import json as _json
                raw = r.lrange(SCAN_FAILED_KEY, 0, -1)
                failed_files = []
                for item in raw[:500]:
                    try:
                        entry = _json.loads(item)
                        failed_files.append({
                            "path": entry.get("file", ""),
                            "reason": entry.get("error", ""),
                        })
                    except Exception:
                        logger.debug("scan_state: failed to parse failed-file entry: %r", item, exc_info=True)
                from app.config import settings as _cfg2
                thumb_root = _cfg2.thumbnails_path
                thumb_failures = [f for f in failed_files if f["path"].startswith(thumb_root)]
                fits_failures = [f for f in failed_files if not f["path"].startswith(thumb_root)]

                if thumb_failures:
                    emit_sync(
                        _db, redis=r, category="thumbnail", severity="warning",
                        event_type="thumbnail_regen_failed",
                        message=f"Thumbnail regen: {len(thumb_failures)} failure{'s' if len(thumb_failures) != 1 else ''}",
                        details={"failed_files": thumb_failures, "truncated": len(raw) > 500},
                        actor="system",
                        parent_id=scan_activity_id,
                    )
                if fits_failures:
                    emit_sync(
                        _db, redis=r, category="scan", severity="warning",
                        event_type="scan_files_failed",
                        message=f"Scan completed with {len(fits_failures)} file failure{'s' if len(fits_failures) != 1 else ''}",
                        details={"failed_files": fits_failures, "truncated": len(raw) > 500},
                        actor="system",
                        parent_id=scan_activity_id,
                    )
    except Exception:
        logger.exception("scan_state: failed to emit scan_complete activity")
    # Invalidate stats cache immediately so the next request gets fresh data
    try:
        r.delete("galactilog:stats:cache", "galactilog:fits_keys")
    except Exception:
        logger.debug("scan_state: Redis stats cache invalidation failed", exc_info=True)
    # Chain post-scan maintenance tasks
    from app.worker.tasks import (
        smart_rebuild_targets, detect_mosaic_panels_task,
        generate_reference_thumbnails, detect_duplicate_targets,
        backfill_dark_hours,
    )
    smart_rebuild_targets.apply_async(countdown=10, kwargs={"parent_activity_id": scan_activity_id})
    generate_reference_thumbnails.apply_async(countdown=20, kwargs={"parent_activity_id": scan_activity_id})
    detect_mosaic_panels_task.apply_async(countdown=30, kwargs={"parent_activity_id": scan_activity_id})
    detect_duplicate_targets.apply_async(countdown=30, kwargs={"parent_activity_id": scan_activity_id})
    backfill_dark_hours.apply_async(countdown=45, kwargs={"parent_activity_id": scan_activity_id})
    # Write initial scan summary to Redis for /scan/summary endpoint
    try:
        import json as _json
        from datetime import datetime as _dt
        _summary = {
            "completed_at": _dt.utcnow().isoformat() + "Z",
            "files_ingested": snap.completed,
            "targets_created": 0,
            "targets_updated": 0,
            "duplicates_found": 0,
            "unresolved_names": 0,
            "errors": snap.failed,
        }
        r.set("galactilog:scan_summary", _json.dumps(_summary))
    except Exception:
        logger.exception("scan_state: failed to write scan_summary to Redis")


def start_scanning_sync(r: sync_redis.Redis) -> None:
    r.hset(SCAN_KEY, mapping={
        "state": "scanning",
        "total": 0,
        "completed": 0,
        "failed": 0,
        "new_files": 0,
        "changed_files": 0,
        "removed": 0,
        "csv_enriched": 0,
        "skipped_calibration": 0,
        "started_at": time.time(),
        "completed_at": "",
        "kind": "scan",
    })
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    r.persist(SCAN_KEY)
    r.delete(SCAN_FAILED_KEY)
    r.delete(SCAN_DISPATCHED_KEY)  # real state has taken over from the dispatch marker
    # Reset the progress envelope unconditionally so a new scan can never
    # inherit the previous run's step/total_steps/percent from the
    # still-persisted scan:state hash (same rationale as
    # set_rebuild_running_sync). Discovery hasn't counted files yet, so
    # total_steps is genuinely unknown here - 0/0 (indeterminate) rather
    # than a fake total; set_ingesting_sync fills in the real total once
    # discovery finishes.
    from app.services.progress_envelope import set_progress
    set_progress(r, SCAN_KEY, task="scan", step=0, total_steps=0, message="Discovering files...")


def set_ingesting_sync(
    r: sync_redis.Redis,
    total: int,
    removed: int = 0,
    new_files: int = 0,
    changed_files: int = 0,
    kind: str = "scan",
) -> None:
    """Transition scan:state to "ingesting".

    ``kind`` distinguishes a real directory scan ("scan", the default) from
    other work that reuses this same progress-tracking hash, such as the CSV
    metrics backfill ("csv_backfill"). ``check_complete_sync`` reads it back
    to decide whether reaching "complete" should emit the scan_complete
    activity and dispatch the post-scan maintenance cascade (AUD-030).
    ``kind`` also doubles as the progress envelope's ``task`` field - one
    less field to keep in sync, since both distinguish the exact same thing.
    """
    r.hset(SCAN_KEY, mapping={
        "state": "ingesting",
        "total": total,
        "removed": removed,
        "new_files": new_files,
        "changed_files": changed_files,
        "kind": kind,
    })
    from app.services.progress_envelope import set_progress
    set_progress(
        r, SCAN_KEY, task=kind, step=0, total_steps=total,
        message=_ingest_progress_message(kind, 0, total),
    )


def increment_csv_enriched_sync(r: sync_redis.Redis) -> None:
    r.hincrby(SCAN_KEY, "csv_enriched", 1)


def add_skipped_path_sync(r: sync_redis.Redis, path: str) -> None:
    """Track a calibration/skipped file path so it's excluded from future scans."""
    r.sadd(SCAN_SKIPPED_PATHS_KEY, path)
    # Refresh the backstop TTL on every write so a set that keeps getting new
    # members during a long scan doesn't expire mid-scan.
    r.expire(SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL)


def get_skipped_paths_sync(r: sync_redis.Redis) -> set[str]:
    """Return all previously skipped file paths."""
    return {p.decode() if isinstance(p, bytes) else p for p in r.smembers(SCAN_SKIPPED_PATHS_KEY)}


def clear_skipped_paths_sync(r: sync_redis.Redis) -> None:
    """Clear skipped paths cache (e.g. when include_calibration setting changes)."""
    r.delete(SCAN_SKIPPED_PATHS_KEY)


def rebuild_skipped_paths_sync(r: sync_redis.Redis, paths: set[str]) -> None:
    """Replace the skipped-paths set with exactly ``paths``, with TTL backstop.

    Called once per full scan (when calibration is excluded) after checking
    which previously-skipped paths still exist on disk, so entries for files
    that were deleted or moved don't linger in the set forever. Always sets
    the 7-day TTL backstop, even for an empty rebuild, so an unrelated
    long-lived key can't survive without one.
    """
    pipe = r.pipeline()
    pipe.delete(SCAN_SKIPPED_PATHS_KEY)
    if paths:
        pipe.sadd(SCAN_SKIPPED_PATHS_KEY, *paths)
        pipe.expire(SCAN_SKIPPED_PATHS_KEY, SCAN_SKIPPED_PATHS_TTL)
    pipe.execute()


def set_idle_sync(r: sync_redis.Redis) -> None:
    """Mark scan as complete with zero files (nothing to do).

    Reached without ever calling set_ingesting_sync, so there's no
    meaningful step/total to report - the envelope resets to indeterminate
    0/0 rather than forcing a fake total, matching the "no fixed total"
    treatment used for the discovery phase.
    """
    r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "total": 0,
        "completed_at": time.time(),
    })
    r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)
    from app.services.progress_envelope import set_progress
    set_progress(r, SCAN_KEY, task="scan", step=0, total_steps=0, message="No files to process")


def set_discovered_sync(r: sync_redis.Redis, count: int) -> None:
    r.hset(SCAN_KEY, "discovered", count)
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    # Discovery phase has no fixed total (files aren't counted as a
    # denominator until set_ingesting_sync knows the real total), so the
    # envelope stays at 0/0 - only the message is refreshed to surface the
    # running discovery count.
    from app.services.progress_envelope import set_progress
    set_progress(
        r, SCAN_KEY, task="scan", step=0, total_steps=0,
        message=f"Discovered {count} file{'s' if count != 1 else ''} so far",
    )


def is_cancel_requested_sync(r: sync_redis.Redis) -> bool:
    return r.exists(SCAN_CANCEL_KEY) == 1


def clear_cancel_sync(r: sync_redis.Redis) -> None:
    r.delete(SCAN_CANCEL_KEY)


def set_cancelled_sync(r: sync_redis.Redis) -> None:
    r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "completed_at": time.time(),
    })
    r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)
    r.delete(SCAN_CANCEL_KEY)
    # Cancellation is a terminal state, same "no fixed total" treatment as
    # set_idle_sync above - reset to indeterminate rather than trying to
    # reverse-engineer a final step count from whatever the counters
    # happened to reach when the cancel was requested.
    from app.services.progress_envelope import set_progress
    set_progress(r, SCAN_KEY, task="scan", step=0, total_steps=0, message="Cancelled")


# ── Rebuild status (Quick Fix / Full Rebuild) ────────────────────────────

REBUILD_KEY = "rebuild:status"
REBUILD_PROGRESS_KEY = "rebuild:last_progress"
REBUILD_EXPIRE = 3600  # 1 hour
# Rebuild-family maintenance tasks (Full Rebuild, Retry Unresolved, reference
# thumbnails) are legitimately long-running, so a short started_at-based timeout
# like get_scan_state uses would flag a healthy run as stalled. Instead they
# write REBUILD_PROGRESS_KEY on every incremental progress update, and a run is
# considered stalled only after this generous no-progress window elapses. This
# is the backstop for a worker that is hard-killed (SIGKILL/OOM) without the
# SoftTimeLimitExceeded handler getting a chance to write a terminal state
# (AUD-003).
REBUILD_STALE_TIMEOUT = 900  # 15 minutes with no progress → consider stuck


@dataclass
class RebuildStatus:
    state: str  # idle | running | complete | error
    mode: str  # smart | full
    message: str
    started_at: float | None
    completed_at: float | None
    details: dict
    step: int | None = None
    total_steps: int | None = None
    percent: float | None = None

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "mode": self.mode,
            "message": self.message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "details": self.details,
            "step": self.step,
            "total_steps": self.total_steps,
            "percent": self.percent,
        }


def _parse_rebuild(data: dict | None) -> RebuildStatus:
    if not data or "state" not in data:
        return RebuildStatus(
            state="idle", mode="", message="", started_at=None,
            completed_at=None, details={}, step=None, total_steps=None, percent=None,
        )
    import json
    from app.schemas.scan import ProgressEnvelope

    # Derive percent from step/total_steps (never stored directly), reusing
    # the envelope's own derivation so the formula lives in one place.
    step = int(data.get("step", 0) or 0)
    total_steps = int(data.get("total_steps", 0) or 0)
    percent = ProgressEnvelope.for_progress(
        task=data.get("task", ""), step=step, total_steps=total_steps,
        message=data.get("message", ""),
    ).percent

    return RebuildStatus(
        state=data.get("state", "idle"),
        mode=data.get("mode", ""),
        message=data.get("message", ""),
        started_at=float(data["started_at"]) if data.get("started_at") else None,
        completed_at=float(data["completed_at"]) if data.get("completed_at") else None,
        details=json.loads(data["details"]) if data.get("details") else {},
        step=step if step >= 0 else None,
        total_steps=total_steps if total_steps >= 0 else None,
        percent=percent,
    )


async def get_rebuild_state(r: aioredis.Redis) -> RebuildStatus:
    data = await r.hgetall(REBUILD_KEY)
    snap = _parse_rebuild(data)
    # Detect a stuck rebuild: state is still "running" but no incremental
    # progress has been written for REBUILD_STALE_TIMEOUT seconds. This covers
    # the case where the worker was hard-killed before the SoftTimeLimitExceeded
    # handler could persist a terminal state, so the status hash would otherwise
    # read "running" forever with no TTL (AUD-003).
    if snap.state == "running":
        last_progress = await r.get(REBUILD_PROGRESS_KEY)
        reference = None
        if last_progress:
            reference = float(last_progress)
        elif snap.started_at:
            reference = snap.started_at
        if reference is not None and (time.time() - reference) > REBUILD_STALE_TIMEOUT:
            snap.state = "stalled"
    return snap


def set_rebuild_running_sync(
    r: sync_redis.Redis, mode: str, message: str,
    task: str | None = None, step: int = 0, total_steps: int = 0,
) -> None:
    """Set rebuild state to running and reset the progress envelope.

    The envelope fields (task/step/total_steps) are always rewritten here:
    rebuild:status persists for REBUILD_EXPIRE seconds after a run, so a new
    run must not inherit the previous run's step/total_steps/percent. task
    defaults to mode (e.g. "full", "retry", "backfill", "smart",
    "ref_thumbnails") unless overridden; step/total_steps default to 0 when
    the run's step count is not yet known. The message is written once, via
    set_progress.
    """
    from app.services.progress_envelope import set_progress

    r.hset(REBUILD_KEY, mapping={
        "state": "running",
        "mode": mode,
        "started_at": time.time(),
        "completed_at": "",
        "details": "{}",
    })
    r.persist(REBUILD_KEY)
    r.set(REBUILD_PROGRESS_KEY, str(time.time()))
    set_progress(
        r, REBUILD_KEY, task=task if task is not None else mode,
        step=step, total_steps=total_steps, message=message,
    )


def set_rebuild_progress_sync(
    r: sync_redis.Redis, message: str,
    task: str | None = None, step: int | None = None, total_steps: int | None = None,
) -> None:
    """Update rebuild message and progress, optionally with envelope fields.

    If task/step/total_steps are provided, the message and the envelope
    fields are written together via the structured progress envelope
    (Phase 3); otherwise only the message is updated. The message wording is
    caller-controlled and stays human-readable for notifications.
    """
    from app.services.progress_envelope import set_progress

    if task is not None and step is not None and total_steps is not None:
        set_progress(r, REBUILD_KEY, task=task, step=step, total_steps=total_steps, message=message)
    else:
        r.hset(REBUILD_KEY, "message", message)
    # Heartbeat for stale detection: every incremental progress write bumps the
    # last-progress marker so get_rebuild_state can tell a slow-but-alive run
    # from a hard-killed one (AUD-003).
    r.set(REBUILD_PROGRESS_KEY, str(time.time()))


def set_rebuild_complete_sync(
    r: sync_redis.Redis, message: str, details: dict,
    task: str | None = None, step: int | None = None, total_steps: int | None = None,
) -> None:
    """Complete rebuild, optionally with progress envelope fields at completion.

    If task/step/total_steps are provided, marks progress as fully complete
    (step == total_steps) via the structured progress envelope (Phase 3);
    the message is then written once, through set_progress.
    """
    from app.services.progress_envelope import set_progress
    import json

    mapping = {
        "state": "complete",
        "completed_at": time.time(),
        "details": json.dumps(details),
    }
    if task is None or step is None or total_steps is None:
        mapping["message"] = message
    r.hset(REBUILD_KEY, mapping=mapping)
    if task is not None and step is not None and total_steps is not None:
        set_progress(r, REBUILD_KEY, task=task, step=step, total_steps=total_steps, message=message)
    r.expire(REBUILD_KEY, REBUILD_EXPIRE)
    r.delete(REBUILD_PROGRESS_KEY)


def set_rebuild_cancelled_sync(
    r: sync_redis.Redis,
    message: str = "Cancelled by user",
    details: dict | None = None,
) -> None:
    import json
    r.hset(REBUILD_KEY, mapping={
        "state": "cancelled",
        "message": message,
        "completed_at": time.time(),
        "details": json.dumps(details or {}),
    })
    r.expire(REBUILD_KEY, EXPIRE_AFTER_COMPLETE)
    r.delete(REBUILD_PROGRESS_KEY)
    clear_cancel_sync(r)
