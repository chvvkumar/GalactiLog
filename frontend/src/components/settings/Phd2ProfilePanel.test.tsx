import { describe, it, expect } from "vitest";
import {
  profileSubtext,
  nextProfileMap,
  readCoordinate,
  formatCoordinate,
  coordinateInputValue,
  resolvedZone,
  resolvedSiteText,
} from "./Phd2ProfilePanel";
import type { Phd2Profile } from "../../api/types";

const base: Phd2Profile = {
  name: "140APO_AM5N_ASI174MM",
  guide_camera: "ZWO ASI174MM Mini",
  focal_length_mm: 784,
  pixel_scale_arcsec: 1.54,
  session_count: 42,
  first_seen: "2026-01-14T22:10:00Z",
  last_seen: "2026-07-14T21:42:27Z",
  mapped_telescope: null,
};

describe("profileSubtext", () => {
  it("renders camera, focal length, pixel scale and session count", () => {
    expect(profileSubtext(base)).toBe("ZWO ASI174MM Mini · 784 mm · 1.54″/px · 42 sessions");
  });

  it("drops the parts the log header did not carry", () => {
    expect(
      profileSubtext({ ...base, guide_camera: null, focal_length_mm: null })
    ).toBe("1.54″/px · 42 sessions");
  });

  it("singularises a one-session profile", () => {
    expect(profileSubtext({ ...base, session_count: 1 })).toBe(
      "ZWO ASI174MM Mini · 784 mm · 1.54″/px · 1 session"
    );
  });
});

describe("nextProfileMap", () => {
  it("adds a mapping without disturbing the others", () => {
    expect(nextProfileMap({ a: { telescope: "Tele A" } }, "b", { telescope: "Tele B" })).toEqual({
      a: { telescope: "Tele A" },
      b: { telescope: "Tele B" },
    });
  });

  it("lets several profiles point at one telescope", () => {
    expect(nextProfileMap({ a: { telescope: "Tele A" } }, "b", { telescope: "Tele A" })).toEqual({
      a: { telescope: "Tele A" },
      b: { telescope: "Tele A" },
    });
  });

  it("removes the entry when the last thing it held is cleared", () => {
    expect(
      nextProfileMap({ a: { telescope: "Tele A" }, b: { telescope: "Tele B" } }, "b", { telescope: null })
    ).toEqual({ a: { telescope: "Tele A" } });
  });

  it("does not mutate the input map", () => {
    const map = { a: { telescope: "Tele A" } };
    nextProfileMap(map, "a", { telescope: null });
    expect(map).toEqual({ a: { telescope: "Tele A" } });
  });

  it("merges a patch into the fields the entry already carries", () => {
    expect(
      nextProfileMap({ a: { telescope: "Tele A", timezone: "America/Chicago" } }, "a", { latitude: 30.27 })
    ).toEqual({ a: { telescope: "Tele A", timezone: "America/Chicago", latitude: 30.27 } });
  });

  it("keeps the row after unmapping a rig that has a zone or a site", () => {
    expect(
      nextProfileMap({ a: { telescope: "Tele A", timezone: "Europe/Madrid", longitude: -3.7 } }, "a", {
        telescope: null,
      })
    ).toEqual({ a: { telescope: null, timezone: "Europe/Madrid", longitude: -3.7 } });
  });

  it("keeps a row whose only remaining value is longitude 0", () => {
    expect(nextProfileMap({ a: { telescope: "Tele A", longitude: 0 } }, "a", { telescope: null })).toEqual({
      a: { telescope: null, longitude: 0 },
    });
  });

  it("keeps a row whose only remaining value is latitude 0", () => {
    expect(nextProfileMap({ a: { timezone: "UTC", latitude: 0 } }, "a", { timezone: "" })).toEqual({
      a: { timezone: "", latitude: 0 },
    });
  });

  it("removes the entry only once every field is empty", () => {
    const withSite = nextProfileMap({ a: { telescope: "Tele A", latitude: 30.27 } }, "a", { telescope: null });
    expect(withSite).toEqual({ a: { telescope: null, latitude: 30.27 } });
    expect(nextProfileMap(withSite, "a", { latitude: null })).toEqual({});
  });

  it("creates an entry for a profile that had none when only a zone is set", () => {
    expect(nextProfileMap({}, "a", { timezone: "Pacific/Auckland" })).toEqual({
      a: { timezone: "Pacific/Auckland" },
    });
  });
});

describe("readCoordinate", () => {
  it("reads a typed coordinate", () => {
    expect(readCoordinate("30.27", "latitude")).toEqual({ value: 30.27, error: null });
  });

  it("reads a negative coordinate", () => {
    expect(readCoordinate("-97.74", "longitude")).toEqual({ value: -97.74, error: null });
  });

  it("keeps zero as a stored coordinate rather than an empty field", () => {
    expect(readCoordinate("0", "longitude")).toEqual({ value: 0, error: null });
    expect(readCoordinate("0", "latitude")).toEqual({ value: 0, error: null });
  });

  it("treats an empty field as inherit, not as an error", () => {
    expect(readCoordinate("", "latitude")).toEqual({ value: null, error: null });
    expect(readCoordinate("   ", "longitude")).toEqual({ value: null, error: null });
  });

  it("rejects text that is not a number", () => {
    expect(readCoordinate("north", "latitude")).toEqual({
      value: null,
      error: "Latitude must be a number",
    });
  });

  it("rejects a coordinate outside its axis range before the backend drops it", () => {
    expect(readCoordinate("91", "latitude")).toEqual({
      value: null,
      error: "Latitude runs from -90 to 90",
    });
    expect(readCoordinate("-181", "longitude")).toEqual({
      value: null,
      error: "Longitude runs from -180 to 180",
    });
  });

  it("accepts the range endpoints", () => {
    expect(readCoordinate("90", "latitude")).toEqual({ value: 90, error: null });
    expect(readCoordinate("180", "longitude")).toEqual({ value: 180, error: null });
  });
});

describe("formatCoordinate", () => {
  it("writes a northern latitude with its hemisphere", () => {
    expect(formatCoordinate(30.27, "latitude")).toBe("30.27° N");
  });

  it("writes a southern latitude with its hemisphere", () => {
    expect(formatCoordinate(-33.87, "latitude")).toBe("33.87° S");
  });

  it("writes a western longitude with its hemisphere", () => {
    expect(formatCoordinate(-97.74, "longitude")).toBe("97.74° W");
  });

  it("writes an eastern longitude with its hemisphere", () => {
    expect(formatCoordinate(151.21, "longitude")).toBe("151.21° E");
  });

  it("gives the equator and the prime meridian the positive word", () => {
    expect(formatCoordinate(0, "latitude")).toBe("0° N");
    expect(formatCoordinate(0, "longitude")).toBe("0° E");
  });

  it("drops trailing zeros rather than padding to four places", () => {
    expect(formatCoordinate(45, "latitude")).toBe("45° N");
    expect(formatCoordinate(-1.5, "longitude")).toBe("1.5° W");
  });
});

describe("coordinateInputValue", () => {
  it("shows an empty field for an inherited coordinate", () => {
    expect(coordinateInputValue(null)).toBe("");
    expect(coordinateInputValue(undefined)).toBe("");
  });

  it("shows a stored zero as zero, not as empty", () => {
    expect(coordinateInputValue(0)).toBe("0");
  });

  it("shows a stored coordinate", () => {
    expect(coordinateInputValue(-97.74)).toBe("-97.74");
  });
});

describe("resolvedZone", () => {
  it("prefers the profile's own zone", () => {
    expect(resolvedZone({ timezone: "Europe/Madrid" }, "America/Chicago")).toEqual({
      zone: "Europe/Madrid",
      source: "profile",
    });
  });

  it("falls back to the global zone when the profile has none", () => {
    expect(resolvedZone({ telescope: "Tele A" }, "America/Chicago")).toEqual({
      zone: "America/Chicago",
      source: "global",
    });
  });

  it("falls back to the global zone for a profile with no entry at all", () => {
    expect(resolvedZone(undefined, "America/Chicago")).toEqual({
      zone: "America/Chicago",
      source: "global",
    });
  });

  it("reports unset when neither level carries a zone", () => {
    expect(resolvedZone({ telescope: "Tele A" }, "")).toEqual({ zone: "", source: "unset" });
    expect(resolvedZone(undefined, null)).toEqual({ zone: "", source: "unset" });
  });
});

describe("resolvedSiteText", () => {
  it("writes the rig's own site without an inheritance note", () => {
    expect(resolvedSiteText({ latitude: 30.27, longitude: -97.74 }, 51.5, -0.12)).toBe(
      "30.27° N, 97.74° W"
    );
  });

  it("names Observer Location when both coordinates are inherited", () => {
    expect(resolvedSiteText({ telescope: "Tele A" }, 51.5, -0.12)).toBe(
      "51.5° N, 0.12° W (from Observer Location)"
    );
  });

  it("names the inherited half when only one coordinate is the rig's own", () => {
    expect(resolvedSiteText({ latitude: 30.27 }, 51.5, -0.12)).toBe(
      "30.27° N, 0.12° W (longitude from Observer Location)"
    );
  });

  it("treats a stored zero as the rig's own coordinate, not as inherit", () => {
    expect(resolvedSiteText({ latitude: 0, longitude: 0 }, 51.5, -0.12)).toBe("0° N, 0° E");
  });

  it("says so when neither level has a location", () => {
    expect(resolvedSiteText(undefined, null, null)).toBe(
      "No location set here or under Observer Location."
    );
  });

  it("reports the axis that is still missing", () => {
    expect(resolvedSiteText({ longitude: -97.74 }, null, null)).toBe("latitude not set, 97.74° W");
  });
});
