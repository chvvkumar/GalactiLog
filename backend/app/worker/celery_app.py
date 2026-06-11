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
    },
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


def _emit_task_event(event_type, severity, task_name, task_id, exc):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import settings, get_sync_redis
    from app.services.activity import emit_sync
    url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=1)
    redis = get_sync_redis()
    verb = "failed" if event_type == "task_failure" else "retrying"
    try:
        with Session(engine) as s:
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
        engine.dispose()


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, **_):
    name = getattr(sender, "name", "unknown")
    _emit_task_event("task_failure", "error", name, task_id, exception or Exception("unknown"))


@task_retry.connect
def _on_task_retry(sender=None, request=None, reason=None, **_):
    name = getattr(sender, "name", "unknown")
    tid = getattr(request, "id", None)
    _emit_task_event("task_retry", "warning", name, tid, reason or Exception("retry"))
