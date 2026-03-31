"""Redis-backed scan state manager.

Keys used:
  scan:state   — hash with fields: state, total, completed, failed, started_at, completed_at
  scan:state is set to expire after 24h on completion so old results don't linger forever.
"""

import time
from dataclasses import dataclass

import redis.asyncio as aioredis
import redis as sync_redis

SCAN_KEY = "scan:state"
SCAN_PROGRESS_KEY = "scan:last_progress"
SCAN_FAILED_KEY = "scan:failed_files"
SCAN_CANCEL_KEY = "scan:cancel"
SCAN_ACTIVITY_KEY = "scan:activity"
SCAN_ACTIVITY_MAX = 20
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
        msg = f"Scan complete: {snap.completed} ingested, {snap.failed} failed"
        if snap.csv_enriched > 0:
            msg += f", {snap.csv_enriched} CSV enriched"
        if snap.removed > 0:
            msg += f", {snap.removed} deleted files purged from catalog"
        append_activity_sync(r, {
            "type": "scan_complete",
            "message": msg,
            "details": {"completed": snap.completed, "failed": snap.failed, "csv_enriched": snap.csv_enriched, "total": snap.total, "removed": snap.removed},
            "timestamp": time.time(),
        })


def start_scanning_sync(r: sync_redis.Redis) -> None:
    r.hset(SCAN_KEY, mapping={
        "state": "scanning",
        "total": 0,
        "completed": 0,
        "failed": 0,
        "started_at": time.time(),
        "completed_at": "",
    })
    r.set(SCAN_PROGRESS_KEY, str(time.time()))
    r.persist(SCAN_KEY)
    r.delete(SCAN_FAILED_KEY)


def set_ingesting_sync(r: sync_redis.Redis, total: int, removed: int = 0) -> None:
    mapping: dict = {
        "state": "ingesting",
        "total": total,
    }
    if removed:
        mapping["removed"] = removed
    r.hset(SCAN_KEY, mapping=mapping)


def increment_csv_enriched_sync(r: sync_redis.Redis) -> None:
    r.hincrby(SCAN_KEY, "csv_enriched", 1)


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


def append_activity_sync(r: sync_redis.Redis, entry: dict) -> None:
    """Append an activity entry and cap the list at SCAN_ACTIVITY_MAX."""
    import json
    r.lpush(SCAN_ACTIVITY_KEY, json.dumps(entry))
    r.ltrim(SCAN_ACTIVITY_KEY, 0, SCAN_ACTIVITY_MAX - 1)


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
