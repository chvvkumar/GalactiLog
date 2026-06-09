import { describe, it, expect } from "vitest";

// Pure validation rules extracted from ScanManager observer location inputs.
// These mirror the inline onInput logic for lat/lng fields.

const validateLatitude = (v: number): string | null =>
  v < -90 || v > 90 ? "Must be between -90 and 90" : null;

const validateLongitude = (v: number): string | null =>
  v < -180 || v > 180 ? "Must be between -180 and 180" : null;

describe("observer latitude validation", () => {
  it("accepts the valid range boundaries", () => {
    expect(validateLatitude(-90)).toBeNull();
    expect(validateLatitude(0)).toBeNull();
    expect(validateLatitude(90)).toBeNull();
  });

  it("rejects values below -90", () => {
    expect(validateLatitude(-90.0001)).toBe("Must be between -90 and 90");
    expect(validateLatitude(-180)).toBe("Must be between -90 and 90");
  });

  it("rejects values above 90", () => {
    expect(validateLatitude(90.0001)).toBe("Must be between -90 and 90");
    expect(validateLatitude(180)).toBe("Must be between -90 and 90");
  });
});

describe("observer longitude validation", () => {
  it("accepts the valid range boundaries", () => {
    expect(validateLongitude(-180)).toBeNull();
    expect(validateLongitude(0)).toBeNull();
    expect(validateLongitude(180)).toBeNull();
  });

  it("rejects values below -180", () => {
    expect(validateLongitude(-180.0001)).toBe("Must be between -180 and 180");
    expect(validateLongitude(-360)).toBe("Must be between -180 and 180");
  });

  it("rejects values above 180", () => {
    expect(validateLongitude(180.0001)).toBe("Must be between -180 and 180");
    expect(validateLongitude(360)).toBe("Must be between -180 and 180");
  });
});
