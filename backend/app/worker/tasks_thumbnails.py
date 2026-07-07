"""Thumbnail maintenance tasks: regenerate missing/all thumbnails, per-image
regeneration, and DSS reference-thumbnail fetching."""
import logging
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from celery.exceptions import SoftTimeLimitExceeded

from app.config import settings
from app.models import Image, Target
from app.services.thumbnail import generate_thumbnail
from app.services.xisf_parser import generate_xisf_thumbnail
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis, _activity_session, _invalidate_stats_cache
from app.services.scan_state import (
    set_idle_sync, set_ingesting_sync, is_cancel_requested_sync, set_cancelled_sync,
    set_rebuild_running_sync, set_rebuild_progress_sync, set_rebuild_complete_sync,
    set_rebuild_cancelled_sync, clear_cancel_sync,
    increment_completed_sync, increment_failed_sync,
)
from app.services.activity import emit_sync as _emit_activity_sync

logger = logging.getLogger(__name__)


@celery_app.task(name="regenerate_missing_thumbnails")
def regenerate_missing_thumbnails() -> dict:
    """Check every image's thumbnail_path and regenerate only those whose
    files are missing from disk.  Much faster than a full regeneration when
    only a handful of files were lost.

    Rows are fetched in chunks of 2000 to keep memory bounded regardless of
    catalog size.  ThreadPoolExecutor parallelism is applied within each chunk.
    """
    _CHUNK = 2000

    from concurrent.futures import ThreadPoolExecutor

    def _check_missing(thumb_path: str) -> bool:
        return not Path(thumb_path).is_file()

    checked = 0
    missing: list[tuple[str, str, str]] = []

    with Session(_sync_engine) as session:
        result = session.execute(
            select(Image.id, Image.file_path, Image.thumbnail_path)
            .where(Image.thumbnail_path.isnot(None))
        ).yield_per(_CHUNK)

        with ThreadPoolExecutor(max_workers=32) as pool:
            for chunk in result.partitions(_CHUNK):
                checked += len(chunk)
                futures = {pool.submit(_check_missing, tp): (image_id, fp, tp)
                           for image_id, fp, tp in chunk}
                for fut, (image_id, file_path, thumb_path) in futures.items():
                    if fut.result() and file_path:
                        missing.append((str(image_id), file_path, thumb_path))

    if checked == 0:
        set_idle_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="thumb_missing_complete",
                message="Regenerate missing thumbnails: no images with thumbnail paths",
                details={"checked": 0, "missing": 0}, actor="system",
            )
        return {"status": "complete", "checked": 0, "missing": 0}

    if not missing:
        set_idle_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="thumb_missing_complete",
                message=f"All {checked} thumbnails present on disk, nothing to regenerate",
                details={"checked": checked, "missing": 0}, actor="system",
            )
        return {"status": "complete", "checked": checked, "missing": 0}

    set_ingesting_sync(_redis, total=len(missing))

    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="thumb_missing_start",
            message=f"Found {len(missing)} missing thumbnail{'s' if len(missing) != 1 else ''} "
                    f"out of {checked} checked, queueing regeneration...",
            details={"checked": checked, "missing": len(missing)}, actor="system",
        )

    for image_id, file_path, thumb_path in missing:
        regenerate_thumbnail.delay(image_id, file_path, thumb_path)

    return {"status": "ingesting", "checked": checked, "missing": len(missing)}


@celery_app.task(name="purge_and_regenerate_thumbnails")
def purge_and_regenerate_thumbnails() -> dict:
    """Delete every thumbnail file on disk, then queue regeneration for all images.

    Logs start, per-batch progress, and completion of the delete phase to the
    activity log. The final "scan complete" activity is emitted by the usual
    check_complete_sync flow once all regenerate_thumbnail tasks finish.

    Rows are fetched in chunks of 2000 to keep memory bounded regardless of
    catalog size.  ThreadPoolExecutor parallelism is applied within each chunk.
    """
    _CHUNK = 2000

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _unlink_one(thumb_path: str) -> str:
        """Return 'deleted', 'missing', or 'error'. Network-IO bound."""
        try:
            Path(thumb_path).unlink()
            return "deleted"
        except FileNotFoundError:
            return "missing"
        except OSError as exc:
            logger.warning("Failed to delete thumbnail %s: %s", thumb_path, exc)
            return "error"

    # First pass: count total rows (needed for cancel/start messages before deletion begins)
    with Session(_sync_engine) as session:
        total_result = session.execute(select(func.count(Image.id))).scalar_one()
    total = total_result

    if not total:
        set_idle_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="thumb_purge_complete",
                message="Regen thumbnails: no images to process",
                details={"deleted": 0, "queued": 0}, actor="system",
            )
        return {"status": "complete", "deleted": 0, "queued": 0}

    if is_cancel_requested_sync(_redis):
        set_cancelled_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message="Thumbnail purge cancelled before start",
                details={"deleted": 0, "queued": 0, "total": total}, actor="system",
            )
        return {"status": "cancelled", "deleted": 0, "queued": 0}

    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="thumb_purge_start",
            message=f"Deleting existing thumbnails for {total} image{'s' if total != 1 else ''}...",
            details={"total": total}, actor="system",
        )

    # Second pass: delete thumbnails chunk-by-chunk
    deleted = 0
    missing_files = 0
    with Session(_sync_engine) as session:
        result = session.execute(
            select(Image.id, Image.file_path, Image.thumbnail_path)
        ).yield_per(_CHUNK)

        with ThreadPoolExecutor(max_workers=32) as pool:
            for chunk in result.partitions(_CHUNK):
                paths_in_chunk = [(image_id, fp, tp) for image_id, fp, tp in chunk if tp]
                if not paths_in_chunk:
                    continue
                futures = {pool.submit(_unlink_one, tp): (image_id, fp, tp)
                           for image_id, fp, tp in paths_in_chunk}
                for fut in as_completed(futures):
                    outcome = fut.result()
                    if outcome == "deleted":
                        deleted += 1
                    elif outcome == "missing":
                        missing_files += 1

    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="thumb_purge_complete",
            message=f"Deleted {deleted} thumbnail{'s' if deleted != 1 else ''}"
                    + (f" ({missing_files} already missing)" if missing_files else "")
                    + f", queueing {total} for regeneration...",
            details={"deleted": deleted, "missing": missing_files, "queued": total},
            actor="system",
        )

    if is_cancel_requested_sync(_redis):
        set_cancelled_sync(_redis)
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message=f"Thumbnail purge cancelled after deleting {deleted} files; regen skipped",
                details={"deleted": deleted, "missing": missing_files, "queued": 0, "total": total},
                actor="system",
            )
        return {"status": "cancelled", "deleted": deleted, "missing": missing_files, "queued": 0}

    set_ingesting_sync(_redis, total=total)

    # Third pass: queue regeneration chunk-by-chunk
    queued = 0
    with Session(_sync_engine) as session:
        result = session.execute(
            select(Image.id, Image.file_path, Image.thumbnail_path)
        ).yield_per(_CHUNK)

        for chunk in result.partitions(_CHUNK):
            for image_id, file_path, thumb_path in chunk:
                if file_path and thumb_path:
                    regenerate_thumbnail.delay(str(image_id), file_path, thumb_path)
                    queued += 1

    return {"status": "ingesting", "deleted": deleted, "missing": missing_files, "queued": queued}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="app.worker.tasks.regenerate_thumbnail")
def regenerate_thumbnail(self, image_id: str, fits_path: str, thumb_path: str) -> dict:
    """Regenerate a single thumbnail using the current stretch algorithm."""
    path = Path(fits_path)
    output = Path(thumb_path)

    # Drain queued tasks on cancel so scan state transitions to complete via check_complete_sync.
    if is_cancel_requested_sync(_redis):
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "cancelled"}

    logger.info("Regenerating thumbnail: %s", path.name)

    try:
        if path.suffix.lower() == ".xisf":
            generate_xisf_thumbnail(path, output, max_width=settings.thumbnail_max_width)
        else:
            generate_thumbnail(path, output, max_width=settings.thumbnail_max_width)
        increment_completed_sync(_redis)
        return {"file": str(path), "status": "ok"}
    except Exception as exc:
        logger.error("Failed to regenerate thumbnail for %s: %s", path, exc)
        if self.request.retries >= self.max_retries:
            increment_failed_sync(_redis, file_path=str(path), error=str(exc))
            return {"file": str(path), "status": "failed", "error": str(exc)}
        raise self.retry(exc=exc)


@celery_app.task(bind=True, name="app.worker.tasks.generate_reference_thumbnails")
def generate_reference_thumbnails(self, force: bool = False, parent_activity_id: int | None = None) -> dict:
    """Fetch DSS reference thumbnails for all targets."""
    from app.services.skyview import fetch_reference_thumbnail

    clear_cancel_sync(_redis)
    set_rebuild_running_sync(
        _redis, "ref_thumbnails", "Finding targets needing thumbnails...",
        task="ref_thumbnails", step=0, total_steps=0,
    )
    output_dir = Path(settings.thumbnails_path) / "reference"

    # Commit fetched thumbnails in small chunks so a run that is killed
    # mid-loop (time limit, worker restart) persists the thumbnails it already
    # fetched instead of rolling back the whole batch. Each subsequent run then
    # re-queries only targets still missing a thumbnail and continues from
    # there, rather than starting over (AUD-003). expire_on_commit is disabled
    # so the pre-loaded target objects stay usable across those chunk commits
    # without a reload round-trip per remaining target.
    COMMIT_CHUNK = 10
    with Session(_sync_engine) as session:
        session.expire_on_commit = False
        q = select(Target).where(
            Target.merged_into_id.is_(None),
            Target.ra.isnot(None),
            Target.dec.isnot(None),
        )
        if not force:
            q = q.where(Target.reference_thumbnail_path.is_(None))
        targets = session.execute(q).scalars().all()

        total = len(targets)
        set_rebuild_progress_sync(
            _redis, f"Fetching reference thumbnails 0/{total}...",
            task="ref_thumbnails", step=0, total_steps=total,
        )
        fetched = 0
        processed = 0
        cancelled = False
        timed_out = False
        try:
            for i, target in enumerate(targets):
                if is_cancel_requested_sync(_redis):
                    cancelled = True
                    break
                path = fetch_reference_thumbnail(target, output_dir)
                if path:
                    target.reference_thumbnail_path = path
                    fetched += 1
                processed = i + 1
                if (i + 1) % COMMIT_CHUNK == 0:
                    session.commit()  # persist partial progress
                if (i + 1) % 5 == 0 or i + 1 == total:
                    set_rebuild_progress_sync(
                        _redis, f"Reference thumbnails: {i + 1}/{total} ({fetched} fetched)",
                        task="ref_thumbnails", step=i + 1, total_steps=total,
                    )
                time.sleep(1.0)  # Rate limit
        except SoftTimeLimitExceeded:
            # Hit the (generous) task time limit. Persist what we have and fall
            # through to write a terminal "complete" state so REBUILD_KEY is
            # never left stuck at "running"; the remaining targets are picked up
            # on the next run because they still have no thumbnail path.
            timed_out = True
        session.commit()

    if cancelled:
        stats = {"fetched": fetched, "total": total}
        set_rebuild_cancelled_sync(
            _redis, f"Cancelled after fetching {fetched}/{total} reference thumbnails", stats
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="thumbnail", severity="info",
                event_type="rebuild_cancelled",
                message=f"Reference Thumbnails cancelled after {fetched}/{total}",
                details=stats, actor="system",
                parent_id=parent_activity_id,
            )
        return {"status": "cancelled", **stats}

    _invalidate_stats_cache()
    stats = {"fetched": fetched, "total": total, "timed_out": timed_out}
    if timed_out:
        message = (
            f"Fetched {fetched}/{total} reference thumbnails "
            "(paused at the time limit; the rest continue on the next scan)"
        )
    else:
        message = f"Fetched {fetched}/{total} reference thumbnails"
    set_rebuild_complete_sync(
        _redis, message, stats,
        task="ref_thumbnails", step=(processed if timed_out else total), total_steps=total,
    )
    with _activity_session() as _db:
        _emit_activity_sync(
            _db, redis=_redis, category="thumbnail", severity="info",
            event_type="ref_thumbnails_complete",
            message=f"Reference Thumbnails: fetched {fetched}/{total}"
                    + (" (paused at time limit)" if timed_out else ""),
            details=stats, actor="system",
            parent_id=parent_activity_id,
        )
    return stats
