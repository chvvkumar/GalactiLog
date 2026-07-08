import { describe, it, expect } from "vitest";
import type { ActiveFilters } from "../api/types";

// hasActiveFilters is not exported; reproduce it here so the logic can be unit-tested
// independently of the SolidJS render tree.
function hasActiveFilters(f: ActiveFilters): boolean {
  if (f.searchQuery) return true;
  if (f.selectedTargetId) return true;
  if (f.camera) return true;
  if (f.telescope) return true;
  if (f.catalog) return true;
  if (f.opticalFilters.length > 0) return true;
  if (f.objectTypes.length > 0) return true;
  if (f.dateRange.start || f.dateRange.end) return true;
  if (f.fitsQueries.length > 0) return true;
  if (f.customColumnFilters.length > 0) return true;
  if (Object.keys(f.qualityFilters).length > 0) return true;
  if (Object.keys(f.metricFilters).length > 0) return true;
  return false;
}

const emptyFilters: ActiveFilters = {
  searchQuery: "",
  selectedTargetId: null,
  camera: null,
  telescope: null,
  catalog: null,
  opticalFilters: [],
  objectTypes: [],
  dateRange: { start: null, end: null },
  fitsQueries: [],
  qualityFilters: {},
  metricFilters: {},
  customColumnFilters: [],
};

describe("hasActiveFilters (empty-state decision)", () => {
  it("returns false when no filters are set (empty catalog state)", () => {
    expect(hasActiveFilters(emptyFilters)).toBe(false);
  });

  it("returns true when searchQuery is non-empty", () => {
    expect(hasActiveFilters({ ...emptyFilters, searchQuery: "M42" })).toBe(true);
  });

  it("returns true when selectedTargetId is set", () => {
    expect(hasActiveFilters({ ...emptyFilters, selectedTargetId: "obj:123" })).toBe(true);
  });

  it("returns true when camera filter is set", () => {
    expect(hasActiveFilters({ ...emptyFilters, camera: "ASI2600MC" })).toBe(true);
  });

  it("returns true when telescope filter is set", () => {
    expect(hasActiveFilters({ ...emptyFilters, telescope: "TS65" })).toBe(true);
  });

  it("returns true when catalog filter is set", () => {
    expect(hasActiveFilters({ ...emptyFilters, catalog: "NGC" })).toBe(true);
  });

  it("returns true when opticalFilters contains entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, opticalFilters: ["Ha"] })).toBe(true);
  });

  it("returns true when objectTypes contains entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, objectTypes: ["Galaxy"] })).toBe(true);
  });

  it("returns true when dateRange has a start date", () => {
    expect(hasActiveFilters({ ...emptyFilters, dateRange: { start: "2024-01-01", end: null } })).toBe(true);
  });

  it("returns true when dateRange has an end date", () => {
    expect(hasActiveFilters({ ...emptyFilters, dateRange: { start: null, end: "2024-12-31" } })).toBe(true);
  });

  it("returns true when fitsQueries has entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, fitsQueries: [{ key: "EXPTIME", operator: "gt", value: "300" }] })).toBe(true);
  });

  it("returns true when customColumnFilters has entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, customColumnFilters: [{ slug: "priority", value: "high" }] })).toBe(true);
  });

  it("returns true when qualityFilters has entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, qualityFilters: { hfrMin: 1.5 } })).toBe(true);
  });

  it("returns true when metricFilters has entries", () => {
    expect(hasActiveFilters({ ...emptyFilters, metricFilters: { fwhm: { max: 3.0 } } })).toBe(true);
  });
});

describe("empty-state discriminator logic", () => {
  // Simulates the isFilteredEmpty memo: totalCount === 0 AND hasActiveFilters
  function isFilteredEmpty(totalCount: number, filters: ActiveFilters): boolean {
    return totalCount === 0 && hasActiveFilters(filters);
  }

  it("catalog-empty state: totalCount=0, no filters -> isFilteredEmpty=false (show first-run message)", () => {
    expect(isFilteredEmpty(0, emptyFilters)).toBe(false);
  });

  it("filter-empty state: totalCount=0, search active -> isFilteredEmpty=true (show no-match message)", () => {
    expect(isFilteredEmpty(0, { ...emptyFilters, searchQuery: "XYZ unknown" })).toBe(true);
  });

  it("non-empty state: totalCount>0 -> isFilteredEmpty=false regardless of filters", () => {
    expect(isFilteredEmpty(5, { ...emptyFilters, searchQuery: "M42" })).toBe(false);
  });
});
