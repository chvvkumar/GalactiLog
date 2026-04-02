"""Calculate astronomical dark hours using astropy solar position.

Astronomical night = sun below -18 degrees altitude.
Samples sun altitude every 10 minutes across the night window (local noon to next noon)
and sums intervals where sun is below -18 degrees.
"""
from datetime import date, timedelta
from functools import lru_cache
import calendar

import numpy as np
from astropy.coordinates import EarthLocation, AltAz, get_sun
from astropy.time import Time
import astropy.units as u

# Sample every 10 minutes across 24h = 144 points
_SAMPLES_PER_DAY = 144
_SAMPLE_INTERVAL_HOURS = 24.0 / _SAMPLES_PER_DAY
_ASTRO_TWILIGHT_DEG = -18.0


def dark_hours_for_night(d: date, lat: float, lon: float) -> float:
    """Return hours of astronomical darkness for the night starting on date `d`.

    Computes sun altitude at 10-minute intervals from local noon on `d`
    to local noon on `d+1`, counting intervals where altitude < -18 degrees.
    """
    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)

    # Start at noon UTC on the given date (close enough — error < 1 sample interval)
    start = Time(f"{d.isoformat()}T12:00:00", scale="utc")
    offsets = np.arange(_SAMPLES_PER_DAY) * _SAMPLE_INTERVAL_HOURS / 24.0  # in days
    times = start + offsets * u.day

    altaz = AltAz(obstime=times, location=location)
    sun_alt = get_sun(times).transform_to(altaz).alt.deg

    dark_count = np.sum(sun_alt < _ASTRO_TWILIGHT_DEG)
    return float(dark_count * _SAMPLE_INTERVAL_HOURS)


@lru_cache(maxsize=512)
def dark_hours_for_month(year: int, month: int, lat: float, lon: float) -> float:
    """Return total astronomical dark hours for all nights in a given month."""
    days_in_month = calendar.monthrange(year, month)[1]
    total = 0.0
    for day in range(1, days_in_month + 1):
        total += dark_hours_for_night(date(year, month, day), lat, lon)
    return round(total, 1)


@lru_cache(maxsize=2048)
def dark_hours_for_week(year: int, week: int, lat: float, lon: float) -> float:
    """Return total astronomical dark hours for an ISO week."""
    # Monday of the ISO week
    jan4 = date(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.weekday())
    monday = start_of_week1 + timedelta(weeks=week - 1)
    total = 0.0
    for i in range(7):
        total += dark_hours_for_night(monday + timedelta(days=i), lat, lon)
    return round(total, 1)
