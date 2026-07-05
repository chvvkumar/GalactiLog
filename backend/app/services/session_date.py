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

import logging
from datetime import date, datetime, timedelta


logger = logging.getLogger(__name__)

_LONGITUDE_KEYS = ("SITELONG", "OBSLONG", "LONG-OBS")


def warn_imaging_night_fallback(logger_: logging.Logger | None = None) -> None:
    """Emit the AUD-021 imaging-night fallback warning.

    compute_session_date itself stays silent because it runs once per image;
    callers (per-image ingest, full-catalog recompute) must call this exactly
    once per scan/recompute run when they first observe the fallback
    condition (use_imaging_night enabled but no longitude resolvable), so a
    large catalog does not flood the log/app_logs sink with one warning per
    frame.
    """
    (logger_ or logger).warning(
        "use_imaging_night is enabled but no longitude is resolvable "
        "(no SITELONG/OBSLONG/LONG-OBS header and no observer_longitude "
        "configured); falling back to UTC-midnight session date grouping. "
        "Set observer_longitude in Settings for imaging-night grouping to "
        "take effect."
    )


def compute_session_date(
    capture_date: datetime | None,
    *,
    use_imaging_night: bool = False,
    longitude: float | None = None,
) -> date | None:
    if capture_date is None:
        return None
    if not use_imaging_night or longitude is None:
        # When use_imaging_night is True but longitude is None this is the
        # silent UTC-midnight fallback (AUD-021). No warning here: this
        # function runs per image, so callers rate-limit via
        # warn_imaging_night_fallback (once per scan/recompute run).
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
