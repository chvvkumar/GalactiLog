import { describe, it, expect, beforeEach } from "vitest";
import { loadWbppQualityState, saveWbppQualityState, type WbppQualityState } from "./wbppQualityStore";

const DEFAULT: WbppQualityState = {
  enabled: false,
  config: { baseline: "session", constraints: [] },
};

const KEY = (rig: string) => `galactilog.wbppQuality.v1.${rig}`;

beforeEach(() => {
  localStorage.clear();
});

describe("round trip", () => {
  it("saves and loads a state per rig", () => {
    const state: WbppQualityState = {
      enabled: true,
      config: {
        baseline: "rig",
        constraints: [
          { metric: "ecc", op: "lte", value: 0.55, enabled: true },
          { metric: "stars", op: "gte", value: 80, enabled: false },
        ],
      },
    };
    saveWbppQualityState("EdgeHD 8", state);
    expect(loadWbppQualityState("EdgeHD 8")).toEqual(state);
    // A different rig is untouched.
    expect(loadWbppQualityState("Redcat 51")).toEqual(DEFAULT);
  });

  it("round-trips scope, k, per-filter seeds, and provenance", () => {
    const state: WbppQualityState = {
      enabled: true,
      config: {
        baseline: "session",
        constraints: [
          {
            metric: "hfr",
            op: "lte",
            value: 2.67,
            enabled: true,
            scope: "session",
            k: 1.2,
            groupValues: { "T|C|Ha": 2.67, "T|C|L": 1.85 },
            seed: {
              groupKey: "T|C|Ha",
              filter: "Ha",
              date: "2026-03-15",
              n: 30,
              pooledFilters: ["SII"],
            },
          },
        ],
      },
    };
    saveWbppQualityState("rigA", state);
    expect(loadWbppQualityState("rigA")).toEqual(state);
  });

  it("drops malformed extension fields without losing the constraint", () => {
    localStorage.setItem(
      KEY("rigA"),
      JSON.stringify({
        enabled: true,
        config: {
          baseline: "session",
          constraints: [
            {
              metric: "hfr",
              op: "lte",
              value: 2.5,
              enabled: true,
              scope: "nightly", // unknown scope
              k: -1, // non-positive
              groupValues: { "T|C|Ha": "high" }, // non-numeric
              seed: { filter: "Ha" }, // missing fields
            },
          ],
        },
      }),
    );
    expect(loadWbppQualityState("rigA").config.constraints).toEqual([
      { metric: "hfr", op: "lte", value: 2.5, enabled: true },
    ]);
  });

  it("keys null and empty rig under 'default'", () => {
    const state: WbppQualityState = {
      enabled: true,
      config: { baseline: "session", constraints: [] },
    };
    saveWbppQualityState(null, state);
    expect(localStorage.getItem(KEY("default"))).not.toBeNull();
    expect(loadWbppQualityState(null)).toEqual(state);
    expect(loadWbppQualityState("")).toEqual(state);
  });
});

describe("malformed storage degrades to the default", () => {
  it("returns the default when nothing is stored", () => {
    expect(loadWbppQualityState("rigA")).toEqual(DEFAULT);
  });

  it("returns the default for unparseable JSON", () => {
    localStorage.setItem(KEY("rigA"), "{not json");
    expect(loadWbppQualityState("rigA")).toEqual(DEFAULT);
  });

  it("returns the default for a non-object or wrong top-level shape", () => {
    localStorage.setItem(KEY("rigA"), JSON.stringify("hello"));
    expect(loadWbppQualityState("rigA")).toEqual(DEFAULT);
    localStorage.setItem(KEY("rigA"), JSON.stringify({ enabled: "yes", config: {} }));
    expect(loadWbppQualityState("rigA")).toEqual(DEFAULT);
    localStorage.setItem(KEY("rigA"), JSON.stringify({ enabled: true }));
    expect(loadWbppQualityState("rigA")).toEqual(DEFAULT);
  });

  it("coerces an unknown baseline to 'session'", () => {
    localStorage.setItem(
      KEY("rigA"),
      JSON.stringify({ enabled: true, config: { baseline: "galactic", constraints: [] } }),
    );
    expect(loadWbppQualityState("rigA")).toEqual({
      enabled: true,
      config: { baseline: "session", constraints: [] },
    });
  });

  it("drops constraints with unknown metric keys, keeping the valid ones", () => {
    localStorage.setItem(
      KEY("rigA"),
      JSON.stringify({
        enabled: true,
        config: {
          baseline: "session",
          constraints: [
            { metric: "adu", op: "lte", value: 1000, enabled: true }, // gone from the domain
            { metric: "ecc", op: "lte", value: 0.55, enabled: true },
          ],
        },
      }),
    );
    expect(loadWbppQualityState("rigA").config.constraints).toEqual([
      { metric: "ecc", op: "lte", value: 0.55, enabled: true },
    ]);
  });

  it("drops constraints with bad op, non-finite value, or non-boolean enabled", () => {
    localStorage.setItem(
      KEY("rigA"),
      JSON.stringify({
        enabled: false,
        config: {
          baseline: "rig",
          constraints: [
            { metric: "hfr", op: "eq", value: 2, enabled: true },
            { metric: "hfr", op: "lte", value: "2", enabled: true },
            { metric: "hfr", op: "lte", value: null, enabled: true },
            { metric: "hfr", op: "lte", value: 2, enabled: 1 },
            "garbage",
            { metric: "hfr", op: "lte", value: 2.5, enabled: false },
          ],
        },
      }),
    );
    expect(loadWbppQualityState("rigA")).toEqual({
      enabled: false,
      config: {
        baseline: "rig",
        constraints: [{ metric: "hfr", op: "lte", value: 2.5, enabled: false }],
      },
    });
  });

  it("treats a non-array constraints field as empty", () => {
    localStorage.setItem(
      KEY("rigA"),
      JSON.stringify({ enabled: true, config: { baseline: "session", constraints: { 0: {} } } }),
    );
    expect(loadWbppQualityState("rigA").config.constraints).toEqual([]);
  });
});
