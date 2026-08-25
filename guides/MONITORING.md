# Application Monitoring

GalactiLog exposes a Prometheus-compatible metrics endpoint at `/api/metrics`, returning standard Prometheus text format. Access is controlled by two independent layers: an nginx network allowlist that is always in effect, and an optional bearer token. See [Access control](#access-control).

## Access control

### nginx allowlist

nginx serves `/api/metrics` from an exact-match location that permits only these sources and denies everything else:

| Source | Purpose |
|--------|---------|
| `127.0.0.1` | In-container scrapers and health checks |
| `10.0.0.0/8` | Private and Docker networks |
| `172.16.0.0/12` | Private and Docker bridge networks |
| `192.168.0.0/16` | Private LAN |

The check runs against the connecting peer address as nginx sees it. A client reaching GalactiLog through a further reverse proxy presents that proxy's address here, so an upstream proxy on a private address defeats the allowlist. Use the bearer token in that case.

This allowlist is unconditional. It applies whether or not a token is configured, and there is no environment variable to widen or disable it; change `nginx.conf` if the ranges do not fit your network.

### Bearer token

Set `GALACTILOG_METRICS_TOKEN` to require a token in addition to the allowlist. When it is set, a request must carry:

```
Authorization: Bearer <token>
```

The `Bearer ` scheme prefix is required, the token must be non-empty, and the value is compared in constant time. A request with no header, a different scheme, an empty token, or a wrong token receives 401. When the variable is unset, no token is required and the allowlist is the only control.

Generate a token with:

```bash
openssl rand -hex 32
```

Configure the scraper to send it. For Prometheus:

```yaml
scrape_configs:
  - job_name: galactilog
    scrape_interval: 30s
    metrics_path: /api/metrics
    authorization:
      credentials: "<token>"
    static_configs:
      - targets: ["astrodb.lan:8080"]
```

For Telegraf's `inputs.prometheus`:

```toml
[[inputs.prometheus]]
  urls = ["http://astrodb.lan:8080/api/metrics"]
  bearer_token_string = "<token>"
```

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

The scraper must reach the endpoint from an address the nginx allowlist permits. Add an `authorization` block when `GALACTILOG_METRICS_TOKEN` is set; see [Bearer token](#bearer-token).

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
