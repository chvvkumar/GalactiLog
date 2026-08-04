"""The single definition of what a PHD2 equipment-profile mapping is.

A PHD2 guide log names the equipment profile that produced it, and nothing
else about the rig. Everything GalactiLog needs to read a log correctly, which
telescope the profile belongs to, which zone its wall-clock timestamps are in
and where on Earth the rig stands, is user configuration stored in
`user_settings.general["phd2_profile_map"]`.

Stored shape, one entry per profile name::

    {"Rig A": {"telescope": "Askar 120", "timezone": "America/Chicago",
               "latitude": 30.27, "longitude": -97.74}}

Field meanings:

- `telescope: None` means the profile is not mapped to a telescope.
- `timezone: ""` means inherit `general.observer_timezone`.
- `latitude: None` and `longitude: None` mean inherit the global observer
  coordinates.

THE INHERIT MARKER FOR THE NUMERIC FIELDS IS `None`, NEVER `0`. Zero is a
legal longitude (Greenwich) and a legal latitude (the equator), so a falsy
test against either field is a defect: it would silently move a rig on the
prime meridian to the user's own site and file its nights under the wrong
date. Every test in this module against those fields is an `is None` test,
and `test_phd2_profiles.py` pins the behaviour from both directions.

The map is also written in the legacy form `{"Rig A": "Askar 120"}`, which is
what every install stored before per-rig timezones existed. Readers do not
each carry that tolerance; they call `normalize_profile_map` here, so the
coercion exists once.

This module imports neither the ORM models nor the guide-log parser. It is
pure shape handling over plain dicts, which is what lets the API layer, the
worker and the data migrations all depend on it without an import cycle. It
also means it never sees the parser/model name collision on `Phd2Frame` and
`Phd2Calibration`.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# The canonical per-profile entry. Readers may rely on every key being present
# on every entry `normalize_profile_map` returns.
_EMPTY_ENTRY: dict[str, Any] = {
    "telescope": None,
    "timezone": "",
    "latitude": None,
    "longitude": None,
}

_LATITUDE_RANGE = (-90.0, 90.0)
_LONGITUDE_RANGE = (-180.0, 180.0)


def _coerce_text(value: Any) -> str:
    """A stored string field, stripped. Anything else reads as empty."""
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_telescope(value: Any) -> str | None:
    """A telescope name, or None when the profile is not mapped.

    An empty or whitespace-only name means "not mapped" rather than "mapped to
    a telescope with no name". Today's UI expresses unmapping by deleting the
    key outright, so an empty value has never had another meaning; under the
    new shape the entry has to survive an unmapping in order to keep carrying
    the timezone and site, so the emptiness moves onto this field.
    """
    name = _coerce_text(value)
    return name or None


def _coerce_coordinate(value: Any, bounds: tuple[float, float]) -> float | None:
    """A stored coordinate, or None meaning "inherit the global value".

    None is the only marker for unset. 0.0 is a real coordinate and is
    returned as one. Out-of-range values, NaN and infinity read as unset
    rather than propagating: they cannot describe a site, and letting one
    reach the sidereal coherence check would produce a confident wrong
    verdict instead of no verdict.

    `bool` is rejected explicitly because it is a subclass of `int`, so a
    stored `true` would otherwise become latitude 1.0.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    low, high = bounds
    if number < low or number > high:
        return None
    return number


def _coerce_entry(value: Any) -> dict[str, Any] | None:
    """One stored map value in canonical form, or None to drop the entry."""
    if isinstance(value, str):
        # Legacy form: the whole value is the telescope name.
        return {**_EMPTY_ENTRY, "telescope": _coerce_telescope(value)}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        # A pydantic model, which is what the settings schema hands over when
        # a save round-trips through GeneralSettings rather than raw JSON.
        try:
            value = dump()
        except TypeError:
            return None
    if not isinstance(value, Mapping):
        return None
    return {
        "telescope": _coerce_telescope(value.get("telescope")),
        "timezone": _coerce_text(value.get("timezone")),
        "latitude": _coerce_coordinate(value.get("latitude"), _LATITUDE_RANGE),
        "longitude": _coerce_coordinate(value.get("longitude"), _LONGITUDE_RANGE),
    }


def normalize_profile_map(raw: Any) -> dict[str, dict]:
    """Every stored form of the profile map, in one canonical form.

    Accepts the legacy `{"Rig A": "Askar 120"}`, the current
    `{"Rig A": {"telescope": ..., "timezone": ..., "latitude": ...,
    "longitude": ...}}`, pydantic model values, and junk. Returns a fresh dict
    whose every value carries all four canonical keys. Entries whose value is
    neither a string nor a mapping are dropped, as are non-string keys.

    The function is idempotent and does not mutate its argument, so a caller
    that resolves many sections normalizes once and passes the result back in
    for each lookup.
    """
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        entry = _coerce_entry(value)
        if entry is not None:
            out[key] = entry
    return out


def telescope_map(raw: Any) -> dict[str, str]:
    """The profile-name to telescope-name projection, unmapped profiles absent.

    An entry with `telescope: None` is missing from the result rather than
    present with a None value, which preserves the `.get()` semantics every
    existing caller was written against: an unmapped profile has always been
    a missing key.
    """
    return {
        profile: entry["telescope"]
        for profile, entry in normalize_profile_map(raw).items()
        if entry["telescope"] is not None
    }


def _carries_configuration(entry: Mapping) -> bool:
    """Whether an entry holds anything besides its telescope.

    The coordinate tests are `is not None`, never truth tests. A rig at
    Greenwich stores longitude 0.0, and a falsy test here would read its entry
    as empty and delete the site the user configured.
    """
    return bool(entry["timezone"]) or (
        entry["latitude"] is not None or entry["longitude"] is not None
    )


def set_telescope(raw: Any, profile: str, telescope: str | None) -> dict[str, dict]:
    """The map with one profile's telescope changed, everything else intact.

    Returns a fresh canonical map; the argument is not mutated. Use this
    instead of assigning into the stored dict, which loses the timezone and
    the site of any profile it rewrites.

    Clearing the telescope (`None`, `""` or whitespace) keeps the delete-on-
    empty behaviour the settings UI relies on, but only where deleting is
    still safe: an entry that carries nothing else disappears from the map as
    it always has, while an entry that carries a timezone or a coordinate
    stays with `telescope: None` so that unmapping a rig does not silently
    discard its zone and site.
    """
    normalized = normalize_profile_map(raw)
    name = _coerce_telescope(telescope)
    entry = {**normalized.get(profile, _EMPTY_ENTRY), "telescope": name}
    if name is None and not _carries_configuration(entry):
        normalized.pop(profile, None)
        return normalized
    normalized[profile] = entry
    return normalized


def rewrite_telescopes(
    raw: Any, rename: Mapping[str, str] | Callable[[str], str | None]
) -> dict[str, dict]:
    """The map with every telescope name put through `rename`.

    This is what an equipment regrouping needs: grouping two telescope names
    turns one into an alias, which strands the map pointing at the alias, so
    the stored names are folded onto the new canonical ones. `rename` is
    either a name-to-name mapping or a callable such as
    `lambda n: normalize_equipment(n, tel_map)`. A name the rename does not
    recognise, signalled by a missing key or by a `None` or empty return, is
    left alone, so callers do not need the `or name` fallback they write
    today. Entries with no telescope are left untouched and `rename` is not
    called for them.

    Only the `telescope` field moves. The timezone and the site of every entry
    survive, which is the whole point of this living in the shape owner: the
    two rewriters that exist today rebuild the map with bare string values and
    would flatten a configured profile back to a legacy entry.

    Returns a fresh canonical map; the argument is not mutated. Test for a
    real change with `out != normalize_profile_map(raw)`, NOT `out != raw`: a
    legacy map always differs from its canonical form, so comparing against
    the stored value would report a change on every save.
    """
    lookup = rename.get if isinstance(rename, Mapping) else rename
    out = normalize_profile_map(raw)
    for profile, entry in out.items():
        current = entry["telescope"]
        if current is None:
            continue
        replacement = _coerce_telescope(lookup(current))
        if replacement is not None:
            out[profile] = {**entry, "telescope": replacement}
    return out


def _loadable(zone: str) -> bool:
    """Whether the running tzdata knows this zone name."""
    if not zone:
        return False
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False
    return True


def _resolve_zone(entry: dict | None, global_zone: str) -> tuple[str, str]:
    own = entry["timezone"] if entry else ""
    if own and _loadable(own):
        return own, "profile"
    if global_zone and _loadable(global_zone):
        return global_zone, "global"
    return "", "unset"


def profile_timezone(
    raw: Any, profile: str | None, global_tz: str | None
) -> tuple[str, str]:
    """The IANA zone a section's timestamps are in, and where it came from.

    Returns `(zone, source)` with `source` one of `"profile"`, `"global"` or
    `"unset"`. Resolution order:

    1. The profile's own `timezone`, when non-empty and loadable.
    2. `general.observer_timezone`, when non-empty and loadable.
    3. Unset, reported as `("", "unset")`.

    An unloadable per-profile zone degrades to the global one and is reported
    as `"global"`, because from the caller's point of view the global value is
    what will be used. The global value keeps its own reporter in
    `tasks_phd2._safe_timezone`, so a bad global is warned about exactly once
    per pass rather than once per section.

    A section whose header carries no equipment profile passes `None` here and
    resolves through steps 2 and 3 only.
    """
    entry = normalize_profile_map(raw).get(profile or "")
    return _resolve_zone(entry, _coerce_text(global_tz))


def profile_zone_resolver(
    raw: Any, global_tz: str | None
) -> Callable[[str | None], tuple[str, str]]:
    """A `profile_timezone` bound to one map, built once per pass.

    Resolving a zone costs a `ZoneInfo` construction, and a pass over a
    library resolves once per guiding section. This precomputes the answer for
    every configured profile plus the fallback for everything else, so a
    lookup during the pass is a dict hit.
    """
    normalized = normalize_profile_map(raw)
    global_zone = _coerce_text(global_tz)
    fallback = _resolve_zone(None, global_zone)
    answers = {
        profile: _resolve_zone(entry, global_zone)
        for profile, entry in normalized.items()
    }

    def resolve(profile: str | None) -> tuple[str, str]:
        return answers.get(profile or "", fallback)

    return resolve


def _resolve_site(
    entry: dict | None, global_lat: float | None, global_lon: float | None
) -> tuple[float | None, float | None, str]:
    own_lat = entry["latitude"] if entry else None
    own_lon = entry["longitude"] if entry else None
    lat = own_lat if own_lat is not None else global_lat
    lon = own_lon if own_lon is not None else global_lon
    if own_lat is not None or own_lon is not None:
        source = "profile"
    elif lat is not None or lon is not None:
        source = "global"
    else:
        source = "unset"
    return lat, lon, source


def profile_site(
    raw: Any,
    profile: str | None,
    global_lat: float | None,
    global_lon: float | None,
) -> tuple[float | None, float | None, str]:
    """Where a section's rig stands, and where those coordinates came from.

    Returns `(latitude, longitude, source)`. Each coordinate resolves
    independently: the profile's own value when it is not None, otherwise the
    global observer value, otherwise None.

    `source` describes the PAIR and is PRESENTATION ONLY. It reads
    `"profile"` when the entry supplied at least one of the two coordinates,
    `"global"` when it supplied neither and at least one global value is set,
    `"unset"` when both resolved to None. Use it to tell a user where the
    numbers on their screen came from, and for nothing else.

    NEVER BRANCH BEHAVIOUR ON `source`. In particular it must not select the
    sidereal cross-check's tier. A profile carrying a latitude and no
    longitude reports `"profile"` while its longitude is the home site's, so a
    tier chosen here would apply the tight 0.5 h tolerance and a confident
    verdict to an inherited value, and accuse the user of a misconfiguration
    on the strength of a coordinate they never entered. Ask
    `profile_has_own_longitude` or `profile_has_own_latitude` for the one
    field the decision actually turns on.

    The comparisons here are `is not None`, never truth tests. A profile
    standing on the prime meridian stores longitude 0.0, and a falsy check
    would hand it the user's own longitude instead and file its nights under
    the wrong date.
    """
    entry = normalize_profile_map(raw).get(profile or "")
    return _resolve_site(
        entry,
        _coerce_coordinate(global_lat, _LATITUDE_RANGE),
        _coerce_coordinate(global_lon, _LONGITUDE_RANGE),
    )


def _own_coordinate(raw: Any, profile: str | None, field: str) -> bool:
    entry = normalize_profile_map(raw).get(profile or "")
    return entry is not None and entry[field] is not None


def profile_has_own_longitude(raw: Any, profile: str | None) -> bool:
    """Whether this profile stores a longitude of its own.

    This is the tier input for the sidereal cross-check, and the only correct
    one. True means the rig's site is known, so an implied longitude can be
    compared against it under the tight tolerance and the finding stated as
    fact. False means the longitude in play is inherited from the global
    observer setting or absent entirely, so the check must fall back to the
    timezone's standard meridian, widen its tolerance and hedge its wording.

    False for an unknown profile, for a section carrying no profile, for a
    legacy string entry, and for a stored value that failed range coercion.
    True for a stored 0.0, which is a rig on the prime meridian.

    Deliberately narrower than `profile_site`'s `source`, which answers about
    the pair and cannot answer this.
    """
    return _own_coordinate(raw, profile, "longitude")


def profile_has_own_latitude(raw: Any, profile: str | None) -> bool:
    """Whether this profile stores a latitude of its own.

    The companion to `profile_has_own_longitude`, for the pointing coherence
    gate: that gate tests a rig's declination and hour angle against a
    latitude, and a remote rig tested against the home latitude would reject
    every section. True for a stored 0.0, a rig on the equator.
    """
    return _own_coordinate(raw, profile, "latitude")


def longitude_resolver(
    raw: Any, global_lon: float | None
) -> Callable[[str | None], float | None]:
    """A per-profile longitude lookup bound to one map, built once per pass.

    Longitude is the one coordinate the session-date arithmetic needs
    (`session_date.compute_session_date`), and it is resolved once per stored
    row during a re-key, so it gets its own narrow resolver.

    Returns None only when neither the profile nor the global value is set.
    That is the signal a caller uses to build the imaging-night fallback set;
    a resolved 0.0 is a site on the prime meridian and is not part of it.
    """
    normalized = normalize_profile_map(raw)
    fallback_lon = _coerce_coordinate(global_lon, _LONGITUDE_RANGE)
    answers = {
        profile: _resolve_site(entry, None, fallback_lon)[1]
        for profile, entry in normalized.items()
    }

    def resolve(profile: str | None) -> float | None:
        return answers.get(profile or "", fallback_lon)

    return resolve
