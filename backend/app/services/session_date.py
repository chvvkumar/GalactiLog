"""Session date computation for imaging night grouping.

When 'imaging night' mode is enabled, sessions are grouped by local solar noon
rather than UTC midnight. This keeps nighttime imaging runs that cross midnight
together as a single session.

The local solar noon for a given longitude is approximately:
    solar_noon_utc = 12:00 - (longitude / 15) hours

Subtracting this offset from the UTC capture time and taking .date() yields
the session date: frames captured between one solar noon and the next all
share the same session date.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


_LONGITUDE_KEYS = ("SITELONG", "OBSLONG", "LONG-OBS")


def compute_session_date(
    capture_date: datetime | None,
    *,
    use_imaging_night: bool = False,
    longitude: float | None = None,
) -> date | None:
    if capture_date is None:
        return None
    if not use_imaging_night or longitude is None:
        return capture_date.date()
    offset_hours = 12.0 - longitude / 15.0
    shifted = capture_date - timedelta(hours=offset_hours)
    return shifted.date()


def extract_longitude(raw_headers: dict | None) -> float | None:
    if not raw_headers:
        return None
    for key in _LONGITUDE_KEYS:
        val = raw_headers.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None
