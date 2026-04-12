import time
import threading
import logging

from prometheus_client import Counter, Histogram, Gauge

logger = logging.getLogger(__name__)

_request_local = threading.local()

HTTP_REQUEST_DURATION = Histogram(
    "galactilog_http_request_duration_seconds",
    "HTTP request latency end-to-end",
    ["method", "endpoint", "status_code"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_REQUESTS_TOTAL = Counter(
    "galactilog_http_requests_total",
    "Total HTTP request count",
    ["method", "endpoint", "status_code"],
)

DB_QUERY_DURATION = Histogram(
    "galactilog_db_query_duration_seconds",
    "Individual DB query execution time",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

DB_QUERIES_PER_REQUEST = Histogram(
    "galactilog_db_queries_per_request",
    "Number of DB queries issued per HTTP request",
    ["endpoint"],
    buckets=[1, 2, 5, 10, 25, 50, 100, 250],
)

DB_POOL_SIZE = Gauge("galactilog_db_pool_size", "Current DB connection pool size")
DB_POOL_CHECKED_OUT = Gauge("galactilog_db_pool_checked_out", "DB connections currently in use")
DB_POOL_OVERFLOW = Gauge("galactilog_db_pool_overflow", "DB overflow connections active")

CELERY_TASK_DURATION = Histogram(
    "galactilog_celery_task_duration_seconds",
    "Celery task execution duration",
    ["task_name"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

CELERY_TASK_FAILURES = Counter(
    "galactilog_celery_task_failures_total",
    "Celery task failure count",
    ["task_name"],
)

CELERY_QUEUE_DEPTH = Gauge("galactilog_celery_queue_depth", "Tasks waiting in Redis queue")
CELERY_WORKERS_ACTIVE = Gauge("galactilog_celery_workers_active", "Worker slots currently processing tasks")
CELERY_WORKERS_TOTAL = Gauge("galactilog_celery_workers_total", "Total worker slots available")

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/api/metrics":
            return await call_next(request)

        _request_local.query_count = 0

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = request.scope.get("route")
        endpoint = route.path if route is not None else request.url.path

        method = request.method
        status = str(response.status_code)

        HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint, status_code=status).observe(duration)
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=status).inc()

        query_count = getattr(_request_local, 'query_count', 0)
        if query_count > 0:
            DB_QUERIES_PER_REQUEST.labels(endpoint=endpoint).observe(query_count)

        return response


def register_db_listeners(sync_engine):
    """Attach query timing and pool instrumentation to a SQLAlchemy sync engine.

    Pass engine.sync_engine when working with an AsyncEngine.
    Call once after engine construction.
    """
    from sqlalchemy import event

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info["query_start"] = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start = conn.info.pop("query_start", None)
        if start is not None:
            DB_QUERY_DURATION.observe(time.perf_counter() - start)
        _request_local.query_count = getattr(_request_local, 'query_count', 0) + 1

    pool = sync_engine.pool

    @event.listens_for(pool, "checkout")
    def on_checkout(dbapi_conn, conn_record, conn_proxy):
        DB_POOL_CHECKED_OUT.inc()
        DB_POOL_SIZE.set(pool.size())
        DB_POOL_OVERFLOW.set(pool.overflow())

    @event.listens_for(pool, "checkin")
    def on_checkin(dbapi_conn, conn_record):
        DB_POOL_CHECKED_OUT.dec()
        DB_POOL_SIZE.set(pool.size())
        DB_POOL_OVERFLOW.set(pool.overflow())


def register_celery_signals():
    """Connect Celery signals for task timing and failure counting.

    Call once at worker startup. dispatch_uid prevents duplicate connections
    if this function is called more than once in the same process.
    """
    from celery.signals import task_prerun, task_postrun, task_failure

    @task_prerun.connect(dispatch_uid="galactilog_task_prerun")
    def on_task_prerun(task_id, task, *args, **kwargs):
        task.request._metrics_start = time.perf_counter()

    @task_postrun.connect(dispatch_uid="galactilog_task_postrun")
    def on_task_postrun(task_id, task, *args, **kwargs):
        start = getattr(task.request, "_metrics_start", None)
        if start is not None:
            CELERY_TASK_DURATION.labels(task_name=task.name).observe(
                time.perf_counter() - start
            )

    @task_failure.connect(dispatch_uid="galactilog_task_failure")
    def on_task_failure(task_id, exception, traceback, sender, *args, **kwargs):
        CELERY_TASK_FAILURES.labels(task_name=sender.name).inc()


def start_queue_depth_probe(celery_app, redis_url: str, interval: int = 15):
    """Start a daemon thread that polls Redis and Celery inspect every `interval` seconds.

    Call from the worker_ready signal in tasks.py. Runs only in the worker process.
    """
    import redis as sync_redis

    def _probe():
        r = sync_redis.from_url(redis_url, decode_responses=True)
        while True:
            try:
                depth = r.llen("celery")
                CELERY_QUEUE_DEPTH.set(depth if depth is not None else 0)
            except Exception:
                logger.debug("Queue depth probe: Redis query failed", exc_info=True)

            try:
                inspector = celery_app.control.inspect(timeout=2)
                active = inspector.active() or {}
                stats = inspector.stats() or {}

                active_count = sum(len(tasks) for tasks in active.values())
                total_slots = sum(
                    s.get("pool", {}).get("max-concurrency", 0)
                    for s in stats.values()
                )
                CELERY_WORKERS_ACTIVE.set(active_count)
                CELERY_WORKERS_TOTAL.set(total_slots)
            except Exception:
                logger.debug("Queue depth probe: Celery inspect failed", exc_info=True)

            time.sleep(interval)

    t = threading.Thread(target=_probe, daemon=True, name="metrics-queue-probe")
    t.start()
    logger.info("Prometheus queue depth probe started (interval=%ds)", interval)
