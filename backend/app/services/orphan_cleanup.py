"""Orphan-detection and thumbnail-reference cleanup for the FITS catalog.

Pure extraction of logic that used to live inline in
`app/worker/tasks.py`'s `run_scan` (the orphan-detection/delete/thumbnail-
unlink/panel-session-pruning block) and in the module-level
`_thumbnail_referenced` helper used by `_do_ingest`'s failure path. Behavior
is preserved exactly, including the 50%-missing safety threshold, the
500-row delete batching, and the exact activity event types/messages/details
asserted on elsewhere (`orphan_cleanup`, `orphan_force_warning`,
`orphan_warning`).

`cleanup_orphaned_images` accepts the session factory, activity-session
factory, activity-emit function, and panel-session-pruning function as
parameters (defaulting to the real implementations) rather than importing
and calling them directly. This mirrors how `run_scan` itself references
these as module-level names on `app.worker.tasks` -- callers/tests that
patch those names on the `tasks` module continue to work unchanged when
`run_scan` forwards its own (possibly patched) references through.
"""

import logging
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Image
from app.services.activity import emit_sync
from app.services.mosaic_detection import prune_stale_panel_sessions

logger = logging.getLogger(__name__)


def thumbnail_referenced(thumb_path_str: str, sync_engine) -> bool:
    """Return True if any Image row references this thumbnail file.

    The thumbnail filename is derived deterministically from the file path
    (md5), so two ingest attempts for the same path target the same file.
    Before unlinking a thumbnail after a failed insert we confirm no existing
    row points at it, otherwise we would break the surviving row (AUD-015).
    """
    try:
        with Session(sync_engine) as session:
            existing = session.execute(
                select(Image.id).where(Image.thumbnail_path == thumb_path_str).limit(1)
            ).first()
            return existing is not None
    except Exception:
        # If the check itself fails, err on the side of NOT deleting a
        # possibly-shared thumbnail.
        return True


def cleanup_orphaned_images(
    sync_engine,
    redis,
    known_paths: set,
    all_disk_paths: set,
    filter_config,
    fits_root,
    force_orphan_cleanup: bool,
    *,
    session_factory=Session,
    activity_session_factory=None,
    emit_fn=emit_sync,
    prune_fn=prune_stale_panel_sessions,
) -> dict:
    """Detect and remove orphaned DB records (files deleted from disk).

    CRITICAL: only consider rows the walker would have actually visited
    under the current filter config. When include_paths or excludes narrow
    the scan, out-of-scope rows appear "missing from disk" even though the
    walker never looked for them. Those must NOT be treated as orphans.

    Returns ``{"removed": int, "in_scope_known": int, "large_removal": bool}``
    so the caller can build its own status dict / log lines.
    """
    if activity_session_factory is None:
        activity_session_factory = lambda: session_factory(sync_engine)

    in_scope_known_paths = {
        p for p in known_paths
        if p and filter_config.should_include_file(Path(p), fits_root)
    }
    orphaned_paths = in_scope_known_paths - all_disk_paths
    removed = 0
    _threshold = max(1, len(in_scope_known_paths)) * 0.5
    _large_removal = len(orphaned_paths) >= _threshold or len(all_disk_paths) == 0
    if orphaned_paths and (force_orphan_cleanup or len(orphaned_paths) < _threshold):
        # Safety: only clean up if less than 50% of files appear missing
        # (protects against unmounted shares / unreachable storage), unless an
        # admin forced a one-time cleanup to reflect a deliberate bulk deletion.
        with session_factory(sync_engine) as session:
            # Capture each deleted row's panel_id before the delete fires --
            # ON DELETE SET NULL on images.panel_id means it can't be read
            # back off the images table afterward. Pruning of stale
            # MosaicPanelSession rows for these panels runs once after the
            # whole orphan pass (not per 500-row batch): a single pass is
            # cheaper and avoids redundant work while more deletes in the
            # same run are still happening.
            affected_panel_ids: set = set()
            for batch_start in range(0, len(orphaned_paths), 500):
                batch = list(orphaned_paths)[batch_start:batch_start + 500]
                rows = session.execute(
                    select(Image.id, Image.thumbnail_path, Image.panel_id).where(
                        Image.file_path.in_(batch)
                    )
                ).all()
                for img_id, thumb_path, panel_id in rows:
                    if thumb_path:
                        try:
                            Path(thumb_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    if panel_id is not None:
                        affected_panel_ids.add(panel_id)
                    session.execute(
                        text("DELETE FROM images WHERE id = :id"),
                        {"id": img_id},
                    )
                    removed += 1
                session.commit()

            if affected_panel_ids:
                pruned = prune_fn(session, affected_panel_ids)
                if pruned:
                    logger.info(
                        "Pruned %d stale mosaic panel session row%s after orphan cleanup",
                        pruned, "s" if pruned != 1 else "",
                    )
        if removed:
            logger.info("Removed %d orphaned image records (files deleted from disk)", removed)
            with activity_session_factory() as _db:
                emit_fn(
                    _db, redis=redis, category="scan", severity="info",
                    event_type="orphan_cleanup",
                    message=f"Removed {removed} deleted file{'s' if removed != 1 else ''} from catalog",
                    details={"removed": removed}, actor="system",
                )
            if force_orphan_cleanup and _large_removal and removed:
                pct = round(removed / max(1, len(in_scope_known_paths)) * 100)
                logger.warning(
                    "Forced orphan cleanup removed %d of %d catalogued files (%d%%)",
                    removed, len(in_scope_known_paths), pct,
                )
                with activity_session_factory() as _db:
                    emit_fn(
                        _db, redis=redis, category="scan", severity="warning",
                        event_type="orphan_force_warning",
                        message=(
                            f"Forced orphan cleanup removed {removed} of "
                            f"{len(in_scope_known_paths)} catalogued file"
                            f"{'s' if removed != 1 else ''} ({pct}% of the catalog). "
                            f"If a storage share was unmounted or unreachable, "
                            f"restore from backup."
                        ),
                        details={"removed": removed, "total_known": len(in_scope_known_paths), "forced": True},
                        actor="system",
                    )
    elif orphaned_paths:
        logger.warning(
            "Skipped orphan cleanup: %d of %d in-scope files missing (>50%%) - "
            "possible unmounted share or unreachable storage",
            len(orphaned_paths), len(in_scope_known_paths),
        )
        with activity_session_factory() as _db:
            emit_fn(
                _db, redis=redis, category="scan", severity="warning",
                event_type="orphan_warning",
                message=f"Orphan cleanup skipped: {len(orphaned_paths)} of {len(in_scope_known_paths)} in-scope files missing (>50%) - possible unmounted share",
                details={"missing": len(orphaned_paths), "total_known": len(in_scope_known_paths)},
                actor="system",
            )

    return {
        "removed": removed,
        "in_scope_known": len(in_scope_known_paths),
        "large_removal": _large_removal,
    }
