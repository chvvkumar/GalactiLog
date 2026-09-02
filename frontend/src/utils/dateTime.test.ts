import { describe, it, expect } from "vitest";
import { isValidTimeZone, relativeTime } from "./dateTime";

describe("isValidTimeZone", () => {
  it("accepts real IANA zone names", () => {
    expect(isValidTimeZone("America/New_York")).toBe(true);
    expect(isValidTimeZone("Europe/Berlin")).toBe(true);
    expect(isValidTimeZone("UTC")).toBe(true);
  });

  it("rejects made-up or malformed zone names", () => {
    expect(isValidTimeZone("Mars/Phobos")).toBe(false);
    expect(isValidTimeZone("EST5EDT!")).toBe(false);
    expect(isValidTimeZone("America/New York")).toBe(false);
  });

  it("treats empty and whitespace-only input as not a zone", () => {
    expect(isValidTimeZone("")).toBe(false);
    expect(isValidTimeZone("   ")).toBe(false);
  });
});

describe("relativeTime", () => {
  const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();

  it("picks the largest unit that fits", () => {
    expect(relativeTime(ago(45))).toContain("second");
    expect(relativeTime(ago(300))).toContain("minute");
    expect(relativeTime(ago(7200))).toContain("hour");
    expect(relativeTime(ago(3 * 86400))).toContain("day");
    expect(relativeTime(ago(90 * 86400))).toContain("month");
    expect(relativeTime(ago(400 * 86400))).toContain("year");
  });

  it("falls back to the never label for a missing or unparseable timestamp", () => {
    expect(relativeTime(null)).toBe("Never");
    expect(relativeTime(undefined)).toBe("Never");
    expect(relativeTime("not a date")).toBe("Never");
    expect(relativeTime(null, "Unused")).toBe("Unused");
  });
});
