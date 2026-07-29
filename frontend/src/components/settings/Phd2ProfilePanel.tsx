import { For, Show, createSignal, createEffect, onMount, type Component } from "solid-js";
import { useSettingsContext } from "../SettingsProvider";
import { useAuth } from "../AuthProvider";
import { useCatalog } from "../../store/catalog";
import { apiClient } from "../../api/generated/client";
import { unwrap } from "../../api/unwrap";
import { showToast } from "../Toast";
import { ARCSEC } from "../../utils/format";
// Phd2Profile/Phd2ProfileListResponse are the hand-written definitions in
// `../../api/types` (strict `number | null` on the header echo fields); the
// response is cast at the boundary, same precedent as api/scanFilters.ts.
import type { Phd2Profile, Phd2ProfileListResponse } from "../../api/types";

/** Helper line under a profile name: guide camera, focal length, pixel scale, sessions. */
export function profileSubtext(profile: Phd2Profile): string {
  const parts: string[] = [];
  if (profile.guide_camera) parts.push(profile.guide_camera);
  if (profile.focal_length_mm !== null) parts.push(`${profile.focal_length_mm} mm`);
  if (profile.pixel_scale_arcsec !== null) parts.push(`${profile.pixel_scale_arcsec.toFixed(2)}${ARCSEC}/px`);
  parts.push(`${profile.session_count} ${profile.session_count === 1 ? "session" : "sessions"}`);
  return parts.join(" · ");
}

/** Immutable update of the profile map; an empty telescope clears the mapping. */
export function nextProfileMap(
  map: Record<string, string>,
  profileName: string,
  telescope: string,
): Record<string, string> {
  const next = { ...map };
  if (telescope) next[profileName] = telescope;
  else delete next[profileName];
  return next;
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
  const [profileMap, setProfileMap] = createSignal<Record<string, string>>({});

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

  const handleMap = async (profileName: string, telescope: string) => {
    const previous = profileMap();
    const updated = nextProfileMap(previous, profileName, telescope);
    setProfileMap(updated);
    const current = settings()?.general;
    if (!current) return;
    try {
      await saveGeneral({ ...current, phd2_profile_map: updated });
      showToast(telescope ? `${profileName} mapped to ${telescope}` : `${profileName} unmapped`);
    } catch {
      setProfileMap(previous);
      showToast("Failed to save profile mapping", "error");
    }
  };

  return (
    <div class="space-y-3">
      <p class="text-sm text-theme-text-secondary">
        Each PHD2 equipment profile is matched to one of your telescopes so guiding data lands on the right rig. Point several profiles at the same telescope when they are the same physical setup under different names.
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
                  <div class="flex flex-wrap items-center gap-3 rounded-[var(--radius-sm)] bg-theme-elevated border border-theme-border-em px-3 py-2">
                    <div class="min-w-0 flex-1">
                      <div class="text-sm text-theme-text-primary truncate">{profile.name}</div>
                      <div class="text-tiny text-theme-text-tertiary truncate">{profileSubtext(profile)}</div>
                    </div>
                    <select
                      class="px-3 py-1.5 bg-theme-input border border-theme-border rounded-[var(--radius-sm)] text-sm text-theme-text-primary focus:ring-1 focus:ring-theme-accent focus:border-theme-accent outline-none disabled:opacity-50"
                      disabled={!isAdmin()}
                      value={profileMap()[profile.name] ?? ""}
                      onChange={(e) => handleMap(profile.name, e.currentTarget.value)}
                    >
                      <option value="">Not mapped</option>
                      <For each={telescopeOptions()}>
                        {(t) => <option value={t.name}>{t.name}</option>}
                      </For>
                    </select>
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
