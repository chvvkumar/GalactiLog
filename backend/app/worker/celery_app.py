from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "astro_cataloger",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=660,
    task_annotations={
        "app.worker.tasks.ingest_file": {
            "soft_time_limit": 120,
            "time_limit": 150,
        },
        # Long-running maintenance tasks iterate the whole target/catalog set
        # with per-item network calls and pacing sleeps, so on a large catalog
        # they legitimately run well past the global 600s/660s limit. Without
        # an override they get hard-killed mid-loop, which for the rebuild
        # family strands REBUILD_KEY at "running" (AUD-003) and for the data
        # migration runner rolls the whole version back and replays it every
        # boot (AUD-035). Give them a generous ceiling; chunked commits +
        # SoftTimeLimitExceeded handlers still guarantee durable progress and a
        # terminal state if this ceiling is ever reached.
        "app.worker.tasks.generate_reference_thumbnails": {
            "soft_time_limit": 7200,
            "time_limit": 7320,
        },
        "app.worker.tasks.rebuild_targets": {
            "soft_time_limit": 7200,
            "time_limit": 7320,
        },
        "app.worker.tasks.retry_unresolved": {
            "soft_time_limit": 7200,
            "time_limit": 7320,
        },
        "app.worker.tasks.run_data_migrations": {
            "soft_time_limit": 10800,
            "time_limit": 10920,
        },
        "app.worker.tasks.backfill_dark_hours": {
            "soft_time_limit": 3600,
            "time_limit": 3720,
        },
        # High-frequency beat tasks whose results are never read. Storing a
        # result backend entry for each just accumulates celery-task-meta-*
        # keys in Redis (drain_app_logs alone runs every 5s). Skip the result
        # backend for them entirely.
        "app.worker.drain_logs.drain_app_logs": {"ignore_result": True},
        "app.worker.prune_activity.prune_activity_events": {"ignore_result": True},
        "app.worker.tasks.auto_scan_tick": {"ignore_result": True},
    },
    # Cap how long task results linger in the result backend. Anything that
    # still writes a result expires within an hour (well under one day) rather
    # than accumulating unbounded.
    result_expires=3600,
    broker_transport_options={"socket_timeout": 5, "socket_connect_timeout": 5},
    result_backend_transport_options={"socket_timeout": 5},
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "auto-scan-tick": {
            "task": "app.worker.tasks.auto_scan_tick",
            "schedule": 60.0,
        },
        "prune-activity-events": {
            "task": "app.worker.prune_activity.prune_activity_events",
            "schedule": crontab(hour=3, minute=0),
        },
        "drain-app-logs": {
            "task": "app.worker.drain_logs.drain_app_logs",
            "schedule": 5.0,
        },
    },
)

celery_app.autodiscover_tasks(["app.worker"])

# autodiscover_tasks only imports each package's `tasks` module. Tasks defined in
# sibling modules are only registered when those modules are imported, so import
# them explicitly here -- otherwise beat dispatches them by name and the worker
# rejects them as "unregistered task". celery_app is already bound above, so these
# imports do not create a circular-import problem.
from app.worker import prune_activity as _prune_activity  # noqa: E402,F401
from app.worker import drain_logs as _drain_logs  # noqa: E402,F401

from app.metrics import register_celery_signals
register_celery_signals()


# ---------------------------------------------------------------------------
# Backend log capture: install RedisLogHandler in worker and beat processes.
# ---------------------------------------------------------------------------
from celery.signals import worker_process_init, beat_init


def _install_log_handler(source: str):
    import logging
    from app.services.log_capture import RedisLogHandler
    root = logging.getLogger()
    if not any(isinstance(h, RedisLogHandler) for h in root.handlers):
        root.addHandler(RedisLogHandler(source=source))
    # Lower the app logger so debug/info records reach the handler; the handler's
    # runtime capture floor decides what is actually recorded. Without this, the
    # default root level (WARNING) drops debug/info at the call site and the
    # capture-level setting below WARNING would have no effect. Library loggers
    # stay at root level, keeping their debug noise out.
    logging.getLogger("app").setLevel(logging.DEBUG)


@worker_process_init.connect
def _worker_log_handler(**_kwargs):
    _install_log_handler("worker")


@beat_init.connect
def _beat_log_handler(**_kwargs):
    _install_log_handler("beat")


# ---------------------------------------------------------------------------
# Curated activity events for Celery task failures and retries.
# ---------------------------------------------------------------------------
from celery.signals import task_failure, task_retry

# Lazily-built module-level sync engine, reused across task-failure/retry signals
# (mirrors drain_logs.py / prune_activity.py) to avoid per-call FD churn during a
# task-failure storm.
_task_event_engine = None


def _get_task_event_engine():
    global _task_event_engine
    if _task_event_engine is None:
        from sqlalchemy import create_engine
        from app.config import settings
        url = settings.database_url.replace("+asyncpg", "+psycopg2")
        _task_event_engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=1, pool_recycle=1800)
    return _task_event_engine


def _emit_task_event(event_type, severity, task_name, task_id, exc):
    from sqlalchemy.orm import Session
    from app.config import get_sync_redis
    from app.services.activity import emit_sync
    redis = get_sync_redis()
    verb = "failed" if event_type == "task_failure" else "retrying"
    try:
        with Session(_get_task_event_engine()) as s:
            emit_sync(
                s, redis=redis, category="system", severity=severity,
                event_type=event_type,
                message=f"Task {task_name} {verb}: {type(exc).__name__}",
                details={"task": task_name, "task_id": str(task_id), "error": str(exc)[:500]},
                actor="system",
            )
    except Exception:
        pass
    finally:
        try:
            redis.close()
        except Exception:
            pass


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, **_):
    name = getattr(sender, "name", "unknown")
    _emit_task_event("task_failure", "error", name, task_id, exception or Exception("unknown"))


@task_retry.connect
def _on_task_retry(sender=None, request=None, reason=None, **_):
    name = getattr(sender, "name", "unknown")
    tid = getattr(request, "id", None)
    _emit_task_event("task_retry", "warning", name, tid, reason or Exception("retry"))
