from celery import Celery

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
    beat_schedule={
        "auto-scan-tick": {
            "task": "app.worker.tasks.auto_scan_tick",
            "schedule": 60.0,
        },
    },
)

celery_app.autodiscover_tasks(["app.worker"])

from app.metrics import register_celery_signals
register_celery_signals()
