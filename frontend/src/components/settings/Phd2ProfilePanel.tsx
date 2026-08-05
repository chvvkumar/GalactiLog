import { For, Show, createSignal, createEffect, onMount, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { useAuth } from "../AuthProvider";
import { useCatalog } from "../../store/catalog";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { showToast } from "../Toast";
import { ARCSEC } from "../../utils/format";
import { supportedTimeZones, timezoneFriendlyName } from "../../utils/dateTime";
// Phd2Profile/Phd2ProfileListResponse are the hand-written definitions in
// `../../api/types` (strict `number | null` on the header echo fields); the
// response is cast at the boundary, same precedent as api/scanFilters.ts.
// GeneralSettings is the alias layer's view of the settings document, and the
// profile-map shapes below are read off it rather than re-declared, so a
// backend change to the mapping model reaches this panel through the
// generated schema instead of through a second hand-written copy.
import type { GeneralSettings, Phd2Profile, Phd2ProfileListResponse } from "../../api/types";

/** Stored profile map: raw PHD2 equipment profile name -> what that rig is. */
export type Phd2ProfileMap = NonNullable<GeneralSettings["phd2_profile_map"]>;

/**
 * One rig's configuration, and equally the shape of a patch against it.
 *
 * Every key is optional, so a patch naming one field is assignable as-is. An
 * absent `telescope` means the profile is not mapped, an empty `timezone`
 * inherits the global observer timezone, and a null `latitude`/`longitude`
 * inherits the global observer coordinates.
 */
export type Phd2ProfileEntry = Phd2ProfileMap[string];

/** Helper line under a profile name: guide camera, focal length, pixel scale, sessions. */
export function profileSubtext(profile: Phd2Profile): string {
  const parts: string[] = [];
  if (profile.guide_camera) parts.push(profile.guide_camera);
  if (profile.focal_length_mm !== null) parts.push(`${profile.focal_length_mm} mm`);
  if (profile.pixel_scale_arcsec !== null) parts.push(`${profile.pixel_scale_arcsec.toFixed(2)}${ARCSEC}/px`);
  parts.push(`${profile.session_count} ${profile.session_count === 1 ? "session" : "sessions"}`);
  return parts.join(" · ");
}

/**
 * True when an entry carries nothing worth storing.
 *
 * The coordinate tests are `== null`, never truth tests: latitude 0 is the
 * equator and longitude 0 is Greenwich, both legal stored values, and a falsy
 * check would throw away a rig's site the moment it sat on either line.
 */
function isEmptyEntry(entry: Phd2ProfileEntry): boolean {
  return (
    !entry.telescope &&
    !entry.timezone &&
    entry.latitude == null &&
    entry.longitude == null
  );
}

/**
 * Immutable update of the profile map, merging a partial patch into one entry.
 *
 * The patch names only the field that changed (`{telescope}`, `{timezone}`,
 * `{latitude}` or `{longitude}`) and the rest of the entry is carried across,
 * so clearing the telescope on a rig that has a zone and a site leaves the row
 * in place with no telescope rather than discarding where and when it
 * observes. The key is deleted only when the merged entry has no telescope, no
 * timezone and neither coordinate.
 */
export function nextProfileMap(
  map: Phd2ProfileMap,
  profileName: string,
  patch: Phd2ProfileEntry,
): Phd2ProfileMap {
  const next = { ...map };
  const merged: Phd2ProfileEntry = { ...(next[profileName] ?? {}), ...patch };
  if (isEmptyEntry(merged)) delete next[profileName];
  else next[profileName] = merged;
  return next;
}

const COORDINATE_RANGE = {
  latitude: { min: -90, max: 90, label: "Latitude" },
  longitude: { min: -180, max: 180, label: "Longitude" },
} as const;

export type CoordinateAxis = keyof typeof COORDINATE_RANGE;

/**
 * A typed coordinate, as a value to store plus an error to show.
 *
 * Empty input is not an error: it is how a rig says "inherit the global
 * observer coordinate", and it stores null. A number outside its axis range is
 * rejected here rather than sent, because the backend's stored-value
 * normalizer degrades an out-of-range coordinate to null on the way in and the
 * user would watch their entry silently disappear.
 */
export function readCoordinate(
  raw: string,
  axis: CoordinateAxis,
): { value: number | null; error: string | null } {
  const trimmed = raw.trim();
  if (!trimmed) return { value: null, error: null };
  const parsed = Number(trimmed);
  const { min, max, label } = COORDINATE_RANGE[axis];
  if (!Number.isFinite(parsed)) return { value: null, error: `${label} must be a number` };
  if (parsed < min || parsed > max) return { value: null, error: `${label} runs from ${min} to ${max}` };
  return { value: parsed, error: null };
}

/**
 * A coordinate written the way a chart writes it: magnitude plus hemisphere.
 *
 * A sign typed into the wrong field is the classic entry mistake, and a
 * longitude that should read W reading E moves the imaging-night boundary by
 * up to twelve hours and invites a sidereal cross-check to accuse the user of
 * a misconfiguration they never made. Reading the value back as "97.74° W"
 * makes that mistake visible at the moment it is made. Zero is signless in
 * both axes, so it takes the positive word: the equator and the prime
 * meridian.
 */
export function formatCoordinate(value: number, axis: CoordinateAxis): string {
  const hemisphere = axis === "latitude" ? (value < 0 ? "S" : "N") : (value < 0 ? "W" : "E");
  return `${String(Number(Math.abs(value).toFixed(4)))}° ${hemisphere}`;
}

/**
 * The zone a rig's guide-log timestamps will be read in, and where it came
 * from. Mirrors the backend's `profile_timezone`: the profile's own zone when
 * it has one, otherwise the global observer timezone, otherwise nothing.
 */
export function resolvedZone(
  entry: Phd2ProfileEntry | undefined,
  globalZone: string | null | undefined,
): { zone: string; source: "profile" | "global" | "unset" } {
  const own = (entry?.timezone ?? "").trim();
  if (own) return { zone: own, source: "profile" };
  const shared = (globalZone ?? "").trim();
  if (shared) return { zone: shared, source: "global" };
  return { zone: "", source: "unset" };
}

/**
 * The site a rig will be placed at, written back with hemispheres and with
 * the inherited half named.
 *
 * Each axis resolves independently, matching the backend's `profile_site`: a
 * rig may carry its own latitude and inherit its longitude. The comparisons
 * are `== null` so a stored 0 counts as the rig's own value.
 */
export function resolvedSiteText(
  entry: Phd2ProfileEntry | undefined,
  globalLatitude: number | null | undefined,
  globalLongitude: number | null | undefined,
): string {
  const ownLat = entry?.latitude ?? null;
  const ownLon = entry?.longitude ?? null;
  const latitude = ownLat != null ? ownLat : globalLatitude ?? null;
  const longitude = ownLon != null ? ownLon : globalLongitude ?? null;
  if (latitude == null && longitude == null) {
    return "No location set here or under Observer Location.";
  }
  const written = [
    latitude == null ? "latitude not set" : formatCoordinate(latitude, "latitude"),
    longitude == null ? "longitude not set" : formatCoordinate(longitude, "longitude"),
  ].join(", ");
  const inherited = [
    ownLat == null && latitude != null ? "latitude" : null,
    ownLon == null && longitude != null ? "longitude" : null,
  ].filter((axis): axis is string => axis !== null);
  if (inherited.length === 2) return `${written} (from Observer Location)`;
  if (inherited.length === 1) return `${written} (${inherited[0]} from Observer Location)`;
  return written;
}

/** The value a coordinate input should show: "" for inherit, "0" for zero. */
export function coordinateInputValue(value: number | null | undefined): string {
  return value == null ? "" : String(value);
}

export const Phd2ProfilePanel: Component = () => {
  const { settings, saveGeneral } = useSettingsContext();
  const { isAdmin } = useAuth();
  const { equipment } = useCatalog();
  const [profiles, setProfiles] = createSignal<Phd2Profile[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [failed, setFailed] = createSignal(false);
  // Local mirror of general.phd2_profile_map so a select reflects the choice
  // immediately and rolls back if the save fails (handleAutoScanToggle shape).
  const [profileMap, setProfileMap] = createSignal<Phd2ProfileMap>({});
  // Per-row, per-axis coordinate complaints, keyed "<profile>|<axis>". Held
  // outside the map so a rejected entry is reported without being stored.
  const [coordinateErrors, setCoordinateErrors] = createSignal<Record<string, string>>({});

  createEffect(() => {
    const s = settings();
    if (s) setProfileMap(s.general.phd2_profile_map ?? {});
  });

  onMount(async () => {
    try {
      const data = (await apiClient
        .GET("/api/phd2/profiles", {})
        .then(unwrap)) as unknown as Phd2ProfileListResponse;
      setProfiles(data.profiles);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  });

  const telescopeOptions = () => equipment()?.telescopes ?? [];
  const entryFor = (profileName: string): Phd2ProfileEntry | undefined => profileMap()[profileName];
  const globalZone = () => settings()?.general.observer_timezone ?? "";
  const globalLatitude = () => settings()?.general.observer_latitude ?? null;
  const globalLongitude = () => settings()?.general.observer_longitude ?? null;

  // Read once per mount rather than per render: the answer cannot change while
  // the page is open, and a null means this runtime cannot enumerate zones, so
  // the field degrades to free text instead of an empty dropdown the user
  // cannot escape. Same source as the global timezone field on the Library tab.
  const timezoneList = supportedTimeZones();

  // A stored zone this runtime does not list (a legacy name like "US/Central",
  // or one only Python's zoneinfo knows) still has to be visible. Without its
  // own option the select falls back to the placeholder, which reads as "uses
  // the global timezone" while the server holds a zone for this rig and
  // applies it.
  const unlistedZone = (profileName: string): string | null => {
    const own = (entryFor(profileName)?.timezone ?? "").trim();
    if (!own) return null;
    return timezoneList && timezoneList.includes(own) ? null : own;
  };

  const zoneText = (profileName: string): string => {
    const { zone, source } = resolvedZone(entryFor(profileName), globalZone());
    if (source === "unset") return "";
    const friendly = timezoneFriendlyName(zone);
    const name = friendly === zone ? zone : `${friendly} (${zone})`;
    return source === "global" ? `${name}, from Observer Location` : name;
  };

  const zoneUnset = (profileName: string) =>
    resolvedZone(entryFor(profileName), globalZone()).source === "unset";

  const coordinateError = (profileName: string, axis: CoordinateAxis) =>
    coordinateErrors()[`${profileName}|${axis}`];

  const setCoordinateError = (profileName: string, axis: CoordinateAxis, message: string | null) => {
    const key = `${profileName}|${axis}`;
    setCoordinateErrors((prev) => {
      if (message === null) {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      return { ...prev, [key]: message };
    });
  };

  const saveEntry = async (profileName: string, patch: Phd2ProfileEntry, message: string) => {
    const current = settings()?.general;
    if (!current) return;
    const previous = profileMap();
    const updated = nextProfileMap(previous, profileName, patch);
    setProfileMap(updated);
    try {
      await saveGeneral({ ...current, phd2_profile_map: updated });
      showToast(message);
    } catch {
      setProfileMap(previous);
      showToast("Failed to save profile settings", "error");
    }
  };

  const handleMap = (profileName: string, telescope: string) =>
    saveEntry(
      profileName,
      { telescope: telescope || null },
      telescope ? `${profileName} mapped to ${telescope}` : `${profileName} unmapped`,
    );

  const handleTimezone = (profileName: string, timezone: string) =>
    saveEntry(
      profileName,
      { timezone },
      timezone ? `${profileName} set to ${timezone}` : `${profileName} uses the global timezone`,
    );

  const handleCoordinate = (profileName: string, axis: CoordinateAxis, raw: string) => {
    const { value, error } = readCoordinate(raw, axis);
    setCoordinateError(profileName, axis, error);
    if (error) return;
    const patch: Phd2ProfileEntry = axis === "latitude" ? { latitude: value } : { longitude: value };
    const where = value === null ? "uses the global location" : `${axis} set to ${formatCoordinate(value, axis)}`;
    return saveEntry(profileName, patch, `${profileName} ${where}`);
  };

  return (
    <div class="space-y-3">
      <p class="text-sm text-theme-text-secondary">
        Each PHD2 equipment profile is matched to one of your telescopes so guiding data lands on the right rig. Point several profiles at the same telescope when they are the same physical setup under different names.
      </p>
      <p class="text-sm text-theme-text-secondary">
        A profile with no timezone of its own reads its guide logs in the global timezone under Observer Location, and one with no coordinates stands at the global location. A rig that observes in another timezone, or from a remote site, needs its own: PHD2 writes wall-clock timestamps with no zone marker, so the wrong clock files a night under the wrong date. Clearing the telescope leaves the timezone and location in place.
      </p>

      <Show when={!loading()} fallback={<div class="text-sm text-theme-text-secondary">Loading profiles...</div>}>
        <Show when={!failed()} fallback={
          <div class="text-sm text-theme-warning">Could not load PHD2 profiles.</div>
        }>
          <Show when={profiles().length > 0} fallback={
            <div class="text-sm text-theme-text-secondary">
              No PHD2 profiles found yet. They appear here after a scan reads a guide log.
            </div>
          }>
            <div class="space-y-2">
              <For each={profiles()}>
                {(profile) => (
                  <div class="space-y-2 rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em px-3 py-2">
                    <div class="flex flex-wrap items-end gap-3">
                      <div class="min-w-0 flex-1 self-center">
                        <div class="text-sm text-theme-text-primary truncate">{profile.name}</div>
                        <div class="text-tiny text-theme-text-tertiary truncate">{profileSubtext(profile)}</div>
                      </div>

                      <label class="flex flex-col gap-0.5">
                        <span class="text-tiny text-theme-text-tertiary">Telescope</span>
                        <select
                          class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none disabled:opacity-50"
                          disabled={!isAdmin()}
                          value={entryFor(profile.name)?.telescope ?? ""}
                          onChange={(e) => handleMap(profile.name, e.currentTarget.value)}
                        >
                          <option value="">Not mapped</option>
                          <For each={telescopeOptions()}>
                            {(t) => <option value={t.name}>{t.name}</option>}
                          </For>
                        </select>
                      </label>

                      <label class="flex flex-col gap-0.5">
                        <span class="text-tiny text-theme-text-tertiary">Timezone</span>
                        <Show
                          when={timezoneList}
                          fallback={
                            <input
                              type="text"
                              placeholder="Use the global timezone"
                              class="w-44 px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none disabled:opacity-50"
                              disabled={!isAdmin()}
                              value={entryFor(profile.name)?.timezone ?? ""}
                              onChange={(e) => handleTimezone(profile.name, e.currentTarget.value.trim())}
                            />
                          }
                        >
                          {(zones) => (
                            <select
                              class="w-44 px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none disabled:opacity-50"
                              disabled={!isAdmin()}
                              value={entryFor(profile.name)?.timezone ?? ""}
                              onChange={(e) => handleTimezone(profile.name, e.currentTarget.value)}
                            >
                              {/* No "server timezone" entry, deliberately: the
                                  server runs on UTC inside its container
                                  whatever clock the host keeps, so it is never
                                  the zone that wrote the guide log. */}
                              <option value="">Use the global timezone</option>
                              <Show when={unlistedZone(profile.name)}>
                                {(zone) => <option value={zone()}>{zone()}</option>}
                              </Show>
                              <For each={zones()}>{(zone) => <option value={zone}>{zone}</option>}</For>
                            </select>
                          )}
                        </Show>
                      </label>

                      <label class="flex flex-col gap-0.5">
                        <span class="text-tiny text-theme-text-tertiary">Latitude</span>
                        <input
                          type="number"
                          step="any"
                          min="-90"
                          max="90"
                          placeholder="Use the global location"
                          class={`w-32 px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 outline-none disabled:opacity-50 ${
                            coordinateError(profile.name, "latitude")
                              ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                              : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                          }`}
                          disabled={!isAdmin()}
                          value={coordinateInputValue(entryFor(profile.name)?.latitude)}
                          onChange={(e) => handleCoordinate(profile.name, "latitude", e.currentTarget.value)}
                        />
                      </label>

                      <label class="flex flex-col gap-0.5">
                        <span class="text-tiny text-theme-text-tertiary">Longitude</span>
                        <input
                          type="number"
                          step="any"
                          min="-180"
                          max="180"
                          placeholder="Use the global location"
                          class={`w-32 px-3 py-1.5 bg-theme-input border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 outline-none disabled:opacity-50 ${
                            coordinateError(profile.name, "longitude")
                              ? "border-red-500 focus:ring-red-500 focus:border-red-500"
                              : "border-theme-border focus:ring-theme-accent focus:border-theme-accent"
                          }`}
                          disabled={!isAdmin()}
                          value={coordinateInputValue(entryFor(profile.name)?.longitude)}
                          onChange={(e) => handleCoordinate(profile.name, "longitude", e.currentTarget.value)}
                        />
                      </label>
                    </div>

                    <div class="space-y-0.5 text-tiny">
                      <Show when={zoneUnset(profile.name)} fallback={
                        <p class="text-theme-text-tertiary">Reads guide logs in {zoneText(profile.name)}.</p>
                      }>
                        {/* Exactly the state the correlation guard refuses to
                            fill guiding metrics from, so say so on the row
                            rather than leaving the numbers quietly missing. */}
                        <p class="text-theme-warning">
                          No timezone here or under Observer Location. This rig's guide logs are catalogued but their guiding numbers are not matched to frames until one is set.
                        </p>
                      </Show>
                      <p class="text-theme-text-tertiary">Site: {resolvedSiteText(entryFor(profile.name), globalLatitude(), globalLongitude())}</p>
                      <For each={(["latitude", "longitude"] as const).map((axis) => coordinateError(profile.name, axis)).filter((m): m is string => !!m)}>
                        {(message) => <p class="text-red-500">{message}</p>}
                      </For>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </Show>
    </div>
  );
};
