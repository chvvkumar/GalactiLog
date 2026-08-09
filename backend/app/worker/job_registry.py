"""Live Celery job registry: every queued or running task, visible to the UI.

Celery signal handlers write one small Redis hash per in-flight task, and
GET /api/jobs reads them back for the nav job monitor. Hooking the signals
rather than the dispatch sites is deliberate: a task added next year is
covered with zero per-task code, and no call site can forget to register
(the same structural-over-conventional argument as auth at the route table).

State model, one hash per task id under ``jobs:entry:<id>`` plus an id set
under ``jobs:active``:

- before_task_publish -> state "queued". This signal fires in whichever
  process enqueues (API, worker cascade, beat), so a task sitting behind a
  countdown or a busy worker is visible from the moment of dispatch - the
  gap the monitor previously could not see.
- task_prerun -> state "running". Also re-adds the id to the active set so a
  task whose publish record was lost still shows while running.
- task_postrun -> entry deleted. Fires on success and failure alike; the
  activity feed, not this registry, is the durable outcome record.

Entries carry a TTL because a SIGKILLed worker (hard time limit, OOM) never
fires task_postrun, and a phantom "running" row that outlives its task by a
week is worse than one that quietly expires.

SUPPRESSED_TASKS names the work already surfaced by a richer source (scan
status envelope, rebuild status), which the monitor renders with progress
bars and cancel buttons this registry cannot know about. Suppression happens
write-side, not in the API read, because run_scan fans out one ingest_file
task per new file: recording tens of thousands of throwaway entries to
filter them out later would be pure Redis churn.
"""
import logging
import time

logger = logging.getLogger(__name__)

JOB_ENTRY_PREFIX = "jobs:entry:"
JOBS_ACTIVE_SET = "jobs:active"
JOB_ENTRY_TTL_S = 3600

# Tasks the scan-status envelope already covers, including its per-file
# ingest fan-out, and the rebuild-status family (REBUILD_KEY modes smart /
# full / retry / ref_thumbnails / regen plus regen's per-image fan-out).
SUPPRESSED_TASKS = frozenset({
    "app.worker.tasks.run_scan",
    "app.worker.tasks.ingest_file",
    "app.worker.tasks.reingest_changed_file",
    "app.worker.tasks.scan_phd2_logs",
    "app.worker.tasks.rebuild_targets",
    "app.worker.tasks.retry_unresolved",
    "app.worker.tasks.smart_rebuild_targets",
    "app.worker.tasks.generate_reference_thumbnails",
    "app.worker.tasks.regenerate_thumbnail",
    "regenerate_missing_thumbnails",
    "purge_and_regenerate_thumbnails",
    # Housekeeping heartbeat, published every 5s. Never worth a monitor row,
    # and while a scan holds the worker pool its backlog would otherwise fill
    # the panel with tens of rows that represent no user-visible work.
    "app.worker.drain_logs.drain_app_logs",
})


def register_job_signals():
    """Connect the registry's Celery signals. Call once per process.

    Registered from celery_app.py, which the API process imports on its first
    enqueue and the worker/beat processes import at startup, so the publish
    signal is live everywhere a task can be born. dispatch_uid makes repeat
    calls idempotent. Every handler swallows Redis errors: visibility must
    never fail the work it is watching (same tolerance as _queue_worker_task).
    """
    from celery.signals import before_task_publish, task_prerun, task_postrun
    import redis as _redis_mod

    _client = None

    def _get_redis():
        nonlocal _client
        if _client is None:
            from app.config import settings
            _client = _redis_mod.from_url(settings.redis_url)
        return _client

    @before_task_publish.connect(dispatch_uid="galactilog_jobs_publish", weak=False)
    def _on_publish(sender=None, headers=None, **_kwargs):
        name = sender or (headers or {}).get("task")
        task_id = (headers or {}).get("id")
        if not name or not task_id or name in SUPPRESSED_TASKS:
            return
        try:
            record_queued(_get_redis(), task_id, name, eta=(headers or {}).get("eta"))
        except Exception:
            logger.debug("job registry: publish write failed", exc_info=True)

    @task_prerun.connect(dispatch_uid="galactilog_jobs_prerun", weak=False)
    def _on_prerun(task_id=None, task=None, **_kwargs):
        name = getattr(task, "name", None)
        if not task_id or not name or name in SUPPRESSED_TASKS:
            return
        try:
            record_running(_get_redis(), task_id, name)
        except Exception:
            logger.debug("job registry: prerun write failed", exc_info=True)

    @task_postrun.connect(dispatch_uid="galactilog_jobs_postrun", weak=False)
    def _on_postrun(task_id=None, task=None, **_kwargs):
        name = getattr(task, "name", None)
        if not task_id or (name and name in SUPPRESSED_TASKS):
            return
        try:
            clear_entry(_get_redis(), task_id)
        except Exception:
            logger.debug("job registry: postrun cleanup failed", exc_info=True)


# The write operations are module-level functions taking an explicit client
# so tests can drive them against the test Redis without Celery in the loop.

def record_queued(r, task_id: str, name: str, eta: str | None = None) -> None:
    mapping = {"name": name, "state": "queued", "queued_at": time.time()}
    if eta:
        mapping["eta"] = eta
    pipe = r.pipeline()
    key = JOB_ENTRY_PREFIX + task_id
    pipe.hset(key, mapping=mapping)
    pipe.expire(key, JOB_ENTRY_TTL_S)
    pipe.sadd(JOBS_ACTIVE_SET, task_id)
    pipe.execute()


def record_running(r, task_id: str, name: str) -> None:
    key = JOB_ENTRY_PREFIX + task_id
    pipe = r.pipeline()
    # name is written here too, not just at publish: a run whose publish
    # record expired (long countdown) or was never seen still gets a full row.
    pipe.hset(key, mapping={
        "name": name, "state": "running", "started_at": time.time(),
    })
    pipe.expire(key, JOB_ENTRY_TTL_S)
    pipe.sadd(JOBS_ACTIVE_SET, task_id)
    pipe.execute()


def clear_entry(r, task_id: str) -> None:
    pipe = r.pipeline()
    pipe.delete(JOB_ENTRY_PREFIX + task_id)
    pipe.srem(JOBS_ACTIVE_SET, task_id)
    pipe.execute()
