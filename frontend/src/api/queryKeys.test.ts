import { describe, it, expect } from "vitest";
import { queryKeys } from "./queryKeys";
import type { ActiveFilters } from "./types";

const emptyFilters: ActiveFilters = {
  searchQuery: "",
  selectedTargetId: null,
  camera: null,
  telescope: null,
  opticalFilters: [],
  objectTypes: [],
  dateRange: { start: null, end: null },
  fitsQueries: [],
  qualityFilters: {},
  metricFilters: {},
  customColumnFilters: [],
  catalog: null,
};

describe("queryKeys", () => {
  it("returns stable (deep-equal) keys across calls with the same arguments", () => {
    expect(queryKeys.targets(emptyFilters, 1, 25, "name", "asc", false)).toEqual(
      queryKeys.targets(emptyFilters, 1, 25, "name", "asc", false)
    );
    expect(queryKeys.targetDetail("m31")).toEqual(queryKeys.targetDetail("m31"));
    expect(queryKeys.mosaicDetail("mosaic-1")).toEqual(queryKeys.mosaicDetail("mosaic-1"));
  });

  it("varies the key when a distinguishing argument changes", () => {
    const page1 = queryKeys.targets(emptyFilters, 1, 25, "name", "asc", false);
    const page2 = queryKeys.targets(emptyFilters, 2, 25, "name", "asc", false);
    expect(page1).not.toEqual(page2);

    expect(queryKeys.targetDetail("m31")).not.toEqual(queryKeys.targetDetail("m42"));
    expect(queryKeys.discovered("cameras")).not.toEqual(queryKeys.discovered("telescopes"));
  });

  it("every factory's key starts with a resource-name string (prefix-invalidation convention)", () => {
    const samples: unknown[][] = [
      [...queryKeys.me()],
      [...queryKeys.bootstrap()],
      [...queryKeys.targets(emptyFilters)],
      [...queryKeys.targetDetail("m31")],
      [...queryKeys.stats()],
      [...queryKeys.scanStatus()],
      [...queryKeys.settings()],
      [...queryKeys.customColumns()],
      [...queryKeys.users()],
      [...queryKeys.mosaics()],
      [...queryKeys.mosaicDetail("id")],
      [...queryKeys.analysisFilters()],
    ];
    for (const key of samples) {
      expect(typeof key[0]).toBe("string");
    }
  });

  it("produces collision-free keys across distinct resources sharing a first segment", () => {
    const targetsList = queryKeys.targets(emptyFilters);
    const targetDetail = queryKeys.targetDetail("m31");
    const targetSearch = queryKeys.targetSearch("m31");
    const mergeHistory = queryKeys.targetMergeHistory("m31");

    const keys = [targetsList, targetDetail, targetSearch, mergeHistory].map((k) => JSON.stringify(k));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("scan and settings families use distinct, non-colliding second segments", () => {
    const keys = [
      queryKeys.scanStatus(),
      queryKeys.scanSummary(),
      queryKeys.rebuildStatus(),
      queryKeys.dbSummary(),
      queryKeys.settings(),
      queryKeys.filterSuggestions(),
      queryKeys.equipmentSuggestions(),
      queryKeys.activitySettings(),
    ].map((k) => JSON.stringify(k));
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("phd2 keys are prefix-scoped and vary by every distinguishing argument", () => {
    expect(queryKeys.phd2Profiles()[0]).toBe("phd2");
    expect(queryKeys.phd2Sessions("2026-07-14", "140APO")).toEqual(
      queryKeys.phd2Sessions("2026-07-14", "140APO")
    );
    expect(queryKeys.phd2Sessions("2026-07-14", "140APO")).not.toEqual(
      queryKeys.phd2Sessions("2026-07-14", "OAG")
    );
    expect(queryKeys.phd2Sessions("2026-07-14", null)).not.toEqual(
      queryKeys.phd2Sessions("2026-07-15", null)
    );
    expect(queryKeys.phd2Frames("a")).not.toEqual(queryKeys.phd2Frames("b"));
  });

  it("phd2 session-list and frames keys cannot collide", () => {
    const keys = [
      queryKeys.phd2Profiles(),
      queryKeys.phd2Sessions("2026-07-14", null),
      queryKeys.phd2Sessions("2026-07-14", "frames"),
      queryKeys.phd2Frames("2026-07-14"),
    ].map((k) => JSON.stringify(k));
    expect(new Set(keys).size).toBe(keys.length);
  });
});
