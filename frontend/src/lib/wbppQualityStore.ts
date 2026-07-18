// Per-rig localStorage persistence for the WBPP export quality filter.
//
// The filter's enablement and constraint set are rig-shaped preferences (an
// eccentricity floor is a property of a mount, not of an account), so they live
// in the browser keyed by rig rather than in server settings. Storage is
// best-effort: a missing, malformed, or foreign value degrades to the default
// (filter off, no constraints) instead of throwing into the modal.

import {
  METRIC_DEFS,
  type ConstraintSeed,
  type MetricKey,
  type QualityConfig,
  type RawConstraint,
  type BaselineMode,
} from "./wbppQualityFilter";

export interface WbppQualityState {
  enabled: boolean;
  config: QualityConfig;
}

const KEY_PREFIX = "galactilog.wbppQuality.v1.";

function storageKey(rig: string | null): string {
  const suffix = rig && rig.trim() !== "" ? rig : "default";
  return `${KEY_PREFIX}${suffix}`;
}

function defaultState(): WbppQualityState {
  return { enabled: false, config: { baseline: "session", constraints: [] } };
}

function isMetricKey(v: unknown): v is MetricKey {
  return typeof v === "string" && v in METRIC_DEFS;
}

/**
 * Validate one stored constraint. Unknown metric keys are dropped rather than
 * failing the whole state: a future version that adds a metric must not wipe
 * the user's other constraints when they roll back. Anything else malformed
 * (bad op, non-finite value, non-boolean enabled) drops the constraint too.
 */
function parseConstraint(raw: unknown): RawConstraint | null {
  if (typeof raw !== "object" || raw === null) return null;
  const c = raw as Record<string, unknown>;
  if (!isMetricKey(c.metric)) return null;
  if (c.op !== "lte" && c.op !== "gte") return null;
  if (typeof c.value !== "number" || !Number.isFinite(c.value)) return null;
  if (typeof c.enabled !== "boolean") return null;
  const out: RawConstraint = { metric: c.metric, op: c.op, value: c.value, enabled: c.enabled };
  // The seeding/scope extensions are best-effort: a malformed piece is dropped
  // on its own (the constraint degrades to a plain absolute gate) rather than
  // discarding the whole constraint.
  if (c.scope === "global" || c.scope === "session") out.scope = c.scope;
  if (typeof c.k === "number" && Number.isFinite(c.k) && c.k > 0) out.k = c.k;
  const gv = parseGroupValues(c.groupValues);
  if (gv) out.groupValues = gv;
  const seed = parseSeed(c.seed);
  if (seed) out.seed = seed;
  return out;
}

function parseGroupValues(raw: unknown): Record<string, number> | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const out: Record<string, number> = {};
  let any = false;
  for (const [key, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    out[key] = v;
    any = true;
  }
  return any ? out : null;
}

function parseSeed(raw: unknown): ConstraintSeed | null {
  if (typeof raw !== "object" || raw === null) return null;
  const s = raw as Record<string, unknown>;
  if (typeof s.groupKey !== "string" || typeof s.filter !== "string") return null;
  if (s.date !== null && typeof s.date !== "string") return null;
  if (typeof s.n !== "number" || !Number.isFinite(s.n)) return null;
  if (!Array.isArray(s.pooledFilters)) return null;
  return {
    groupKey: s.groupKey,
    filter: s.filter,
    date: s.date,
    n: s.n,
    pooledFilters: s.pooledFilters.filter((f): f is string => typeof f === "string"),
  };
}

export function loadWbppQualityState(rig: string | null): WbppQualityState {
  if (typeof localStorage === "undefined") return defaultState();
  let raw: string | null;
  try {
    raw = localStorage.getItem(storageKey(rig));
  } catch {
    return defaultState();
  }
  if (!raw) return defaultState();

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return defaultState();
  }
  if (typeof parsed !== "object" || parsed === null) return defaultState();
  const p = parsed as Record<string, unknown>;
  if (typeof p.enabled !== "boolean") return defaultState();
  if (typeof p.config !== "object" || p.config === null) return defaultState();
  const cfg = p.config as Record<string, unknown>;

  const baseline: BaselineMode =
    cfg.baseline === "session" || cfg.baseline === "rig" ? cfg.baseline : "session";
  const constraints: RawConstraint[] = Array.isArray(cfg.constraints)
    ? cfg.constraints
        .map(parseConstraint)
        .filter((c): c is RawConstraint => c !== null)
    : [];

  return { enabled: p.enabled, config: { baseline, constraints } };
}

export function saveWbppQualityState(rig: string | null, state: WbppQualityState): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(storageKey(rig), JSON.stringify(state));
  } catch {
    // Quota exceeded or storage disabled: the filter still works for this
    // session; it just will not persist. Nothing useful to surface here.
  }
}
