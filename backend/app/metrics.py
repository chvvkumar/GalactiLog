import time
import threading
import logging

from prometheus_client import Counter, Histogram, Gauge
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, HistogramMetricFamily, REGISTRY

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
    """Connect Celery signals that write task metrics to Redis.

    Metrics are bridged to Prometheus by CeleryTaskCollector (below).
    Call once at worker startup. dispatch_uid prevents duplicate connections
    if this function is called more than once in the same process.
    """
    from celery.signals import task_prerun, task_postrun, task_failure
    import redis as _redis_mod

    _redis_client = None

    def _get_redis():
        nonlocal _redis_client
        if _redis_client is None:
            import os
            url = os.environ.get("GALACTILOG_REDIS_URL", "redis://localhost:6379/0")
            _redis_client = _redis_mod.from_url(url)
        return _redis_client

    @task_prerun.connect(dispatch_uid="galactilog_task_prerun", weak=False)
    def on_task_prerun(task_id, task, *args, **kwargs):
        task.request._metrics_start = time.perf_counter()

    @task_postrun.connect(dispatch_uid="galactilog_task_postrun", weak=False)
    def on_task_postrun(task_id, task, *args, **kwargs):
        start = getattr(task.request, "_metrics_start", None)
        if start is None:
            return
        duration = time.perf_counter() - start
        task_name = task.name
        try:
            r = _get_redis()
            pipe = r.pipeline()
            pipe.hincrbyfloat("galactilog:task_duration_sum", task_name, duration)
            pipe.hincrby("galactilog:task_duration_count", task_name, 1)
            for bucket in [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]:
                if duration <= bucket:
                    pipe.hincrby(f"galactilog:task_duration_bucket:{bucket}", task_name, 1)
            pipe.hincrby("galactilog:task_duration_bucket:+Inf", task_name, 1)
            pipe.execute()
        except Exception:
            logger.debug("Failed to write task metrics to Redis", exc_info=True)

    @task_failure.connect(dispatch_uid="galactilog_task_failure", weak=False)
    def on_task_failure(task_id, exception, traceback, sender, *args, **kwargs):
        try:
            r = _get_redis()
            r.hincrby("galactilog:task_failures", sender.name, 1)
        except Exception:
            logger.debug("Failed to write task failure to Redis", exc_info=True)


def start_queue_depth_probe(celery_app, redis_url: str, interval: int = 15):
    """Start a daemon thread that polls Redis and Celery inspect every `interval` seconds.

    Call from the lifespan function in main.py so gauges are written into the
    uvicorn process registry and are visible at the /metrics endpoint.
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


class CeleryTaskCollector:
    """Custom collector that reads Celery task metrics from Redis on each scrape."""

    _BUCKETS = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float("inf")]

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            import redis as _redis_mod
            self._redis = _redis_mod.from_url(self._redis_url)
        return self._redis

    def collect(self):
        try:
            r = self._get_redis()
        except Exception:
            return

        # Task duration histogram
        try:
            count_map = r.hgetall("galactilog:task_duration_count") or {}
            sum_map = r.hgetall("galactilog:task_duration_sum") or {}
            task_names = set(k.decode() for k in count_map.keys())

            if task_names:
                h = HistogramMetricFamily(
                    "galactilog_celery_task_duration_seconds",
                    "Celery task execution duration",
                    labels=["task_name"],
                )
                for task_name in sorted(task_names):
                    count = int(count_map.get(task_name.encode(), 0))
                    total = float(sum_map.get(task_name.encode(), 0))
                    buckets = []
                    for le in [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]:
                        bucket_key = f"galactilog:task_duration_bucket:{le}"
                        val = r.hget(bucket_key, task_name)
                        buckets.append((str(le), int(val or 0)))
                    inf_val = r.hget("galactilog:task_duration_bucket:+Inf", task_name)
                    buckets.append(("+Inf", int(inf_val or 0)))
                    h.add_metric([task_name], buckets=buckets, sum_value=total)
                yield h
        except Exception:
            logger.debug("Failed to collect task duration metrics", exc_info=True)

        # Task failures counter
        try:
            failure_map = r.hgetall("galactilog:task_failures") or {}
            if failure_map:
                c = CounterMetricFamily(
                    "galactilog_celery_task_failures_total",
                    "Celery task failure count",
                    labels=["task_name"],
                )
                for task_name_bytes, count_bytes in failure_map.items():
                    c.add_metric([task_name_bytes.decode()], float(count_bytes))
                yield c
        except Exception:
            logger.debug("Failed to collect task failure metrics", exc_info=True)


def register_celery_collector(redis_url: str):
    """Register the custom Celery task collector. Call once from main.py."""
    REGISTRY.register(CeleryTaskCollector(redis_url))
