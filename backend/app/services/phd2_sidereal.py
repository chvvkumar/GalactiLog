"""Sidereal cross-check for PHD2 guide-log timezones.

PHD2 guide logs record a bare local wall-clock time. A corpus survey over 252
files and 8 PHD2 versions found no timezone, no UTC offset and no UTC
timestamp anywhere in the format, so the zone has to be configured by hand and
a wrong one silently shifts every guiding session by whole hours.

The logs do carry pointing, though. A guiding section header writes RA and
hour angle, and `LST = RA + HA` by definition. Local sidereal time is fixed by
where the telescope is looking, not by what any clock says, so comparing it
against GMST at the instant the configured zone implies solves for the
longitude the logs believe the rig is at. Disagreement with the configured
longitude means the assumed instant is wrong, which means the configured
timezone or the mount's own clock is wrong.

This module is evidence for a warning and never a source of truth. It rests on
the mount's clock and the mount's coordinates both being right, and neither is
guaranteed. Nothing here may change a stored value.

Sign convention, pinned by test rather than asserted from the formula:

- Longitude is east-positive throughout, matching `session_date.py`, whose
  solar-noon rule is `12 - longitude / 15`.
- `offset_error_hours` is positive when the configured setup is AHEAD of what
  the pointing implies. A rig really on UTC-4, mislabelled UTC+1, yields
  about +5. The true offset is therefore the configured offset minus the
  reported error.

No astropy
----------
`astropy.time.Time.sidereal_time` reaches for IERS earth-rotation tables and
attempts a network download when they are stale. This code runs inside
guide-log ingest on a Celery worker that may be offline, and that exact
staleness failure is already breaking another job in production, so the
standard GMST polynomial is used instead. Its residual against astropy 7.2.0
across 1987 to 2026 is under 4 milliseconds, five orders of magnitude tighter
than the half-hour tolerance below. `astro_night.py` may keep its astropy
import; this module must not gain one.

Threshold rationale
-------------------
`SIDEREAL_TOLERANCE_HOURS = 0.5` sits far above the noise floor and below the
smallest mistake a user can actually make. Above: RA and hour angle are
written to 0.01 hr, which is 36 s, the pointing line is written once at
section start rather than tracked through the section, and mount clocks are
usually NTP-fed, so a correct configuration lands within a few minutes. A
tenth of an hour would sit inside that noise and generate false accusations.
Below: the smallest timezone error available in practice is one hour, and even
the half-hour zones (India, Newfoundland, parts of Australia) are misread as
whole-hour neighbours far more often than as each other. 0.5 h catches every
realistic error and nothing else.

`SIDEREAL_MAX_SPREAD_HOURS = 0.25` on the interquartile range is what stops
the check crying wolf. A timezone error is a constant: every section of every
night is displaced by the same amount, so real evidence looks like a tight
cluster. A drifting mount clock, a profile carried between two sites, a mount
reporting apparent rather than mean coordinates, or a stale pointing line
copied from an earlier target all produce scatter. Scatter means the premises
failed, so no verdict is emitted rather than a confident wrong one. The
quartile range rather than the full range keeps one bad section from
suppressing a real finding.

`MIN_SIDEREAL_SECTIONS = 3` keeps a single bad pointing line from generating a
warning at all, and is what makes the spread guard meaningful: a spread over
one or two samples measures nothing.

`SIDEREAL_NO_SITE_TOLERANCE_HOURS = 3.0` applies only when the profile has no
longitude of its own and the comparison falls back to the timezone's standard
meridian. Real zones are wide: western Xinjiang is roughly 3 h from the UTC+8
meridian, and Spain and western Argentina are comparable. Anything under 3 h
against a standard meridian is explained by zone geography alone, so this tier
detects only gross errors and its finding is labelled probable rather than
stated as fact.

`POINTING_MAX_ALT_RESIDUAL_DEG = 3.0` gates everything above. The pointing
block is internally checkable with no clock and no longitude at all, because
`sin(alt) = sin(lat) sin(dec) + cos(lat) cos(dec) cos(HA)` involves only
latitude, declination, hour angle and altitude. When the reported altitude
disagrees with the one the configured latitude predicts, the mount's own
coordinates are incoherent and no timezone verdict may be drawn from them.
3 degrees clears atmospheric refraction (half a degree at the horizon, less
everywhere else), the 0.1 degree write precision, and ordinary pointing-model
error, while still catching a mount that is set up for the wrong hemisphere or
is reporting a stale position.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# See the threshold rationale in the module docstring. Do not change one of
# these without reading it.
MIN_SIDEREAL_SECTIONS = 3
SIDEREAL_TOLERANCE_HOURS = 0.5
SIDEREAL_MAX_SPREAD_HOURS = 0.25
SIDEREAL_NO_SITE_TOLERANCE_HOURS = 3.0
POINTING_MAX_ALT_RESIDUAL_DEG = 3.0

# Tier 1: the profile carries its own longitude, so the site is known and the
# finding is unambiguous.
TIER_SITE_KNOWN = "site"
# Tier 2: the profile carries a timezone but no longitude, so the comparison
# falls back to that zone's standard meridian and only gross errors show.
TIER_ZONE_MERIDIAN = "meridian"

_TOLERANCE_BY_TIER = {
    TIER_SITE_KNOWN: SIDEREAL_TOLERANCE_HOURS,
    TIER_ZONE_MERIDIAN: SIDEREAL_NO_SITE_TOLERANCE_HOURS,
}

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_UNIX_EPOCH_JD = 2440587.5
_J2000_JD = 2451545.0
_JULIAN_CENTURY_DAYS = 36525.0
_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class SidVerdict:
    """One profile's sidereal disagreement, when there is enough evidence.

    `median_error_hours` follows the module sign convention: positive means
    the configured setup runs ahead of what the pointing implies.
    `nearest_whole_hours` is the roundable form for user-facing wording.
    `confident` is False on the standard-meridian tier, where the wording must
    say "probable" rather than stating the finding as fact.
    """

    median_error_hours: float
    nearest_whole_hours: int
    sample_count: int
    tier: str
    tolerance_hours: float
    confident: bool
    implied_longitude_deg: float | None = None


def wrap12(hours: float) -> float:
    """Fold an hour difference into [-12, 12).

    Longitude and hour-angle differences are circular; the short way round is
    always the intended one.
    """
    return ((hours + 12.0) % 24.0) - 12.0


def julian_day(instant: datetime) -> float:
    """Julian Day for a UTC instant. A naive instant is read as UTC."""
    if instant.tzinfo is None:
        aware = instant.replace(tzinfo=timezone.utc)
    else:
        aware = instant.astimezone(timezone.utc)
    return _UNIX_EPOCH_JD + (aware - _UNIX_EPOCH).total_seconds() / _SECONDS_PER_DAY


def gmst_hours(instant: datetime) -> float:
    """Greenwich mean sidereal time in hours, in [0, 24).

    The standard polynomial (Meeus, Astronomical Algorithms, eq. 12.4), not
    astropy. See the module docstring for why.
    """
    jd = julian_day(instant)
    d = jd - _J2000_JD
    t = d / _JULIAN_CENTURY_DAYS
    degrees = (
        280.46061837
        + 360.98564736629 * d
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return (degrees % 360.0) / 15.0


def implied_longitude_hours(
    ra_hr: float | None, hour_angle_hr: float | None, instant: datetime
) -> float | None:
    """Longitude in hours east that the pointing implies at `instant`.

    `instant` is the UTC moment the configured timezone assigns to the log's
    wall-clock timestamp. If that timezone is wrong the instant is wrong and
    this value is displaced by the same amount, which is the whole point.

    Returns None when the pointing is incomplete. ASIAIR-flavoured logs write
    no RA, so they take this path and can never accuse a timezone.
    """
    if ra_hr is None or hour_angle_hr is None:
        return None
    lst = (ra_hr + hour_angle_hr) % 24.0
    return wrap12(lst - gmst_hours(instant))


def implied_longitude_deg(
    ra_hr: float | None, hour_angle_hr: float | None, instant: datetime
) -> float | None:
    """`implied_longitude_hours` in degrees east, for display and storage."""
    hours = implied_longitude_hours(ra_hr, hour_angle_hr, instant)
    return None if hours is None else hours * 15.0


def offset_error_hours(
    implied_lon_hours: float | None, configured_longitude_deg: float | None
) -> float | None:
    """Hours by which the configured setup runs ahead of the pointing.

    Positive means the configured timezone is ahead of the truth: a rig really
    on UTC-4 but labelled UTC+1 returns about +5. Pinned by test, not read off
    the algebra.
    """
    if implied_lon_hours is None or configured_longitude_deg is None:
        return None
    return wrap12(implied_lon_hours - configured_longitude_deg / 15.0)


def predicted_altitude_deg(
    dec_deg: float | None, hour_angle_hr: float | None, latitude_deg: float | None
) -> float | None:
    """Altitude the standard pointing triangle predicts, in degrees.

    `sin(alt) = sin(lat) sin(dec) + cos(lat) cos(dec) cos(HA)`.
    """
    if dec_deg is None or hour_angle_hr is None or latitude_deg is None:
        return None
    lat = math.radians(latitude_deg)
    dec = math.radians(dec_deg)
    ha = math.radians(hour_angle_hr * 15.0)
    sin_alt = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * math.cos(ha)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def pointing_is_coherent(
    alt_deg: float | None,
    dec_deg: float | None,
    hour_angle_hr: float | None,
    latitude_deg: float | None,
    tolerance_deg: float = POINTING_MAX_ALT_RESIDUAL_DEG,
) -> bool | None:
    """Does the mount's own pointing agree with the configured latitude?

    The gate on every sidereal verdict. Uses the forward altitude form rather
    than `latitude_from_pointing` because inverting the triangle admits two
    solutions and degenerates where it constrains nothing, whereas the forward
    residual is single-valued everywhere.

    Returns None when any input is missing, which the caller must treat as
    "cannot check", not as "coherent".
    """
    predicted = predicted_altitude_deg(dec_deg, hour_angle_hr, latitude_deg)
    if predicted is None or alt_deg is None:
        return None
    return abs(alt_deg - predicted) <= tolerance_deg


def latitude_from_pointing(
    alt_deg: float | None, dec_deg: float | None, hour_angle_hr: float | None
) -> list[float] | None:
    """Latitudes consistent with one pointing block, ascending.

    Solves `sin(alt) = A sin(lat) + B cos(lat)` with `A = sin(dec)` and
    `B = cos(dec) cos(HA)`, which is `R sin(lat + phi) = sin(alt)`. Diagnostic
    only: the gate uses `pointing_is_coherent`.

    Returns None when an input is missing. Returns an empty list when the
    geometry pins no latitude, which covers both the unreachable case (the
    reported altitude exceeds what any latitude allows) and the degenerate one
    (every latitude fits, as on the horizon at declination zero).
    """
    if alt_deg is None or dec_deg is None or hour_angle_hr is None:
        return None
    a = math.sin(math.radians(dec_deg))
    b = math.cos(math.radians(dec_deg)) * math.cos(math.radians(hour_angle_hr * 15.0))
    r = math.hypot(a, b)
    if r < 1e-12:
        return []
    ratio = math.sin(math.radians(alt_deg)) / r
    if abs(ratio) > 1.0:
        return []
    phi = math.degrees(math.atan2(b, a))
    principal = math.degrees(math.asin(ratio))
    candidates = []
    for solution in (principal - phi, 180.0 - principal - phi):
        folded = ((solution + 180.0) % 360.0) - 180.0
        if -90.0 - 1e-9 <= folded <= 90.0 + 1e-9:
            candidates.append(max(-90.0, min(90.0, folded)))
    unique: list[float] = []
    for value in sorted(candidates):
        if not unique or abs(value - unique[-1]) > 1e-9:
            unique.append(value)
    return unique


def zone_meridian_longitude_deg(tz_name: str | None, instant: datetime) -> float | None:
    """Standard meridian of `tz_name` at `instant`, in degrees east.

    The tier-2 stand-in for a real longitude: a zone offset of N hours has a
    standard meridian at N * 15 degrees. Daylight saving is included, because
    the offset that shifts the log timestamps is the one in force that night.

    Returns None for an empty or unloadable zone name. This reads only the
    local tzdata; it makes no network call.
    """
    if not tz_name:
        return None
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    offset = instant.astimezone(zone).utcoffset() or timedelta(0)
    return offset.total_seconds() / 3600.0 * 15.0


def _unwrap_around_first(samples: Sequence[float]) -> list[float]:
    """Lift circular hour values onto a line centred on the first sample.

    Without this a cluster straddling the +/-12 h seam, which a 12 h zone
    error produces, reads as maximal scatter and the spread guard silently
    suppresses a real finding.
    """
    reference = samples[0]
    return [reference + wrap12(value - reference) for value in samples]


def _interquartile_spread(samples: Sequence[float]) -> float:
    if len(samples) < 2:
        return 0.0
    q1, _, q3 = statistics.quantiles(samples, n=4, method="inclusive")
    return q3 - q1


def verdict(
    errors_hours: Sequence[float],
    *,
    tier: str = TIER_SITE_KNOWN,
    implied_longitudes_hours: Sequence[float] | None = None,
) -> SidVerdict | None:
    """One profile's verdict from its per-section offset errors.

    Returns None, meaning say nothing, whenever the evidence is thin: fewer
    than `MIN_SIDEREAL_SECTIONS` samples, an interquartile spread above
    `SIDEREAL_MAX_SPREAD_HOURS`, or a median inside the tier's tolerance.
    Silence is the correct output in all three cases; a confidently wrong
    accusation about the user's configuration is worse than no message.

    `implied_longitudes_hours`, when given, supplies the median longitude the
    pointing implies, which tier 2 quotes as a value to enter on the profile.
    """
    if tier not in _TOLERANCE_BY_TIER:
        raise ValueError(f"unknown sidereal tier: {tier!r}")
    tolerance = _TOLERANCE_BY_TIER[tier]

    samples = [value for value in errors_hours if value is not None]
    if len(samples) < MIN_SIDEREAL_SECTIONS:
        return None

    unwrapped = _unwrap_around_first(samples)
    if _interquartile_spread(unwrapped) > SIDEREAL_MAX_SPREAD_HOURS:
        return None

    median = wrap12(statistics.median(unwrapped))
    if abs(median) < tolerance:
        return None

    suggested = None
    if implied_longitudes_hours:
        usable = [value for value in implied_longitudes_hours if value is not None]
        if usable:
            suggested = wrap12(statistics.median(_unwrap_around_first(usable))) * 15.0

    return SidVerdict(
        median_error_hours=median,
        nearest_whole_hours=int(round(median)),
        sample_count=len(samples),
        tier=tier,
        tolerance_hours=tolerance,
        confident=tier == TIER_SITE_KNOWN,
        implied_longitude_deg=suggested,
    )
