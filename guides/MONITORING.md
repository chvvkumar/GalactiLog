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

## Scraping with Telegraf

Add a config file to `/etc/telegraf/telegraf.d/`:

```ini
# /etc/telegraf/telegraf.d/galactilog.conf
[[inputs.prometheus]]
  urls = ["http://astrodb.lan:8080/api/metrics"]
  interval = "30s"
  namepass = ["galactilog_*"]
  [inputs.prometheus.tags]
    source = "galactilog"
```

Reload telegraf:

```bash
sudo systemctl reload telegraf
```

Metrics flow into InfluxDB under the `telegraf` database with measurement names matching the metric names above.

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

The `galactilog_db_queries_per_request` metric tracks how many database queries each HTTP request issues. High values indicate N+1 query patterns. Sample InfluxDB query:

```sql
SELECT non_negative_derivative(last("sum"), 1s)
     / non_negative_derivative(last("count"), 1s)
FROM "galactilog_db_queries_per_request"
WHERE ("source" = 'galactilog') AND $timeFilter
GROUP BY time($__interval), "endpoint"
fill(null)
```

### Example: Request Latency

```sql
SELECT non_negative_derivative(last("sum"), 1s)
     / non_negative_derivative(last("count"), 1s)
FROM "galactilog_http_request_duration_seconds"
WHERE ("source" = 'galactilog') AND $timeFilter
GROUP BY time($__interval), "endpoint"
fill(null)
```

## Endpoint Labels

The `endpoint` label uses route templates (e.g., `/api/targets/{target_id}`), not resolved paths. This keeps label cardinality bounded regardless of how many targets or mosaics exist in the database.
