"""Data-version migrations + reference-catalog bootstrap: run_data_migrations,
load_reference_catalogs_if_empty, and their job-row bookkeeping helpers."""
import logging

from sqlalchemy import func, update as sa_update
from sqlalchemy.orm import Session
from celery.exceptions import SoftTimeLimitExceeded

from app.models.data_job import DataJob, DataJobStatus
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis, _activity_session
from app.worker.tasks_target_rebuild import smart_rebuild_targets
from app.worker.tasks_mosaics import detect_mosaic_panels_task
from app.services.activity import emit_sync as _emit_activity_sync

logger = logging.getLogger(__name__)

DATA_MIGRATION_LOCK = "data_migration:lock"
DATA_MIGRATION_LOCK_TTL = 600  # 10 minutes

REFERENCE_CATALOG_LOCK = "reference_catalogs:lock"
REFERENCE_CATALOG_LOCK_TTL = 600  # 10 minutes


def _data_migration_job_session():
    """Return a context-managed sync Session for data_jobs writes.

    Job-row writes always use their own session and commit independently of
    the migration-work session in run_data_migrations, so a job status update
    is never rolled back with a failed migration and is visible to concurrent
    readers (e.g. a future API progress endpoint) the instant it commits,
    regardless of what happens to the migration-work transaction afterward.
    """
    return Session(_sync_engine)


def _pickup_data_migration_job(job_key: str, total_steps: int, message: str) -> None:
    """Mark the data_jobs row for this run as running and seed its progress.

    Upserts on (job_type, job_key) so a run triggered without a prior
    dispatch-created row (e.g. a task invoked directly, as in tests) still
    gets a durable record. started_at is only set if not already set, so a
    resumed run after an interruption keeps its original start time;
    attempt_count always increments. step/total_steps are (re)seeded here
    since total_steps is computed once per run and a resumed run needs it
    recomputed against the fresh get_pending_migrations() count.

    Best-effort: job rows are observability only, so a failed pickup write
    must never block the real migration work. Any exception is logged and
    swallowed here, and the run proceeds without job-row tracking (the
    subsequent _update_data_migration_job calls are equally best-effort).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    try:
        with _data_migration_job_session() as db:
            stmt = pg_insert(DataJob).values(
                job_type="data_migration",
                job_key=job_key,
                status=DataJobStatus.running,
                started_at=func.now(),
                attempt_count=1,
                step=0,
                total_steps=total_steps,
                message=message,
                heartbeat_at=func.now(),
            ).on_conflict_do_update(
                index_elements=["job_type", "job_key"],
                set_={
                    "status": DataJobStatus.running,
                    "started_at": func.coalesce(DataJob.started_at, func.now()),
                    "attempt_count": DataJob.attempt_count + 1,
                    "step": 0,
                    "total_steps": total_steps,
                    "message": message,
                    "heartbeat_at": func.now(),
                },
            )
            db.execute(stmt)
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning(
            "data_migrations: could not record job pickup for job_key=%s; "
            "proceeding without job-row tracking", job_key, exc_info=True,
        )


def _update_data_migration_job(job_key: str, **values) -> None:
    """Update the data_jobs row for this run; always stamps heartbeat_at.

    Runs in its own session/commit (see _data_migration_job_session), so this
    never shares a transaction with the migration-work session and is durable
    the instant it returns.

    Best-effort: job rows are observability only, so a failed bookkeeping
    write must never raise into run_data_migrations - it could otherwise mark
    a succeeded migration as failed, or abort remaining pending migrations.
    Any exception is logged and swallowed.
    """
    try:
        with _data_migration_job_session() as db:
            db.execute(
                sa_update(DataJob)
                .where(DataJob.job_type == "data_migration", DataJob.job_key == job_key)
                .values(heartbeat_at=func.now(), **values)
            )
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning(
            "data_migrations: could not update job row for job_key=%s "
            "(values=%s); migration outcome is unaffected",
            job_key, sorted(values.keys()), exc_info=True,
        )


@celery_app.task(bind=True, name="app.worker.tasks.run_data_migrations")
def run_data_migrations(self, from_version: int) -> dict:
    """Run pending data migrations dispatched by startup version check.

    Maintains a durable data_jobs row (job_type="data_migration",
    job_key=str(DATA_VERSION), i.e. the target version for this upgrade run)
    tracking status/progress/errors alongside the migration work. Job-row
    writes always go through _pickup_data_migration_job /
    _update_data_migration_job, which use their own session and commit
    independently of the migration-work session below -- a job-status update
    is never rolled back with a failed migration, and is durable and visible
    to concurrent readers immediately. Completion authority for which
    migrations run stays with app_metadata.data_version via
    get_pending_migrations; this job row is observability only.
    """
    from app.services.data_migrations import (
        DATA_VERSION, get_pending_migrations, set_data_version,
    )

    job_key = str(DATA_VERSION)

    # Acquire lock to prevent duplicate runs on rapid restarts
    if not _redis.set(DATA_MIGRATION_LOCK, "1", nx=True, ex=DATA_MIGRATION_LOCK_TTL):
        logger.info("data_migrations: another migration is already running, skipping")
        return {"status": "skipped"}

    try:
        pending = get_pending_migrations(from_version)
        total_steps = len(pending)
        _pickup_data_migration_job(
            job_key, total_steps,
            f"Upgrading v{from_version} -> v{DATA_VERSION} ({total_steps} migrations pending)",
        )

        if not pending:
            logger.info("data_migrations: no pending migrations (v%d is current)", from_version)
            _update_data_migration_job(
                job_key, status=DataJobStatus.succeeded, step=0, total_steps=0,
                message="No pending migrations", finished_at=func.now(),
            )
            return {"status": "noop"}

        logger.info("data_migrations: upgrading v%d -> v%d (%d migrations)",
                    from_version, DATA_VERSION, len(pending))

        results = []
        step = 0
        with Session(_sync_engine) as session:
            for ver, desc, migrate_fn in pending:
                logger.info("data_migrations: running v%d - %s", ver, desc)
                try:
                    summary = migrate_fn(session)
                    set_data_version(session, ver)
                    session.commit()
                except SoftTimeLimitExceeded:
                    # The task hit its (generous) time limit mid-migration.
                    # Long per-target migration loops commit their work in
                    # chunks, so that partial progress is already durable; only
                    # the uncommitted tail is rolled back here. The version is
                    # deliberately NOT stamped, so the entrypoint re-dispatches
                    # this same migration on the next boot -- but because the
                    # per-target enrichers skip already-enriched targets, the
                    # replay is cheap and each run advances further until it
                    # finally completes (AUD-035). A terminal activity event is
                    # always written so this is never a silent loop.
                    session.rollback()
                    msg = (
                        f"Data upgrade v{ver} ({desc}) paused at the task time "
                        f"limit; committed progress is preserved and it will "
                        f"resume on the next restart."
                    )
                    logger.warning("data_migrations: %s", msg)
                    _update_data_migration_job(
                        job_key, status=DataJobStatus.interrupted, step=step,
                        total_steps=total_steps, message=msg,
                    )
                    with _activity_session() as _db:
                        _emit_activity_sync(
                            _db, redis=_redis, category="migration", severity="warning",
                            event_type="data_upgrade_paused",
                            message=msg,
                            details={"version": ver}, actor="system",
                        )
                    return {"status": "timeout", "version": ver}
                except Exception as e:
                    session.rollback()
                    error_msg = f"Data upgrade failed at v{ver} ({desc}): {e}"
                    logger.exception("data_migrations: %s", error_msg)
                    _update_data_migration_job(
                        job_key, status=DataJobStatus.failed, step=step,
                        total_steps=total_steps, message=error_msg,
                        last_error=str(e), finished_at=func.now(),
                    )
                    with _activity_session() as _db:
                        _emit_activity_sync(
                            _db, redis=_redis, category="migration", severity="error",
                            event_type="data_upgrade_failed",
                            message=f"{error_msg}. Press Quick Fix to retry.",
                            details={"version": ver, "error": str(e)},
                            actor="system",
                        )
                    return {"status": "error", "version": ver, "error": str(e)}

                # v{ver} is committed and version-stamped at this point. The
                # bookkeeping below sits outside the try/except (and the
                # helpers swallow their own errors) so a failed observability
                # write can never demote a succeeded migration to failed or
                # stop the remaining pending migrations from running.
                results.append(f"v{ver}: {summary}")
                step += 1
                _update_data_migration_job(
                    job_key, step=step, total_steps=total_steps,
                    message=f"v{ver}: {summary} complete"
                    + (f"; running v{pending[step][0]}..." if step < total_steps else ""),
                )
                logger.info("data_migrations: v%d complete - %s", ver, summary)

        summary_msg = "Data upgrade complete: " + "; ".join(results)
        _update_data_migration_job(
            job_key, status=DataJobStatus.succeeded, step=total_steps,
            total_steps=total_steps, message=summary_msg, finished_at=func.now(),
        )
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="migration", severity="info",
                event_type="data_upgrade_complete",
                message=summary_msg,
                details={"from_version": from_version, "to_version": DATA_VERSION},
                actor="system",
            )
        logger.info("data_migrations: %s", summary_msg)

        # Queue quick fix + mosaic detection after data migrations
        smart_rebuild_targets.apply_async(countdown=5)
        detect_mosaic_panels_task.apply_async(countdown=30)

        return {"status": "complete", "from": from_version, "to": DATA_VERSION}
    finally:
        _redis.delete(DATA_MIGRATION_LOCK)


@celery_app.task(bind=True, name="app.worker.tasks.load_reference_catalogs_if_empty")
def load_reference_catalogs_if_empty(self) -> dict:
    """Load static reference catalogs (OpenNGC, SAC, Caldwell, Herschel 400,
    Arp, Abell) on boot if they have never been loaded.

    Dispatched unconditionally from the entrypoint on every startup. The v2.0
    baseline seeds fresh databases at the current data_version, so the data
    migrations that used to load these catalogs as a side effect (v3, v7, v13)
    never run against a fresh install, leaving the catalog tables permanently
    empty. Gating on emptiness here (rather than always reloading) keeps
    normal restarts of an already-loaded install cheap, while every loader
    invoked by load_reference_catalogs is itself an idempotent upsert, so a
    second run - e.g. a retry after a crash mid-load - never duplicates rows.
    """
    from app.services.data_migrations import (
        reference_catalogs_are_empty, load_reference_catalogs,
    )

    if not _redis.set(REFERENCE_CATALOG_LOCK, "1", nx=True, ex=REFERENCE_CATALOG_LOCK_TTL):
        logger.info("reference_catalogs: another load is already running, skipping")
        return {"status": "skipped"}

    try:
        with Session(_sync_engine) as session:
            if not reference_catalogs_are_empty(session):
                return {"status": "noop"}

            logger.info("reference_catalogs: openngc_catalog is empty, loading static catalogs")
            try:
                summary = load_reference_catalogs(session)
                session.commit()
            except Exception as e:
                session.rollback()
                error_msg = f"Reference catalog load failed: {e}"
                logger.exception("reference_catalogs: %s", error_msg)
                with _activity_session() as _db:
                    _emit_activity_sync(
                        _db, redis=_redis, category="migration", severity="error",
                        event_type="reference_catalog_load_failed",
                        message=error_msg,
                        details={"error": str(e)}, actor="system",
                    )
                return {"status": "error", "error": str(e)}

            logger.info("reference_catalogs: %s", summary)
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="migration", severity="info",
                    event_type="reference_catalog_load_complete",
                    message=f"Reference catalogs loaded: {summary}",
                    details={}, actor="system",
                )
            return {"status": "loaded", "summary": summary}
    finally:
        _redis.delete(REFERENCE_CATALOG_LOCK)
