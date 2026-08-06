import { describe, it, expect } from "vitest";
import { isValidTimeZone } from "./dateTime";

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
