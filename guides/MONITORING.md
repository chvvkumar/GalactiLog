# Application Monitoring

GalactiLog exposes a Prometheus-compatible metrics endpoint at `/api/metrics`. The endpoint requires no authentication and returns standard Prometheus text format.

## Metrics Exposed

### HTTP

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `galactilog_http_request_duration_seconds` | Histogram | method, endpoint, status_code | Request latency |
| `galactilog_http_requests_total` | Counter | method, endpoint, status_code | Request count |

### Database

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `galactilog_db_query_duration_seconds` | Histogram | (none) | Individual query execution time |
| `galactilog_db_queries_per_request` | Histogram | endpoint | Queries issued per HTTP request |
| `galactilog_db_pool_size` | Gauge | (none) | Connection pool size |
| `galactilog_db_pool_checked_out` | Gauge | (none) | Connections in use |
| `galactilog_db_pool_overflow` | Gauge | (none) | Overflow connections active |

### Celery

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `galactilog_celery_task_duration_seconds` | Histogram | task_name | Task execution time |
| `galactilog_celery_task_failures_total` | Counter | task_name | Task failure count |
| `galactilog_celery_queue_depth` | Gauge | (none) | Tasks waiting in Redis |
| `galactilog_celery_workers_active` | Gauge | (none) | Worker slots processing |
| `galactilog_celery_workers_total` | Gauge | (none) | Total worker slots |

## Scraping with Prometheus

Add a scrape target to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: galactilog
    scrape_interval: 30s
    metrics_path: /api/metrics
    static_configs:
      - targets: ["astrodb.lan:8080"]
```

## Grafana Dashboard

A pre-built dashboard is available in the GalactiLog folder on Grafana. It includes:

* Request rate and latency by endpoint (time series)
* Stat panels for total requests, average latency, pool utilization, queue depth, and worker count
* Queries per request by endpoint (bar chart, useful for detecting N+1 patterns)
* Average query duration over time
* Connection pool utilization (pool size vs checked out vs overflow)
* Celery queue depth and worker utilization

### Example: Queries Per Request

The `galactilog_db_queries_per_request` metric tracks how many database queries each HTTP request issues. High values indicate N+1 query patterns. Sample PromQL:

```promql
# Average queries per request by endpoint (over 5m windows)
rate(galactilog_db_queries_per_request_sum[5m])
  / rate(galactilog_db_queries_per_request_count[5m])
```

### Example: Request Latency

```promql
# Average request latency by endpoint (over 5m windows)
rate(galactilog_http_request_duration_seconds_sum[5m])
  / rate(galactilog_http_request_duration_seconds_count[5m])
```

### Example: P95 Latency

```promql
histogram_quantile(0.95,
  rate(galactilog_http_request_duration_seconds_bucket[5m])
)
```

## Endpoint Labels

The `endpoint` label uses route templates (e.g., `/api/targets/{target_id}`), not resolved paths. This keeps label cardinality bounded regardless of how many targets or mosaics exist in the database.
