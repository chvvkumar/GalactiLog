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
# A scan trigger that arrives while a scan is running sets this flag instead of
# being rejected: the running walk is single-pass, so files copied in after it
# started are invisible to it until someone triggers again. The flag is a
# single key, so N triggers during one scan collapse into exactly one follow-up
# run. Value is "1"/"0" carrying the trigger's include_calibration choice
# (force_orphan_cleanup is deliberately not carried - it is a one-time
# admin action, not something to replay into a scan the admin didn't ask for).
# Consumed with GETDEL at every scan completion path, so the follow-up can
# never re-trigger itself; its own followers queue normally.
SCAN_PENDING_KEY = "scan:pending_rescan"
SCAN_PENDING_TTL = 6 * 3600  # backstop: a flag stranded by a crashed scan dies
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
    # PHD2 guide-log ingest counters, written once at the end of the
    # scan_phd2_logs run rather than incremented per file: the PHD2 pass runs
    # after image discovery and must not interleave with the image ingest
    # progress bar's step/total.
    phd2_found: int = 0
    phd2_ingested: int = 0
    phd2_failed: int = 0
    # Files the pass has looked at so far, whatever the verdict (ingested,
    # unchanged, empty, failed). This is the scan screen's numerator: on a
    # routine rescan nearly every log short-circuits as unchanged, so a
    # numerator built from ingested+failed sat at 0 against a denominator of
    # hundreds and then jumped straight to done.
    phd2_checked: int = 0
    # "" | pending | running. The guide-log pass is dispatched by run_scan and
    # then runs on its own, so `state` can read "complete" while it is still
    # working. Without this field a caller polling for completeness reads the
    # phd2_* counters during that window and gets zeros. "pending" covers the
    # gap between dispatch and the worker picking the task up; "running" is
    # written by the task itself and cleared, together with the counters, in
    # the one write that publishes them.
    phd2_state: str = ""
    # Unix time at which phd2_state was last written, or None for a hash
    # written before this field existed. Only a RAISING apply_async clears
    # the flag: a guide-log task that was queued and then lost (worker down,
    # broker discard) leaves "pending" set until the whole scan:state key
    # expires, and a consumer that waits for the flag to clear waits forever.
    # The age of the claim is what lets a reader stop believing it.
    phd2_state_at: float | None = None
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
    # True when a trigger arrived mid-scan and a follow-up scan is queued to
    # run once this one finishes (SCAN_PENDING_KEY). Not a field of the
    # scan:state hash - it outlives that hash's resets - so it is filled in by
    # get_scan_state, not by parse_snapshot.
    pending_rescan: bool = False

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
            "phd2_found": self.phd2_found,
            "phd2_ingested": self.phd2_ingested,
            "phd2_failed": self.phd2_failed,
            "phd2_checked": self.phd2_checked,
            "phd2_state": self.phd2_state,
            "phd2_state_at": self.phd2_state_at,
            "task": self.task,
            "step": self.step,
            "total_steps": self.total_steps,
            "percent": self.percent,
            "message": self.message,
            "pending_rescan": self.pending_rescan,
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
        phd2_found=int(data.get("phd2_found", 0)),
        phd2_ingested=int(data.get("phd2_ingested", 0)),
        phd2_failed=int(data.get("phd2_failed", 0)),
        phd2_checked=int(data.get("phd2_checked", 0)),
        phd2_state=data.get("phd2_state", "") or "",
        phd2_state_at=(
            float(data["phd2_state_at"]) if data.get("phd2_state_at") else None
        ),
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
    snap.pending_rescan = await r.exists(SCAN_PENDING_KEY) == 1
    return snap


async def request_scan(
    r: aioredis.Redis | None = None,
    *,
    include_calibration: bool = False,
    force_orphan_cleanup: bool = False,
) -> str:
    """Start a scan, or queue one to follow the scan that is already running.

    Returns "started" (run_scan dispatched now) or "queued" (a scan is in
    flight; SCAN_PENDING_KEY set so exactly one follow-up runs when it
    finishes). Queuing rather than rejecting is the point: the directory walk
    is single-pass, so files that land after it started are invisible to it,
    and "come back and press the button again" is not something a copy job can
    do.

    ``r`` is optional so a caller that already holds a connection can pass it;
    without one a connection is opened for the call.
    """
    if r is None:
        from app.config import async_redis
        async with async_redis() as conn:
            return await request_scan(
                conn,
                include_calibration=include_calibration,
                force_orphan_cleanup=force_orphan_cleanup,
            )

    pending_value = "1" if include_calibration else "0"
    # Same SET NX lock as before: it closes the check/dispatch race. Losing it
    # means another request is dispatching a scan right now - its walk has not
    # begun, so it will see whatever this caller just copied in. Nothing to
    # queue and nothing to dispatch; queuing here would turn a double-click
    # into a second full library walk.
    if not await r.set("scan:lock", "1", nx=True, ex=10):
        return "started"
    try:
        state = await get_scan_state(r)
        if state.state in ("scanning", "ingesting"):
            # get_scan_state reports a just-dispatched scan as "scanning" even
            # though no worker has picked it up (AUD-016). That scan has not
            # walked anything yet, so it covers this request too - only a scan
            # that has actually started needs a follow-up. start_scanning_sync
            # deletes the marker, so a running scan never trips this.
            if await r.exists(SCAN_DISPATCHED_KEY):
                return "started"
            await r.set(SCAN_PENDING_KEY, pending_value, ex=SCAN_PENDING_TTL)
            return "queued"

        from app.worker.tasks import run_scan

        # Mark a scan as dispatched *before* releasing the lock below, so a
        # second request that acquires the lock right after this one still
        # sees an active scan even though the queued run_scan task hasn't been
        # picked up by a worker yet and start_scanning_sync() hasn't run
        # (AUD-016).
        await mark_scan_dispatched(r)
        run_scan.delay(
            include_calibration=include_calibration,
            force_orphan_cleanup=force_orphan_cleanup,
        )
        return "started"
    finally:
        await r.delete("scan:lock")


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
    # Drop any queued follow-up scan too. Reset is the "put everything back to
    # idle" button, pressed on a scan that is stalled or wedged; honouring the
    # flag here would start a fresh scan out of an action the user asked for
    # precisely because they wanted the scanning to stop. They can press Scan.
    # Without this the flag would sit until its 6h TTL and then surprise the
    # next completed scan with an extra run.
    await r.delete(SCAN_PENDING_KEY)
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


def arm_pending_rescan_sync(r: sync_redis.Redis, include_calibration: bool) -> None:
    """Queue a follow-up scan from the worker side (see SCAN_PENDING_KEY).

    The worker-side twin of request_scan's queueing branch, for a run_scan
    dispatch that bails on the run lock: the walk it was going to do is still
    owed, and the scan holding the lock is the one that can pay it.
    """
    r.set(SCAN_PENDING_KEY, "1" if include_calibration else "0", ex=SCAN_PENDING_TTL)


def dispatch_pending_rescan_sync(r: sync_redis.Redis) -> bool:
    """Run the follow-up scan queued by a trigger that arrived mid-scan.

    Called from every path where a scan finishes. GETDEL is what makes this
    safe to call from several of them: the flag is read and cleared in one
    round trip, so two completion paths racing can only dispatch one scan. The
    follow-up re-arms the flag only if it never got to run at all (bailed on
    the run lock - see run_scan); a trigger arriving during a follow-up that
    does run queues the next one normally.

    The countdown gives run_scan's own SCAN_RUN_LOCK - released in its
    `finally`, which can still be pending when the no-new-files path calls
    this from inside the task - time to clear; without it the follow-up would
    bail out as a duplicate dispatch and the queued rescan would be lost. The
    dispatch marker keeps /scan/status reading "scanning" across the wait, so
    the UI doesn't blink idle and a third trigger doesn't slip in.

    Race window: a trigger that read the state as "ingesting" before this
    scan published "complete", but wrote its flag after the GETDEL below, sets
    a flag nobody consumes until the next scan finishes. It costs one extra
    scan later, never a lost one, and requires the request to stall across the
    whole completion tail - not worth a lock to close.
    """
    raw = r.getdel(SCAN_PENDING_KEY)
    if raw is None:
        return False
    value = raw.decode() if isinstance(raw, bytes) else raw
    include_calibration = value == "1"
    from app.worker.tasks import run_scan
    try:
        r.set(SCAN_DISPATCHED_KEY, "1", ex=SCAN_DISPATCHED_TTL)
        run_scan.apply_async(
            countdown=10,
            # queued=True: if it still finds the run lock held, it re-arms the
            # flag instead of dropping the rescan (the GETDEL above already
            # consumed it).
            kwargs={"include_calibration": include_calibration, "queued": True},
        )
    except Exception:
        # Put the flag back: the request that queued this rescan is owed a
        # scan, and a broker hiccup here would otherwise drop it silently for
        # good. The next completion path re-tries the dispatch.
        r.set(SCAN_PENDING_KEY, value, ex=SCAN_PENDING_TTL)
        r.delete(SCAN_DISPATCHED_KEY)
        logger.warning(
            "scan_state: could not dispatch the queued follow-up scan", exc_info=True,
        )
        return False
    logger.info("scan_state: dispatching queued follow-up scan")
    return True


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
        # A CSV backfill publishes itself as "ingesting" in this same hash, so
        # a scan triggered while one runs is told "queued". This branch is
        # where that backfill ends, and it is the only place that follow-up
        # can be dispatched from - without it the promised scan never runs.
        dispatch_pending_rescan_sync(r)
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
                        details={
                            "failed_files": fits_failures,
                            "truncated": len(raw) > 500,
                            "action": {
                                "label": "View failed files",
                                "href": "/settings?tab=scan#activity-feed",
                            },
                        },
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
        backfill_dark_hours, correlate_phd2_images,
    )
    smart_rebuild_targets.apply_async(countdown=10, kwargs={"parent_activity_id": scan_activity_id})
    generate_reference_thumbnails.apply_async(countdown=20, kwargs={"parent_activity_id": scan_activity_id})
    detect_mosaic_panels_task.apply_async(countdown=30, kwargs={"parent_activity_id": scan_activity_id})
    detect_duplicate_targets.apply_async(countdown=30, kwargs={"parent_activity_id": scan_activity_id})
    backfill_dark_hours.apply_async(countdown=45, kwargs={"parent_activity_id": scan_activity_id})
    # Newly ingested frames whose night already holds guide-log sessions. Last
    # in the cascade at 120 s: the guide-log pass run_scan dispatched at 50 s
    # re-derives the nights it writes, and this only has to catch the frames
    # that pass never looked at.
    correlate_phd2_images.apply_async(countdown=120, kwargs={"parent_activity_id": scan_activity_id})
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
    # The ingest is done, so this is where a scan triggered mid-run gets its
    # turn: everything copied in after this run's single-pass walk started is
    # only visible to a fresh walk.
    dispatch_pending_rescan_sync(r)


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


PHD2_STATE_PENDING = "pending"
PHD2_STATE_RUNNING = "running"
PHD2_STATE_IDLE = ""


def reset_phd2_counts_sync(r: sync_redis.Redis, found: int) -> None:
    """Zero the PHD2 counters and mark a new guide-log pass as queued.

    Called where the scan dispatches the pass. scan:state survives a completed
    scan for EXPIRE_AFTER_COMPLETE, so without this the previous run's totals
    stay readable as if they described the run now starting - a poller that
    waits for `state == "complete"` and then reads phd2_ingested gets the last
    scan's number. Zeroing and flagging together means the counters are only
    ever non-zero once they describe this pass.

    `found` is how many guide logs this pass has in scope, and it is the
    denominator the scan screen counts "N of M" against. It is required, and
    written in this same hset, because the pass is dispatched with a 50 second
    countdown: the task's own set_phd2_found_sync call does not run until then,
    so a placeholder written here is what the user reads for the whole
    countdown, and a denominator of zero is exactly what makes the UI drop the
    sub-label. Requiring the argument is also what keeps "not yet known" and
    "known to be zero" apart. The count can never lag the flag, so a reader
    seeing phd2_found == 0 next to a live phd2_state knows this pass has no
    guide logs in scope rather than a number still to come.

    phd2_state_at goes in the same write. The flag has no other expiry: a task
    that is queued and then lost never runs the code that clears it, so a
    reader needs the age of the claim to stop believing it.
    """
    r.hset(SCAN_KEY, mapping={
        "phd2_found": found,
        "phd2_ingested": 0,
        "phd2_failed": 0,
        "phd2_checked": 0,
        "phd2_state": PHD2_STATE_PENDING,
        "phd2_state_at": time.time(),
    })


def set_phd2_state_sync(r: sync_redis.Redis, state: str) -> None:
    """Record where the guide-log pass has got to (see ScanStateSnapshot).

    The timestamp moves with the state, so "running" written by a worker that
    then dies ages out the same way "pending" does.
    """
    r.hset(SCAN_KEY, mapping={
        "phd2_state": state,
        "phd2_state_at": time.time() if state else "",
    })


def set_phd2_found_sync(r: sync_redis.Redis, found: int) -> None:
    """Publish how many guide logs this pass will look at, as soon as it knows.

    The scan screen counts "N of M" while the pass runs, and M is known the
    moment the candidate list exists. Publishing it only in the end-of-pass
    write meant the UI had a numerator that climbed against a denominator of
    zero for the whole pass - which is why the counters read 0 for the pass's
    entire lifetime rather than only until it started.

    Written alone rather than through set_phd2_counts_sync: that function
    clears the in-flight flag in the same write, and the pass is very much
    still in flight here.
    """
    r.hset(SCAN_KEY, "phd2_found", found)


def increment_phd2_progress_sync(
    r: sync_redis.Redis, ingested: int = 0, failed: int = 0, checked: int = 0
) -> None:
    """Advance the per-file guide-log counters, following increment_csv_enriched_sync.

    hincrby rather than hset because the pass keeps its authoritative totals
    in local variables and writes them once at the end: re-writing a derived
    running total per file would race that final write, and a crash halfway
    through would leave a total that describes neither state. Incrementing is
    also what the image-ingest counters do, so the scan screen's two progress
    readouts behave the same way.

    A call with nothing to report writes nothing. Most files in a rescan are
    unchanged, and a Redis round trip per unchanged file in a library of
    hundreds of logs is pure overhead - which is why `checked` (files looked
    at, whatever the verdict) is flushed by the caller in batches rather than
    reported one file at a time.

    Real progress also renews phd2_state_at. The timestamp is what lets a
    reader age a stuck claim out, and a consumer that applies its staleness
    window to "running" as well as "pending" would otherwise call a healthy
    pass stalled the moment it ran longer than that window - which a library
    of hundreds of guide logs comfortably does. Renewing it here means a
    timestamp that has stopped moving is evidence the pass has, rather than
    evidence it is merely slow. Only a call that has progress to report
    renews it: a no-op must not keep a genuinely hung pass looking alive.
    """
    if not ingested and not failed and not checked:
        return
    if ingested:
        r.hincrby(SCAN_KEY, "phd2_ingested", ingested)
    if failed:
        r.hincrby(SCAN_KEY, "phd2_failed", failed)
    if checked:
        r.hincrby(SCAN_KEY, "phd2_checked", checked)
    r.hset(SCAN_KEY, "phd2_state_at", time.time())


def set_phd2_counts_sync(
    r: sync_redis.Redis, found: int, ingested: int, failed: int,
    checked: int | None = None,
) -> None:
    """Publish the PHD2 pass's totals in one write and clear the in-flight flag.

    Not incremental: the PHD2 pass runs after image discovery and writes its
    own fields, so it can never disturb the completed/failed/total counters
    that drive the image ingest progress bar.

    phd2_state is cleared in the same hset as the counters, deliberately: a
    reader that sees the pass finished must see this pass's numbers in the
    same snapshot, never the flag cleared a moment before the totals land.
    """
    r.hset(SCAN_KEY, mapping={
        "phd2_found": found,
        "phd2_ingested": ingested,
        "phd2_failed": failed,
        # A finished pass has by definition checked everything it found; this
        # also settles the partial batch the per-file flush had not sent yet.
        "phd2_checked": found if checked is None else checked,
        "phd2_state": PHD2_STATE_IDLE,
        "phd2_state_at": "",
    })


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
    # Unlike set_idle_sync (nothing was ever processed there, so 0/0 is
    # factually correct), a cancelled scan has real progress in the flat
    # counters, and the hash lives on for EXPIRE_AFTER_COMPLETE (24h). The
    # envelope must agree with completed/failed/total at the moment of
    # cancellation - otherwise a bar reading percent would snap from e.g.
    # 80% to 0% and stay wrong until the hash expires.
    data = r.hgetall(SCAN_KEY)
    snap = parse_snapshot(data)
    kind = data.get("kind", "scan") if data else "scan"
    r.hset(SCAN_KEY, mapping={
        "state": "complete",
        "completed_at": time.time(),
    })
    r.expire(SCAN_KEY, EXPIRE_AFTER_COMPLETE)
    r.delete(SCAN_CANCEL_KEY)
    # A cancelled scan must not hand off to a queued follow-up: the user asked
    # for the scanning to stop, and a rescan starting seconds later is the
    # opposite of that.
    r.delete(SCAN_PENDING_KEY)
    from app.services.progress_envelope import set_progress
    set_progress(
        r, SCAN_KEY, task=kind, step=snap.completed + snap.failed,
        total_steps=snap.total, message="Cancelled",
    )


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
