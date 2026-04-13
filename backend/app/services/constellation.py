"""Constellation lookup from J2000 equatorial coordinates using astropy."""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


def coords_to_constellation(ra_deg: float | None, dec_deg: float | None) -> str | None:
    """Return IAU constellation abbreviation for given J2000 RA/Dec in degrees.

    Returns a 3-letter abbreviation (e.g. 'Ori', 'Cyg') or None if
    coordinates are missing or lookup fails.
    """
    if ra_deg is None or dec_deg is None:
        return None

    try:
        from astropy.coordinates import SkyCoord
        import astropy.units as u

        coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs")
        return coord.get_constellation(short_name=True)
    except Exception as e:
        logger.debug("Constellation lookup failed for RA=%.4f Dec=%.4f: %s", ra_deg, dec_deg, e)
        return None
