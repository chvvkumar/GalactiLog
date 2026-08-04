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

    `source` describes the pair: `"profile"` when the profile entry supplied
    at least one of the two coordinates, `"global"` when it supplied neither
    and at least one global value is set, `"unset"` when both resolved to
    None. A caller needing the origin of one field on its own compares against
    `normalize_profile_map(raw)[profile]` directly.

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
