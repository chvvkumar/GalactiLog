import type { MetricFamily, Sample } from "./prometheusParse";

export type Health = "green" | "amber" | "red";

export interface ApiSummary {
  rps: number;
  errorRatePct: number;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
  slowest: Array<{ endpoint: string; method: string; status: string; p95Ms: number; rps: number }>;
  topErrors: Array<{ endpoint: string; status: string; count: number; sharePct: number }>;
  health: Health;
}

export interface DbSummary {
  qps: number;
  avgMs: number;
  p95Ms: number;
  p99Ms: number;
  poolUsed: number;
  poolSize: number;
  overflow: number;
  qprMedian: number;
  qprP95: number;
  qprMax: number;
  health: Health;
}

export interface JobsSummary {
  queueDepth: number;
  workersActive: number;
  workersTotal: number;
  failuresWindow: number;
  slowest: Array<{ taskName: string; p95Seconds: number; runs: number }>;
  failures: Array<{ taskName: string; count: number }>;
  health: Health;
}

export interface OverallSummary {
  uptimeSeconds: number;
  memoryBytes: number;
  openFds: number;
  pythonVersion: string;
  startedAt: Date | null;
  gc: { gen0: number; gen1: number; gen2: number } | null;
  health: Health;
}

export interface PrevCounters {
  timestampMs: number;
  totals: Map<string, number>;
}

export const emptyPrev = (): PrevCounters => ({ timestampMs: 0, totals: new Map() });

function labelKey(name: string, labels: Record<string, string>): string {
  const keys = Object.keys(labels).filter((k) => k !== "__suffix__").sort();
  const parts = keys.map((k) => `${k}=${labels[k]}`);
  return name + "{" + parts.join(",") + "}";
}

function findFamily(families: MetricFamily[], name: string): MetricFamily | undefined {
  return families.find((f) => f.name === name);
}

function sumBySuffix(fam: MetricFamily | undefined, suffix: string, keyFilter?: (labels: Record<string, string>) => boolean): Sample[] {
  if (!fam) return [];
  return fam.samples.filter((s) => (s.labels["__suffix__"] ?? "") === suffix && (!keyFilter || keyFilter(s.labels)));
}

// Group histogram samples by the set of non-bucket labels (exclude "le", "__suffix__")
interface HistoSet {
  labels: Record<string, string>;
  buckets: Array<{ le: number; count: number }>;
  sum: number;
  count: number;
}

function groupHistogram(fam: MetricFamily | undefined): HistoSet[] {
  if (!fam) return [];
  const groups = new Map<string, HistoSet>();
  const keyOf = (labels: Record<string, string>) => {
    const keys = Object.keys(labels).filter((k) => k !== "le" && k !== "__suffix__").sort();
    return keys.map((k) => `${k}=${labels[k]}`).join(",");
  };
  for (const s of fam.samples) {
    const suffix = s.labels["__suffix__"] ?? "";
    const k = keyOf(s.labels);
    let g = groups.get(k);
    if (!g) {
      const lbl: Record<string, string> = {};
      for (const [lk, lv] of Object.entries(s.labels)) {
        if (lk !== "le" && lk !== "__suffix__") lbl[lk] = lv;
      }
      g = { labels: lbl, buckets: [], sum: 0, count: 0 };
      groups.set(k, g);
    }
    if (suffix === "_bucket") {
      const leRaw = s.labels["le"];
      const le = leRaw === "+Inf" ? Infinity : Number(leRaw);
      g.buckets.push({ le, count: s.value });
    } else if (suffix === "_sum") {
      g.sum = s.value;
    } else if (suffix === "_count") {
      g.count = s.value;
    }
  }
  for (const g of groups.values()) g.buckets.sort((a, b) => a.le - b.le);
  return Array.from(groups.values());
}

// Compute quantile using Prometheus histogram_quantile with linear interpolation.
// When the quantile lands in the +Inf bucket, return the upper bound of the previous finite bucket.
export function histogramQuantile(q: number, buckets: Array<{ le: number; count: number }>): number {
  if (!buckets.length) return 0;
  const sorted = buckets.slice().sort((a, b) => a.le - b.le);
  const total = sorted[sorted.length - 1]?.count ?? 0;
  if (total <= 0) return 0;
  const rank = q * total;
  let prevLe = 0;
  let prevCount = 0;
  for (let i = 0; i < sorted.length; i++) {
    const b = sorted[i];
    if (b.count >= rank) {
      if (!isFinite(b.le)) {
        // find last finite bucket upper bound
        for (let j = i - 1; j >= 0; j--) {
          if (isFinite(sorted[j].le)) return sorted[j].le;
        }
        return 0;
      }
      const bucketCount = b.count - prevCount;
      if (bucketCount <= 0) return b.le;
      const fraction = (rank - prevCount) / bucketCount;
      return prevLe + (b.le - prevLe) * fraction;
    }
    prevLe = isFinite(b.le) ? b.le : prevLe;
    prevCount = b.count;
  }
  return prevLe;
}

function mergeBuckets(groups: HistoSet[]): { buckets: Array<{ le: number; count: number }>; count: number; sum: number } {
  const byLe = new Map<number, number>();
  let count = 0;
  let sum = 0;
  for (const g of groups) {
    count += g.count;
    sum += g.sum;
    for (const b of g.buckets) {
      byLe.set(b.le, (byLe.get(b.le) ?? 0) + b.count);
    }
  }
  const buckets = Array.from(byLe.entries())
    .map(([le, c]) => ({ le, count: c }))
    .sort((a, b) => a.le - b.le);
  return { buckets, count, sum };
}

function rateFor(key: string, current: number, prev: PrevCounters, dtSeconds: number): number {
  if (prev.timestampMs === 0 || dtSeconds <= 0) return 0;
  const p = prev.totals.get(key);
  if (p === undefined) return 0;
  const d = current - p;
  if (d < 0) return 0;
  return d / dtSeconds;
}

function fmtPct(n: number): number {
  if (!isFinite(n)) return 0;
  return Math.max(0, n);
}

function healthApi(errPct: number, p95Ms: number): Health {
  if (errPct < 1 && p95Ms < 500) return "green";
  if (errPct < 5 || p95Ms < 2000) return "amber";
  return "red";
}

function healthDb(poolUsed: number, poolSize: number, overflow: number): Health {
  const ratio = poolSize > 0 ? poolUsed / poolSize : 0;
  if (ratio < 0.7 && overflow === 0) return "green";
  if (ratio < 0.9 && overflow === 0) return "amber";
  return "red";
}

function healthJobs(queueDepth: number, workersTotal: number, failures: number): Health {
  const cap2 = workersTotal * 2;
  const cap5 = workersTotal * 5;
  if (queueDepth < cap2 && failures === 0) return "green";
  if (queueDepth < cap5 || failures <= 3) return "amber";
  return "red";
}

export function aggregate(
  families: MetricFamily[],
  prev: PrevCounters,
  nowMs: number,
): { api: ApiSummary; db: DbSummary; jobs: JobsSummary; overall: OverallSummary; nextPrev: PrevCounters } {
  const dtSeconds = prev.timestampMs > 0 ? Math.max(0, (nowMs - prev.timestampMs) / 1000) : 0;
  const nextTotals = new Map<string, number>();

  // --- HTTP requests counter ---
  const httpReqsFam = findFamily(families, "galactilog_http_requests_total");
  let totalReqs = 0;
  let errorReqs = 0;
  let totalWindow = 0;
  let errorWindow = 0;
  const perEndpointCounts: Array<{ method: string; endpoint: string; status: string; count: number; key: string }> = [];
  if (httpReqsFam) {
    for (const s of httpReqsFam.samples) {
      const suffix = s.labels["__suffix__"] ?? "";
      if (suffix !== "" && suffix !== "_total") continue;
      const method = s.labels["method"] ?? "";
      const endpoint = s.labels["endpoint"] ?? "";
      const status = s.labels["status_code"] ?? "";
      const k = labelKey("galactilog_http_requests_total", { method, endpoint, status_code: status });
      nextTotals.set(k, s.value);
      totalReqs += s.value;
      const sc = parseInt(status, 10);
      if (!isNaN(sc) && sc >= 400) errorReqs += s.value;
      const prv = prev.totals.get(k);
      const delta = prv !== undefined ? Math.max(0, s.value - prv) : 0;
      totalWindow += delta;
      if (status.startsWith("4") || status.startsWith("5")) errorWindow += delta;
      perEndpointCounts.push({ method, endpoint, status, count: s.value, key: k });
    }
  }
  const prevTotalReqsSum = (() => {
    if (prev.timestampMs === 0) return 0;
    let s = 0;
    for (const [k, v] of prev.totals) if (k.startsWith("galactilog_http_requests_total{")) s += v;
    return s;
  })();
  const rps = dtSeconds > 0 ? Math.max(0, (totalReqs - prevTotalReqsSum) / dtSeconds) : 0;
  const errorRatePct = prev.timestampMs === 0
    ? 0
    : totalWindow > 0 ? fmtPct((errorWindow / totalWindow) * 100) : 0;

  // --- HTTP duration histogram: overall percentiles + per-endpoint p95 ---
  const httpDurFam = findFamily(families, "galactilog_http_request_duration_seconds");
  const httpGroups = groupHistogram(httpDurFam);
  const merged = mergeBuckets(httpGroups);
  const p50Ms = httpGroups.length ? histogramQuantile(0.5, merged.buckets) * 1000 : 0;
  const p95Ms = httpGroups.length ? histogramQuantile(0.95, merged.buckets) * 1000 : 0;
  const p99Ms = httpGroups.length ? histogramQuantile(0.99, merged.buckets) * 1000 : 0;

  // slowest endpoints: per (method, endpoint) aggregated across statuses
  const byEp = new Map<string, { method: string; endpoint: string; status: string; buckets: Array<{ le: number; count: number }>; count: number }>();
  for (const g of httpGroups) {
    const method = g.labels["method"] ?? "";
    const endpoint = g.labels["endpoint"] ?? "";
    const status = g.labels["status_code"] ?? "";
    const k = `${method}|${endpoint}|${status}`;
    byEp.set(k, { method, endpoint, status, buckets: g.buckets, count: g.count });
  }
  const slowest = Array.from(byEp.values())
    .map((e) => {
      const p95 = histogramQuantile(0.95, e.buckets) * 1000;
      const countKey = labelKey("galactilog_http_requests_total", { method: e.method, endpoint: e.endpoint, status_code: e.status });
      const cur = nextTotals.get(countKey) ?? 0;
      const prv = prev.totals.get(countKey);
      const epRps = dtSeconds > 0 && prv !== undefined ? Math.max(0, (cur - prv) / dtSeconds) : 0;
      return { endpoint: e.endpoint, method: e.method, status: e.status, p95Ms: p95, rps: epRps };
    })
    .sort((a, b) => b.p95Ms - a.p95Ms)
    .slice(0, 5);

  const errorRows = perEndpointCounts
    .filter((r) => {
      const sc = parseInt(r.status, 10);
      return !isNaN(sc) && sc >= 400;
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  const topErrors = errorRows.map((r) => ({
    endpoint: r.endpoint ? `${r.method} ${r.endpoint}` : r.method,
    status: r.status,
    count: r.count,
    sharePct: errorReqs > 0 ? (r.count / errorReqs) * 100 : 0,
  }));

  const api: ApiSummary = {
    rps,
    errorRatePct,
    p50Ms,
    p95Ms,
    p99Ms,
    slowest,
    topErrors,
    health: healthApi(errorRatePct, p95Ms),
  };

  // --- DB ---
  const dbQueryFam = findFamily(families, "galactilog_db_query_duration_seconds");
  const dbGroups = groupHistogram(dbQueryFam);
  const dbMerged = mergeBuckets(dbGroups);
  const dbP95Ms = dbGroups.length ? histogramQuantile(0.95, dbMerged.buckets) * 1000 : 0;
  const dbP99Ms = dbGroups.length ? histogramQuantile(0.99, dbMerged.buckets) * 1000 : 0;
  const dbAvgMs = dbMerged.count > 0 ? (dbMerged.sum / dbMerged.count) * 1000 : 0;
  const dbCurCount = dbMerged.count;
  const dbCountKey = "galactilog_db_query_duration_seconds_count";
  nextTotals.set(dbCountKey, dbCurCount);
  const dbQps = rateFor(dbCountKey, dbCurCount, prev, dtSeconds);

  const poolSize = gaugeValue(families, "galactilog_db_pool_size");
  const poolUsed = gaugeValue(families, "galactilog_db_pool_checked_out");
  const overflow = gaugeValue(families, "galactilog_db_pool_overflow");

  const qprFam = findFamily(families, "galactilog_db_queries_per_request");
  const qprGroups = groupHistogram(qprFam);
  const qprMerged = mergeBuckets(qprGroups);
  const qprMedian = qprGroups.length ? histogramQuantile(0.5, qprMerged.buckets) : 0;
  const qprP95 = qprGroups.length ? histogramQuantile(0.95, qprMerged.buckets) : 0;
  // "max" approximated as the top finite bucket having observations
  let qprMax = 0;
  for (const b of qprMerged.buckets) {
    if (b.count > 0 && isFinite(b.le)) qprMax = Math.max(qprMax, b.le);
  }

  const db: DbSummary = {
    qps: dbQps,
    avgMs: dbAvgMs,
    p95Ms: dbP95Ms,
    p99Ms: dbP99Ms,
    poolUsed,
    poolSize,
    overflow,
    qprMedian,
    qprP95,
    qprMax,
    health: healthDb(poolUsed, poolSize, overflow),
  };

  // --- Jobs ---
  const queueDepth = gaugeValue(families, "galactilog_celery_queue_depth");
  const workersActive = gaugeValue(families, "galactilog_celery_workers_active");
  const workersTotal = gaugeValue(families, "galactilog_celery_workers_total");

  const taskDurFam = findFamily(families, "galactilog_celery_task_duration_seconds");
  const taskGroups = groupHistogram(taskDurFam);
  const slowestTasks = taskGroups
    .map((g) => ({
      taskName: g.labels["task_name"] ?? "",
      p95Seconds: histogramQuantile(0.95, g.buckets),
      runs: g.count,
    }))
    .sort((a, b) => b.p95Seconds - a.p95Seconds)
    .slice(0, 5);

  const failFam = findFamily(families, "galactilog_celery_task_failures_total");
  const failRows: Array<{ taskName: string; count: number }> = [];
  let failuresWindowTotal = 0;
  if (failFam) {
    for (const s of failFam.samples) {
      const suffix = s.labels["__suffix__"] ?? "";
      if (suffix !== "" && suffix !== "_total") continue;
      const taskName = s.labels["task_name"] ?? "";
      const k = labelKey("galactilog_celery_task_failures_total", { task_name: taskName });
      nextTotals.set(k, s.value);
      const prv = prev.totals.get(k);
      const delta = prv !== undefined ? Math.max(0, s.value - prv) : 0;
      if (delta > 0) failuresWindowTotal += delta;
      failRows.push({ taskName, count: prv !== undefined ? delta : s.value });
    }
  }
  failRows.sort((a, b) => b.count - a.count);

  const jobs: JobsSummary = {
    queueDepth,
    workersActive,
    workersTotal,
    failuresWindow: prev.timestampMs > 0 ? failuresWindowTotal : 0,
    slowest: slowestTasks,
    failures: failRows.filter((r) => r.count > 0).slice(0, 10),
    health: healthJobs(queueDepth, workersTotal, prev.timestampMs > 0 ? failuresWindowTotal : 0),
  };

  // --- Overall ---
  const startTs = gaugeValue(families, "process_start_time_seconds");
  const uptimeSeconds = startTs > 0 ? Math.max(0, nowMs / 1000 - startTs) : 0;
  const memoryBytes = gaugeValue(families, "process_resident_memory_bytes");
  const openFds = gaugeValue(families, "process_open_fds");

  let pythonVersion = "";
  const pyInfo = findFamily(families, "python_info");
  if (pyInfo && pyInfo.samples.length) {
    pythonVersion = pyInfo.samples[0].labels["version"] ?? "";
  }

  const gcFam = findFamily(families, "python_gc_collections_total");
  let gc: { gen0: number; gen1: number; gen2: number } | null = null;
  if (gcFam) {
    const g = { gen0: 0, gen1: 0, gen2: 0 };
    for (const s of gcFam.samples) {
      const suffix = s.labels["__suffix__"] ?? "";
      if (suffix !== "" && suffix !== "_total") continue;
      const gen = s.labels["generation"];
      if (gen === "0") g.gen0 = s.value;
      else if (gen === "1") g.gen1 = s.value;
      else if (gen === "2") g.gen2 = s.value;
    }
    gc = g;
  }

  const overall: OverallSummary = {
    uptimeSeconds,
    memoryBytes,
    openFds,
    pythonVersion,
    startedAt: startTs > 0 ? new Date(startTs * 1000) : null,
    gc,
    health: "green",
  };

  return {
    api,
    db,
    jobs,
    overall,
    nextPrev: { timestampMs: nowMs, totals: nextTotals },
  };
}

function gaugeValue(families: MetricFamily[], name: string): number {
  const fam = findFamily(families, name);
  if (!fam || fam.samples.length === 0) return 0;
  // For labeled gauges, return the first; callers should use findFamily directly when needed
  return fam.samples[0].value;
}
