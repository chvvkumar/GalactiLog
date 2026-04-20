"""Redis-backed scan state manager.

Keys used:
  scan:state   - hash with fields: state, total, completed, failed, started_at, completed_at
  scan:state is set to expire after 24h on completion so old results don't linger forever.
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
        }


def parse_snapshot(data: dict | None) -> ScanStateSnapshot:
    if not data or "state" not in data:
        return ScanStateSnapshot(
            state="idle", total=0, completed=0, failed=0,
            started_at=None, completed_at=None,
        )
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
    )


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
    return snap


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
    data = r.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    if snap.state == "ingesting" and snap.total > 0 and (snap.completed + snap.failed) >= snap.total:
        r.hset(SCAN_KEY, mapping={
            "state": "complete",
            "completed_at": time.time(),
        })
        r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)
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
        try:
            from app.config import settings as _cfg
            _engine = create_engine(
                _cfg.database_url.replace("+asyncpg", "+psycopg2"),
                pool_pre_ping=True,
            )
            with _SyncSession(_engine) as _db:
                emit_sync(
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
                            pass
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
                        )
                    if fits_failures:
                        emit_sync(
                            _db, redis=r, category="scan", severity="warning",
                            event_type="scan_files_failed",
                            message=f"Scan completed with {len(fits_failures)} file failure{'s' if len(fits_failures) != 1 else ''}",
                            details={"failed_files": fits_failures, "truncated": len(raw) > 500},
                            actor="system",
                        )
        except Exception:
            logger.exception("scan_state: failed to emit scan_complete activity")
        # Invalidate stats cache immediately so the next request gets fresh data
        try:
            r.delete("galactilog:stats:cache", "galactilog:fits_keys")
        except Exception:
            pass
        # Chain post-scan maintenance tasks
        from app.worker.tasks import smart_rebuild_targets, detect_mosaic_panels_task
        smart_rebuild_targets.apply_async(countdown=10)
        detect_mosaic_panels_task.apply_async(countdown=30)
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
    })
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    r.persist(SCAN_KEY)
    r.delete(SCAN_FAILED_KEY)


def set_ingesting_sync(r: sync_redis.Redis, total: int, removed: int = 0, new_files: int = 0, changed_files: int = 0) -> None:
    r.hset(SCAN_KEY, mapping={
        "state": "ingesting",
        "total": total,
        "removed": removed,
        "new_files": new_files,
        "changed_files": changed_files,
    })


def increment_csv_enriched_sync(r: sync_redis.Redis) -> None:
    r.hincrby(SCAN_KEY, "csv_enriched", 1)


def add_skipped_path_sync(r: sync_redis.Redis, path: str) -> None:
    """Track a calibration/skipped file path so it's excluded from future scans."""
    r.sadd(SCAN_SKIPPED_PATHS_KEY, path)


def get_skipped_paths_sync(r: sync_redis.Redis) -> set[str]:
    """Return all previously skipped file paths."""
    return {p.decode() if isinstance(p, bytes) else p for p in r.smembers(SCAN_SKIPPED_PATHS_KEY)}


def clear_skipped_paths_sync(r: sync_redis.Redis) -> None:
    """Clear skipped paths cache (e.g. when include_calibration setting changes)."""
    r.delete(SCAN_SKIPPED_PATHS_KEY)


def set_idle_sync(r: sync_redis.Redis) -> None:
    r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "total": 0,
        "completed_at": time.time(),
    })
    r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)


def set_discovered_sync(r: sync_redis.Redis, count: int) -> None:
    r.hset(SCAN_KEY, "discovered", count)
    r.set(SCAN_PROGRESS_KEY, str(time.time()))


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


# ── Rebuild status (Quick Fix / Full Rebuild) ────────────────────────────

REBUILD_KEY = "rebuild:status"
REBUILD_EXPIRE = 3600  # 1 hour


@dataclass
class RebuildStatus:
    state: str  # idle | running | complete | error
    mode: str  # smart | full
    message: str
    started_at: float | None
    completed_at: float | None
    details: dict

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "mode": self.mode,
            "message": self.message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "details": self.details,
        }


def _parse_rebuild(data: dict | None) -> RebuildStatus:
    if not data or "state" not in data:
        return RebuildStatus(
            state="idle", mode="", message="", started_at=None,
            completed_at=None, details={},
        )
    import json
    return RebuildStatus(
        state=data.get("state", "idle"),
        mode=data.get("mode", ""),
        message=data.get("message", ""),
        started_at=float(data["started_at"]) if data.get("started_at") else None,
        completed_at=float(data["completed_at"]) if data.get("completed_at") else None,
        details=json.loads(data["details"]) if data.get("details") else {},
    )


async def get_rebuild_state(r: aioredis.Redis) -> RebuildStatus:
    data = await r.hgetall(REBUILD_KEY)
    return _parse_rebuild(data)


def set_rebuild_running_sync(r: sync_redis.Redis, mode: str, message: str) -> None:
    r.hset(REBUILD_KEY, mapping={
        "state": "running",
        "mode": mode,
        "message": message,
        "started_at": time.time(),
        "completed_at": "",
        "details": "{}",
    })
    r.persist(REBUILD_KEY)


def set_rebuild_progress_sync(r: sync_redis.Redis, message: str) -> None:
    r.hset(REBUILD_KEY, "message", message)


def set_rebuild_complete_sync(r: sync_redis.Redis, message: str, details: dict) -> None:
    import json
    r.hset(REBUILD_KEY, mapping={
        "state": "complete",
        "message": message,
        "completed_at": time.time(),
        "details": json.dumps(details),
    })
    r.expire(REBUILD_KEY, REBUILD_EXPIRE)


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
    clear_cancel_sync(r)
