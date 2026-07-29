import { describe, it, expect } from "vitest";
import { profileSubtext, nextProfileMap } from "./Phd2ProfilePanel";
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
    expect(nextProfileMap({ a: "Tele A" }, "b", "Tele B")).toEqual({ a: "Tele A", b: "Tele B" });
  });

  it("lets several profiles point at one telescope", () => {
    expect(nextProfileMap({ a: "Tele A" }, "b", "Tele A")).toEqual({ a: "Tele A", b: "Tele A" });
  });

  it("removes the entry when the selection is cleared", () => {
    expect(nextProfileMap({ a: "Tele A", b: "Tele B" }, "b", "")).toEqual({ a: "Tele A" });
  });

  it("does not mutate the input map", () => {
    const map = { a: "Tele A" };
    nextProfileMap(map, "a", "");
    expect(map).toEqual({ a: "Tele A" });
  });
});
