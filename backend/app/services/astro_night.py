"""Calculate astronomical dark hours using astropy solar position.

Astronomical night = sun below -18 degrees altitude.
Samples sun altitude every 10 minutes across the night window (local noon to next noon)
and sums intervals where sun is below -18 degrees.

Uses vectorized batch computation to avoid per-day overhead.
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
    """Return hours of astronomical darkness for a single night.

    For bulk computation, use dark_hours_batch() instead.
    """
    result = dark_hours_batch([d], lat, lon)
    return result[0]


def dark_hours_batch(dates: list[date], lat: float, lon: float) -> list[float]:
    """Compute dark hours for multiple nights in one vectorized astropy call.

    This is much faster than calling dark_hours_for_night() in a loop
    because astropy's coordinate transforms are vectorized over time arrays.
    """
    if not dates:
        return []

    location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=0 * u.m)
    n_days = len(dates)

    # Build a single time array: for each date, 144 samples starting at noon UTC
    offsets = np.arange(_SAMPLES_PER_DAY) * _SAMPLE_INTERVAL_HOURS / 24.0  # in days
    all_times = []
    for d in dates:
        start = Time(f"{d.isoformat()}T12:00:00", scale="utc")
        all_times.append(start + offsets * u.day)

    # Stack into one big Time array for a single vectorized transform
    combined = all_times[0]
    for t in all_times[1:]:
        combined = Time(np.concatenate([combined.jd, t.jd]), format="jd", scale="utc")

    altaz = AltAz(obstime=combined, location=location)
    sun_alt = get_sun(combined).transform_to(altaz).alt.deg

    # Split back into per-day chunks and count dark samples
    results = []
    for i in range(n_days):
        chunk = sun_alt[i * _SAMPLES_PER_DAY : (i + 1) * _SAMPLES_PER_DAY]
        dark_count = np.sum(chunk < _ASTRO_TWILIGHT_DEG)
        results.append(float(dark_count * _SAMPLE_INTERVAL_HOURS))

    return results


@lru_cache(maxsize=512)
def dark_hours_for_month(year: int, month: int, lat: float, lon: float) -> float:
    """Return total astronomical dark hours for all nights in a given month."""
    days_in_month = calendar.monthrange(year, month)[1]
    dates = [date(year, month, d) for d in range(1, days_in_month + 1)]
    return round(sum(dark_hours_batch(dates, lat, lon)), 1)


@lru_cache(maxsize=2048)
def dark_hours_for_week(year: int, week: int, lat: float, lon: float) -> float:
    """Return total astronomical dark hours for an ISO week."""
    jan4 = date(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.weekday())
    monday = start_of_week1 + timedelta(weeks=week - 1)
    dates = [monday + timedelta(days=i) for i in range(7)]
    return round(sum(dark_hours_batch(dates, lat, lon)), 1)
