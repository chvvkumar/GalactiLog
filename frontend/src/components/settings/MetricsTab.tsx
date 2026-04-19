import { Component, createEffect, createMemo, createResource, createSignal, For, onCleanup, Show } from "solid-js";
import { parsePrometheusText, type MetricFamily } from "../../utils/prometheusParse";
import { aggregate, emptyPrev, type Health, type PrevCounters } from "../../utils/metricsAggregate";

type RefreshOption = "off" | "5" | "15" | "30" | "60";

interface Snapshot {
  families: MetricFamily[];
  fetchedAt: Date;
}

const ChevronIcon: Component<{ size?: number }> = (props) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={props.size ?? 12} height={props.size ?? 12} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="9 18 15 12 9 6" />
  </svg>
);

const CopyIcon: Component = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);

function formatNumber(n: number, digits = 1): string {
  if (!isFinite(n)) return "0";
  if (Math.abs(n) >= 1000) return Math.round(n).toLocaleString();
  return n.toFixed(digits);
}

function formatInt(n: number): string {
  if (!isFinite(n)) return "0";
  return Math.round(n).toLocaleString();
}

function formatMs(ms: number): string {
  if (!isFinite(ms) || ms <= 0) return "0 ms";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatSeconds(s: number): string {
  if (!isFinite(s) || s <= 0) return "0 s";
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 60) return `${s.toFixed(1)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function formatBytes(b: number): string {
  if (!isFinite(b) || b <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

function formatUptime(s: number): string {
  if (!isFinite(s) || s <= 0) return "0m";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatDateTime(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function statusColorClass(status: string): string {
  const sc = parseInt(status, 10);
  if (isNaN(sc)) return "text-theme-text-secondary";
  if (sc >= 500) return "text-red-400";
  if (sc >= 400) return "text-amber-400";
  if (sc >= 300) return "text-blue-400";
  return "text-green-400";
}

const StatusPill: Component<{ health: Health }> = (props) => {
  const label = () => props.health === "green" ? "Healthy" : props.health === "amber" ? "Degraded" : "Unhealthy";
  const classes = () => {
    if (props.health === "green") return "bg-green-900/40 text-green-300";
    if (props.health === "amber") return "bg-amber-900/40 text-amber-300";
    return "bg-red-900/40 text-red-300";
  };
  const dotClass = () => {
    if (props.health === "green") return "bg-green-500";
    if (props.health === "amber") return "bg-amber-500";
    return "bg-red-500";
  };
  return (
    <span class={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${classes()}`}>
      <span class={`w-1.5 h-1.5 rounded-full ${dotClass()}`} />
      {label()}
    </span>
  );
};

const Card: Component<{ children: any; class?: string }> = (props) => (
  <div class={`rounded-[var(--radius-md)] bg-theme-surface border border-theme-border ${props.class ?? ""}`}>
    {props.children}
  </div>
);

const Kpi: Component<{ value: string; label: string }> = (props) => (
  <div>
    <div class="text-2xl tabular-nums text-theme-text-primary">{props.value}</div>
    <div class="text-xs text-theme-text-secondary mt-1">{props.label}</div>
  </div>
);

const DetailsToggle: Component<{ summary: any; children: any }> = (props) => (
  <details class="group">
    <summary class="flex items-center gap-2 text-xs text-theme-text-secondary hover:text-theme-text-primary cursor-pointer list-none [&::-webkit-details-marker]:hidden">
      <span class="transition-transform duration-150 group-open:rotate-90"><ChevronIcon /></span>
      {props.summary}
    </summary>
    <div class="mt-4 space-y-4">{props.children}</div>
  </details>
);

export const MetricsTab: Component = () => {
  const [refreshOpt, setRefreshOpt] = createSignal<RefreshOption>("15");
  const [tick, setTick] = createSignal(0);
  const [lastSnapshot, setLastSnapshot] = createSignal<Snapshot | null>(null);
  const [fetchError, setFetchError] = createSignal<string | null>(null);

  let prevCounters: PrevCounters = emptyPrev();

  createEffect(() => {
    const opt = refreshOpt();
    let handle: ReturnType<typeof setInterval> | null = null;
    if (opt !== "off") {
      const seconds = parseInt(opt, 10);
      handle = setInterval(() => setTick((t) => t + 1), seconds * 1000);
    }
    onCleanup(() => {
      if (handle !== null) clearInterval(handle);
    });
  });

  const [data] = createResource(tick, async () => {
    try {
      const res = await fetch("/api/metrics", { credentials: "include" });
      if (!res.ok) {
        setFetchError(`HTTP ${res.status}`);
        return lastSnapshot();
      }
      const text = await res.text();
      const families = parsePrometheusText(text);
      if (families.length === 0) {
        setFetchError("No metric families returned");
        return lastSnapshot();
      }
      const snap: Snapshot = { families, fetchedAt: new Date() };
      setLastSnapshot(snap);
      setFetchError(null);
      return snap;
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : String(e));
      return lastSnapshot();
    }
  });

  const aggregated = createMemo(() => {
    const snap = lastSnapshot();
    if (!snap) return null;
    return aggregate(snap.families, prevCounters, snap.fetchedAt.getTime());
  });

  createEffect(() => {
    const a = aggregated();
    if (a) prevCounters = a.nextPrev;
  });

  const onIntervalChange = (e: Event) => {
    const val = (e.currentTarget as HTMLSelectElement).value as RefreshOption;
    setRefreshOpt(val);
  };

  const copyScrapeUrl = async () => {
    try { await navigator.clipboard.writeText(`${window.location.origin}/api/metrics`); } catch { /* ignore */ }
  };

  return (
    <div class="space-y-6">
      {/* Header */}
      <Card class="p-5">
        <div class="flex flex-wrap items-center gap-3">
          <div class="flex items-center gap-2">
            <label for="metrics-refresh" class="text-xs text-theme-text-secondary">Refresh</label>
            <select
              id="metrics-refresh"
              value={refreshOpt()}
              onChange={onIntervalChange}
              class="bg-theme-surface border border-theme-border text-theme-text-primary rounded-[var(--radius-sm)] px-2.5 py-1.5 text-sm"
            >
              <option value="off">Off</option>
              <option value="5">5s</option>
              <option value="15">15s</option>
              <option value="30">30s</option>
              <option value="60">60s</option>
            </select>
          </div>
          <button
            onClick={() => setTick((t) => t + 1)}
            class="px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] bg-blue-500/15 text-blue-400 border border-blue-500/30 hover:bg-blue-500/25"
          >
            Refresh now
          </button>
          <span class="text-xs text-theme-text-secondary">
            Last updated:{" "}
            <span class="tabular-nums text-theme-text-primary">
              {lastSnapshot() ? lastSnapshot()!.fetchedAt.toLocaleTimeString() : "--:--:--"}
            </span>
          </span>

          <div class="flex-1" />

          <div class="flex items-center gap-2">
            <span class="text-xs text-theme-text-secondary">Scrape URL</span>
            <span class="inline-flex items-center gap-2 font-mono text-xs px-2.5 py-1 rounded-[var(--radius-sm)] bg-theme-surface border border-theme-border text-theme-text-primary">
              /api/metrics
              <button onClick={copyScrapeUrl} class="text-theme-text-secondary hover:text-theme-text-primary" title="Copy URL" aria-label="Copy URL">
                <CopyIcon />
              </button>
            </span>
          </div>
        </div>
      </Card>

      <Show when={fetchError()}>
        <Card class="p-4">
          <div class="text-sm text-red-400">Failed to load metrics: {fetchError()}</div>
        </Card>
      </Show>

      <Show when={aggregated()} fallback={
        <Show when={!lastSnapshot() && data.loading}>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <For each={[1, 2, 3, 4]}>{() => (
              <Card class="p-6">
                <div class="h-5 w-24 bg-theme-elevated rounded animate-pulse mb-4" />
                <div class="h-8 w-32 bg-theme-elevated rounded animate-pulse" />
              </Card>
            )}</For>
          </div>
        </Show>
      }>
        {(agg) => (
          <>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ApiCard summary={agg().api} />
              <DbCard summary={agg().db} />
              <JobsCard summary={agg().jobs} />
              <OverallCard summary={agg().overall} />
            </div>
            <RawMetrics families={lastSnapshot()!.families} prevTotals={prevCounters} />
          </>
        )}
      </Show>
    </div>
  );
};

const ApiCard: Component<{ summary: import("../../utils/metricsAggregate").ApiSummary }> = (props) => (
  <Card class="p-6 space-y-5">
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-sm font-semibold text-theme-text-primary">API</h2>
      <StatusPill health={props.summary.health} />
    </div>
    <div class="grid grid-cols-3 gap-4">
      <Kpi value={formatNumber(props.summary.rps)} label="requests/sec" />
      <Kpi value={`${props.summary.errorRatePct.toFixed(1)}%`} label="error rate" />
      <Kpi value={formatMs(props.summary.p95Ms)} label="p95 latency" />
    </div>
    <DetailsToggle summary="Details">
      <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-xs text-theme-text-secondary">
              <th class="text-left font-medium px-4 py-2 border-b border-theme-border">percentile</th>
              <th class="text-right font-medium px-4 py-2 border-b border-theme-border">latency</th>
            </tr>
          </thead>
          <tbody>
            <PctRow label="p50" value={formatMs(props.summary.p50Ms)} />
            <PctRow label="p95" value={formatMs(props.summary.p95Ms)} />
            <PctRow label="p99" value={formatMs(props.summary.p99Ms)} last />
          </tbody>
        </table>
      </div>
      <Show when={props.summary.slowest.length > 0}>
        <div>
          <div class="text-xs text-theme-text-secondary mb-2">Top 5 slowest endpoints</div>
          <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-theme-text-secondary">
                  <th class="text-left font-medium px-4 py-2 border-b border-theme-border">endpoint</th>
                  <th class="text-right font-medium px-4 py-2 border-b border-theme-border">p95</th>
                  <th class="text-right font-medium px-4 py-2 border-b border-theme-border">req/s</th>
                </tr>
              </thead>
              <tbody>
                <For each={props.summary.slowest}>{(row, i) => (
                  <tr class={i() < props.summary.slowest.length - 1 ? "border-b border-theme-border" : ""}>
                    <td class="font-mono text-xs px-4 py-2">{row.method} {row.endpoint}</td>
                    <td class="text-right tabular-nums px-4 py-2">{formatMs(row.p95Ms)}</td>
                    <td class="text-right tabular-nums text-theme-text-secondary px-4 py-2">{formatNumber(row.rps)}</td>
                  </tr>
                )}</For>
              </tbody>
            </table>
          </div>
        </div>
      </Show>
      <Show when={props.summary.topErrors.length > 0}>
        <div>
          <div class="text-xs text-theme-text-secondary mb-2">Top 5 endpoints by errors</div>
          <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-theme-text-secondary">
                  <th class="text-left font-medium px-4 py-2 border-b border-theme-border">endpoint</th>
                  <th class="text-left font-medium px-4 py-2 border-b border-theme-border">status</th>
                  <th class="text-right font-medium px-4 py-2 border-b border-theme-border">count</th>
                  <th class="text-right font-medium px-4 py-2 border-b border-theme-border">share</th>
                </tr>
              </thead>
              <tbody>
                <For each={props.summary.topErrors}>{(row, i) => (
                  <tr class={i() < props.summary.topErrors.length - 1 ? "border-b border-theme-border" : ""}>
                    <td class="font-mono text-xs px-4 py-2">{row.endpoint}</td>
                    <td class={`font-mono text-xs px-4 py-2 ${statusColorClass(row.status)}`}>{row.status}</td>
                    <td class="text-right tabular-nums px-4 py-2">{formatInt(row.count)}</td>
                    <td class="text-right tabular-nums text-theme-text-secondary px-4 py-2">{row.sharePct.toFixed(1)}%</td>
                  </tr>
                )}</For>
              </tbody>
            </table>
          </div>
        </div>
      </Show>
    </DetailsToggle>
  </Card>
);

const PctRow: Component<{ label: string; value: string; last?: boolean }> = (props) => (
  <tr class={props.last ? "" : "border-b border-theme-border"}>
    <td class="font-mono text-xs px-4 py-2">{props.label}</td>
    <td class="text-right tabular-nums px-4 py-2">{props.value}</td>
  </tr>
);

const DbCard: Component<{ summary: import("../../utils/metricsAggregate").DbSummary }> = (props) => {
  const utilPct = () => props.summary.poolSize > 0 ? (props.summary.poolUsed / props.summary.poolSize) * 100 : 0;
  return (
    <Card class="p-6 space-y-5">
      <div class="flex items-center justify-between gap-3">
        <h2 class="text-sm font-semibold text-theme-text-primary">Database</h2>
        <StatusPill health={props.summary.health} />
      </div>
      <div class="grid grid-cols-3 gap-4">
        <Kpi value={formatNumber(props.summary.qps)} label="queries/sec" />
        <Kpi value={formatMs(props.summary.p95Ms)} label="p95 query" />
        <Kpi value={`${formatInt(props.summary.poolUsed)} / ${formatInt(props.summary.poolSize)}`} label="pool" />
      </div>
      <DetailsToggle summary="Details">
        <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-theme-text-secondary">
                <th class="text-left font-medium px-4 py-2 border-b border-theme-border">metric</th>
                <th class="text-right font-medium px-4 py-2 border-b border-theme-border">value</th>
              </tr>
            </thead>
            <tbody>
              <PctRow label="avg query time" value={formatMs(props.summary.avgMs)} />
              <PctRow label="p95" value={formatMs(props.summary.p95Ms)} />
              <PctRow label="p99" value={formatMs(props.summary.p99Ms)} last />
            </tbody>
          </table>
        </div>
        <div>
          <div class="flex items-center justify-between text-xs text-theme-text-secondary mb-2">
            <span>Pool utilization</span>
            <span class="tabular-nums text-theme-text-primary">{utilPct().toFixed(0)}%</span>
          </div>
          <div class="h-2.5 rounded bg-theme-elevated overflow-hidden">
            <div
              class={`h-full rounded ${utilPct() >= 90 ? "bg-red-500/60" : utilPct() >= 70 ? "bg-amber-500/60" : "bg-blue-500/60"}`}
              style={{ width: `${Math.min(100, utilPct())}%` }}
            />
          </div>
          <div class="text-xs text-theme-text-secondary mt-2 tabular-nums">
            {formatInt(props.summary.poolUsed)} / {formatInt(props.summary.poolSize)} connections in use, {formatInt(props.summary.overflow)} overflow
          </div>
        </div>
        <div>
          <div class="text-xs text-theme-text-secondary mb-2">Queries per request</div>
          <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-xs text-theme-text-secondary">
                  <th class="text-left font-medium px-4 py-2 border-b border-theme-border">statistic</th>
                  <th class="text-right font-medium px-4 py-2 border-b border-theme-border">queries</th>
                </tr>
              </thead>
              <tbody>
                <PctRow label="median" value={formatNumber(props.summary.qprMedian, 0)} />
                <PctRow label="p95" value={formatNumber(props.summary.qprP95, 0)} />
                <PctRow label="max" value={formatNumber(props.summary.qprMax, 0)} last />
              </tbody>
            </table>
          </div>
        </div>
      </DetailsToggle>
    </Card>
  );
};

const JobsCard: Component<{ summary: import("../../utils/metricsAggregate").JobsSummary }> = (props) => {
  const utilPct = () => props.summary.workersTotal > 0 ? (props.summary.workersActive / props.summary.workersTotal) * 100 : 0;
  return (
    <Card class="p-6 space-y-5">
      <div class="flex items-center justify-between gap-3">
        <h2 class="text-sm font-semibold text-theme-text-primary">Background Jobs</h2>
        <StatusPill health={props.summary.health} />
      </div>
      <div class="grid grid-cols-3 gap-4">
        <Kpi value={formatInt(props.summary.queueDepth)} label="queue depth" />
        <Kpi value={`${formatInt(props.summary.workersActive)} / ${formatInt(props.summary.workersTotal)}`} label="workers" />
        <Kpi value={formatInt(props.summary.failuresWindow)} label="failures (since last refresh)" />
      </div>
      <DetailsToggle summary="Details">
        <div>
          <div class="flex items-center justify-between text-xs text-theme-text-secondary mb-2">
            <span>Worker utilization</span>
            <span class="tabular-nums text-theme-text-primary">{utilPct().toFixed(0)}%</span>
          </div>
          <div class="h-2.5 rounded bg-theme-elevated overflow-hidden">
            <div
              class={`h-full rounded ${utilPct() >= 90 ? "bg-red-500/60" : utilPct() >= 70 ? "bg-amber-500/60" : "bg-blue-500/60"}`}
              style={{ width: `${Math.min(100, utilPct())}%` }}
            />
          </div>
          <div class="text-xs text-theme-text-secondary mt-2 tabular-nums">
            {formatInt(props.summary.workersActive)} / {formatInt(props.summary.workersTotal)} busy
          </div>
        </div>
        <Show when={props.summary.slowest.length > 0}>
          <div>
            <div class="text-xs text-theme-text-secondary mb-2">Slowest tasks (p95)</div>
            <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-xs text-theme-text-secondary">
                    <th class="text-left font-medium px-4 py-2 border-b border-theme-border">task_name</th>
                    <th class="text-right font-medium px-4 py-2 border-b border-theme-border">p95</th>
                    <th class="text-right font-medium px-4 py-2 border-b border-theme-border">runs</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={props.summary.slowest}>{(row, i) => (
                    <tr class={i() < props.summary.slowest.length - 1 ? "border-b border-theme-border" : ""}>
                      <td class="font-mono text-xs px-4 py-2">{row.taskName}</td>
                      <td class="text-right tabular-nums px-4 py-2">{formatSeconds(row.p95Seconds)}</td>
                      <td class="text-right tabular-nums text-theme-text-secondary px-4 py-2">{formatInt(row.runs)}</td>
                    </tr>
                  )}</For>
                </tbody>
              </table>
            </div>
          </div>
        </Show>
        <Show when={props.summary.failures.length > 0}>
          <div>
            <div class="text-xs text-theme-text-secondary mb-2">Recent failures</div>
            <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-xs text-theme-text-secondary">
                    <th class="text-left font-medium px-4 py-2 border-b border-theme-border">task_name</th>
                    <th class="text-right font-medium px-4 py-2 border-b border-theme-border">count</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={props.summary.failures}>{(row, i) => (
                    <tr class={i() < props.summary.failures.length - 1 ? "border-b border-theme-border" : ""}>
                      <td class="font-mono text-xs px-4 py-2">{row.taskName}</td>
                      <td class="text-right tabular-nums px-4 py-2">{formatInt(row.count)}</td>
                    </tr>
                  )}</For>
                </tbody>
              </table>
            </div>
          </div>
        </Show>
      </DetailsToggle>
    </Card>
  );
};

const OverallCard: Component<{ summary: import("../../utils/metricsAggregate").OverallSummary }> = (props) => (
  <Card class="p-6 space-y-5">
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-sm font-semibold text-theme-text-primary">Overall</h2>
      <StatusPill health={props.summary.health} />
    </div>
    <div class="grid grid-cols-3 gap-4">
      <Kpi value={formatUptime(props.summary.uptimeSeconds)} label="uptime" />
      <Kpi value={formatBytes(props.summary.memoryBytes)} label="memory" />
      <Kpi value={formatInt(props.summary.openFds)} label="open FDs" />
    </div>
    <DetailsToggle summary="Details">
      <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
        <table class="w-full text-sm">
          <tbody>
            <tr class="border-b border-theme-border">
              <td class="text-theme-text-secondary px-4 py-2">Python version</td>
              <td class="text-right tabular-nums font-mono text-xs px-4 py-2">{props.summary.pythonVersion || "n/a"}</td>
            </tr>
            <tr>
              <td class="text-theme-text-secondary px-4 py-2">Process start time</td>
              <td class="text-right tabular-nums font-mono text-xs px-4 py-2">{props.summary.startedAt ? formatDateTime(props.summary.startedAt) : "n/a"}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <Show when={props.summary.gc}>
        {(gc) => (
          <div>
            <div class="text-xs text-theme-text-secondary mb-2">GC collections</div>
            <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
              <table class="w-full text-sm">
                <thead>
                  <tr class="text-xs text-theme-text-secondary">
                    <th class="text-left font-medium px-4 py-2 border-b border-theme-border">generation</th>
                    <th class="text-right font-medium px-4 py-2 border-b border-theme-border">collections</th>
                  </tr>
                </thead>
                <tbody>
                  <PctRow label="gen0" value={formatInt(gc().gen0)} />
                  <PctRow label="gen1" value={formatInt(gc().gen1)} />
                  <PctRow label="gen2" value={formatInt(gc().gen2)} last />
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Show>
    </DetailsToggle>
  </Card>
);

const RawMetrics: Component<{ families: MetricFamily[]; prevTotals: PrevCounters }> = (props) => {
  const groups = createMemo(() => {
    const http: MetricFamily[] = [];
    const db: MetricFamily[] = [];
    const celery: MetricFamily[] = [];
    const other: MetricFamily[] = [];
    for (const f of props.families) {
      if (f.name.startsWith("galactilog_http_")) http.push(f);
      else if (f.name.startsWith("galactilog_db_")) db.push(f);
      else if (f.name.startsWith("galactilog_celery_")) celery.push(f);
      else other.push(f);
    }
    return [
      { key: "HTTP", prefix: "galactilog_http_*", items: http, open: true },
      { key: "Database", prefix: "galactilog_db_*", items: db, open: true },
      { key: "Celery", prefix: "galactilog_celery_*", items: celery, open: false },
      { key: "Other", prefix: "*", items: other, open: false },
    ];
  });

  return (
    <details class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border group">
      <summary class="px-5 py-4 flex items-center gap-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden">
        <span class="text-theme-text-secondary transition-transform duration-150 group-open:rotate-90"><ChevronIcon size={14} /></span>
        <h2 class="text-sm font-semibold text-theme-text-primary">Show raw metrics</h2>
        <span class="text-xs text-theme-text-secondary">grouped by subsystem</span>
      </summary>
      <div class="p-5 space-y-6">
        <For each={groups()}>{(grp) => (
          <Show when={grp.items.length > 0}>
            <RawGroup title={grp.key} prefix={grp.prefix} items={grp.items} defaultOpen={grp.open} prevTotals={props.prevTotals} />
          </Show>
        )}</For>
      </div>
    </details>
  );
};

const RawGroup: Component<{ title: string; prefix: string; items: MetricFamily[]; defaultOpen: boolean; prevTotals: PrevCounters }> = (props) => (
  <details class="rounded-[var(--radius-md)] bg-theme-surface border border-theme-border group" open={props.defaultOpen}>
    <summary class="px-5 py-4 flex items-center gap-3 border-b border-theme-border cursor-pointer list-none [&::-webkit-details-marker]:hidden">
      <span class="text-theme-text-secondary transition-transform duration-150 group-open:rotate-90"><ChevronIcon size={14} /></span>
      <h2 class="text-sm font-semibold text-theme-text-primary">{props.title}</h2>
      <span class="text-xs text-theme-text-secondary font-mono">{props.prefix}</span>
      <span class="ml-auto inline-flex items-center px-2 py-0.5 rounded-full text-xs text-theme-text-secondary bg-theme-elevated border border-theme-border tabular-nums">
        {props.items.length} metric{props.items.length === 1 ? "" : "s"}
      </span>
    </summary>
    <div class="p-5 space-y-5">
      <For each={props.items}>{(fam) => <RawFamily family={fam} prevTotals={props.prevTotals} />}</For>
    </div>
  </details>
);

const RawFamily: Component<{ family: MetricFamily; prevTotals: PrevCounters }> = (props) => {
  return (
    props.family.type === "gauge" ? <GaugeView family={props.family} /> :
    props.family.type === "counter" ? <CounterView family={props.family} prevTotals={props.prevTotals} /> :
    props.family.type === "histogram" ? <HistogramView family={props.family} /> :
    <UntypedView family={props.family} />
  );
};

const GaugeView: Component<{ family: MetricFamily }> = (props) => (
  <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border p-4">
    <div class="text-xs text-theme-text-secondary font-mono">{props.family.name}</div>
    <Show when={props.family.samples.length === 1 && Object.keys(props.family.samples[0].labels).filter(k => k !== "__suffix__").length === 0}
      fallback={
        <div class="mt-3 rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-theme-text-secondary">
                <th class="text-left font-medium px-4 py-2 border-b border-theme-border">labels</th>
                <th class="text-right font-medium px-4 py-2 border-b border-theme-border">value</th>
              </tr>
            </thead>
            <tbody>
              <For each={props.family.samples}>{(s, i) => (
                <tr class={i() < props.family.samples.length - 1 ? "border-b border-theme-border" : ""}>
                  <td class="font-mono text-xs px-4 py-2">{labelPairsText(s.labels)}</td>
                  <td class="text-right tabular-nums px-4 py-2">{formatNumber(s.value)}</td>
                </tr>
              )}</For>
            </tbody>
          </table>
        </div>
      }
    >
      <div class="text-2xl font-semibold tabular-nums text-theme-text-primary mt-2">{formatNumber(props.family.samples[0].value)}</div>
    </Show>
    <Show when={props.family.help}>
      <div class="text-xs italic text-theme-text-secondary mt-1">{props.family.help}</div>
    </Show>
  </div>
);

function labelPairsText(labels: Record<string, string>): string {
  return Object.entries(labels)
    .filter(([k]) => k !== "__suffix__")
    .map(([k, v]) => `${k}="${v}"`)
    .join(", ");
}

const CounterView: Component<{ family: MetricFamily; prevTotals: PrevCounters }> = (props) => {
  const rows = createMemo(() => {
    const out: Array<{ labels: Record<string, string>; value: number; rate: number }> = [];
    let total = 0;
    for (const s of props.family.samples) {
      const suffix = s.labels["__suffix__"] ?? "";
      if (suffix !== "" && suffix !== "_total") continue;
      const labels: Record<string, string> = {};
      for (const [k, v] of Object.entries(s.labels)) if (k !== "__suffix__") labels[k] = v;
      const key = labelKey(props.family.name, labels);
      const prev = props.prevTotals.totals.get(key);
      const dt = props.prevTotals.timestampMs > 0 ? (Date.now() - props.prevTotals.timestampMs) / 1000 : 0;
      const rate = prev !== undefined && dt > 0 ? Math.max(0, (s.value - prev) / dt) : 0;
      total += s.value;
      out.push({ labels, value: s.value, rate });
    }
    out.sort((a, b) => b.value - a.value);
    return { rows: out, total };
  });

  const totalRate = createMemo(() => {
    const dt = props.prevTotals.timestampMs > 0 ? (Date.now() - props.prevTotals.timestampMs) / 1000 : 0;
    if (dt <= 0) return 0;
    let prevSum = 0;
    for (const [k, v] of props.prevTotals.totals) if (k.startsWith(props.family.name + "{")) prevSum += v;
    return Math.max(0, (rows().total - prevSum) / dt);
  });

  const labelCols = createMemo(() => {
    const set = new Set<string>();
    for (const r of rows().rows) for (const k of Object.keys(r.labels)) set.add(k);
    return Array.from(set);
  });

  return (
    <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border p-4">
      <div class="flex items-start justify-between gap-3 mb-3">
        <div>
          <div class="text-xs text-theme-text-secondary font-mono">{props.family.name}</div>
          <Show when={props.family.help}><div class="text-xs italic text-theme-text-secondary mt-0.5">{props.family.help}</div></Show>
        </div>
        <div class="text-right">
          <div class="text-2xl font-semibold tabular-nums text-theme-text-primary">{formatInt(rows().total)}</div>
          <div class="text-xs text-theme-text-secondary tabular-nums">{formatNumber(totalRate())}/s since last refresh</div>
        </div>
      </div>
      <Show when={labelCols().length > 0}>
        <div class="rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
          <table class="w-full text-sm">
            <thead>
              <tr class="text-xs text-theme-text-secondary">
                <For each={labelCols()}>{(c) => <th class="text-left font-medium px-4 py-2 border-b border-theme-border">{c}</th>}</For>
                <th class="text-right font-medium px-4 py-2 border-b border-theme-border">total</th>
                <th class="text-right font-medium px-4 py-2 border-b border-theme-border">rate/s</th>
              </tr>
            </thead>
            <tbody>
              <For each={rows().rows}>{(row, i) => (
                <tr class={i() < rows().rows.length - 1 ? "border-b border-theme-border" : ""}>
                  <For each={labelCols()}>{(c) => {
                    const v = row.labels[c] ?? "";
                    const cls = c === "status_code" ? statusColorClass(v) : "";
                    return <td class={`font-mono text-xs px-4 py-2 ${cls}`}>{v}</td>;
                  }}</For>
                  <td class="text-right tabular-nums px-4 py-2">{formatInt(row.value)}</td>
                  <td class="text-right tabular-nums text-theme-text-secondary px-4 py-2">{formatNumber(row.rate)}</td>
                </tr>
              )}</For>
            </tbody>
          </table>
        </div>
      </Show>
    </div>
  );
};

function labelKey(name: string, labels: Record<string, string>): string {
  const keys = Object.keys(labels).filter((k) => k !== "__suffix__").sort();
  return name + "{" + keys.map((k) => `${k}=${labels[k]}`).join(",") + "}";
}

const HistogramView: Component<{ family: MetricFamily }> = (props) => {
  const groups = createMemo(() => {
    type G = { labels: Record<string, string>; buckets: Array<{ le: number; count: number }>; sum: number; count: number };
    const map = new Map<string, G>();
    for (const s of props.family.samples) {
      const suffix = s.labels["__suffix__"] ?? "";
      const labels: Record<string, string> = {};
      for (const [k, v] of Object.entries(s.labels)) if (k !== "__suffix__" && k !== "le") labels[k] = v;
      const keyParts = Object.keys(labels).sort().map(k => `${k}=${labels[k]}`).join(",");
      let g = map.get(keyParts);
      if (!g) { g = { labels, buckets: [], sum: 0, count: 0 }; map.set(keyParts, g); }
      if (suffix === "_bucket") {
        const leRaw = s.labels["le"];
        const le = leRaw === "+Inf" ? Infinity : Number(leRaw);
        g.buckets.push({ le, count: s.value });
      } else if (suffix === "_sum") g.sum = s.value;
      else if (suffix === "_count") g.count = s.value;
    }
    for (const g of map.values()) g.buckets.sort((a, b) => a.le - b.le);
    return Array.from(map.values());
  });

  return (
    <div>
      <div class="text-xs text-theme-text-secondary font-mono mb-2">{props.family.name}</div>
      <Show when={props.family.help}><div class="text-xs italic text-theme-text-secondary mb-3">{props.family.help}</div></Show>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <For each={groups()}>{(g) => {
          const avgMs = g.count > 0 ? (g.sum / g.count) * 1000 : 0;
          const top = g.buckets.length ? g.buckets[g.buckets.length - 1].count : 0;
          return (
            <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border p-4">
              <div class="flex flex-wrap items-baseline justify-between gap-2 mb-3">
                <div class="flex items-center gap-2 text-xs font-mono">
                  <For each={Object.entries(g.labels)}>{([k, v]) => {
                    const cls = k === "status_code" ? statusColorClass(v) : "text-theme-text-secondary";
                    return <span class={cls}>{k}={v}</span>;
                  }}</For>
                </div>
                <div class="flex items-center gap-4 text-xs text-theme-text-secondary">
                  <span>count <span class="tabular-nums text-theme-text-primary">{formatInt(g.count)}</span></span>
                  <span>sum <span class="tabular-nums text-theme-text-primary">{formatNumber(g.sum, 2)} s</span></span>
                  <span>avg <span class="tabular-nums text-theme-text-primary">{formatMs(avgMs)}</span></span>
                </div>
              </div>
              <div class="space-y-1.5">
                <For each={g.buckets}>{(b) => {
                  const pct = top > 0 ? (b.count / top) * 100 : 0;
                  const leLabel = isFinite(b.le) ? `le=${b.le}` : "le=+Inf";
                  return (
                    <div class="grid grid-cols-[5rem_1fr_5rem] items-center gap-3 text-xs">
                      <span class="font-mono text-theme-text-secondary">{leLabel}</span>
                      <div class="h-2 rounded bg-theme-elevated overflow-hidden border border-theme-border">
                        <div class="h-full rounded bg-blue-500/55" style={{ width: `${Math.min(100, pct)}%` }} />
                      </div>
                      <span class={`tabular-nums text-right ${!isFinite(b.le) ? "font-semibold text-theme-text-primary" : "text-theme-text-primary"}`}>{formatInt(b.count)}</span>
                    </div>
                  );
                }}</For>
              </div>
            </div>
          );
        }}</For>
      </div>
    </div>
  );
};

const UntypedView: Component<{ family: MetricFamily }> = (props) => (
  <div class="rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border p-4">
    <div class="text-xs text-theme-text-secondary font-mono">{props.family.name}</div>
    <Show when={props.family.help}><div class="text-xs italic text-theme-text-secondary mt-0.5">{props.family.help}</div></Show>
    <div class="mt-3 rounded-[var(--radius-sm)] overflow-hidden border border-theme-border">
      <table class="w-full text-sm">
        <tbody>
          <For each={props.family.samples}>{(s, i) => (
            <tr class={i() < props.family.samples.length - 1 ? "border-b border-theme-border" : ""}>
              <td class="font-mono text-xs px-4 py-2">{labelPairsText(s.labels)}</td>
              <td class="text-right tabular-nums px-4 py-2">{formatNumber(s.value)}</td>
            </tr>
          )}</For>
        </tbody>
      </table>
    </div>
  </div>
);
