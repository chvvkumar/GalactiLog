"""USNO Astronomical Applications API - night ephemeris for imaging planning."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USNO_BASE_URL = "https://aa.usno.navy.mil/api"


def _empty_result(date_iso: str) -> dict[str, Any]:
    return {
        "date": date_iso,
        "astro_dusk": None,
        "astro_dawn": None,
        "moon_phase": None,
        "moon_illumination": None,
        "moon_rise": None,
        "moon_set": None,
        "source_available": False,
    }


def _parse_time_to_iso(date_iso: str, time_str: str) -> str:
    """Convert a USNO time string like '05:23' on a given date to ISO 8601 UTC."""
    try:
        dt = datetime.strptime(f"{date_iso} {time_str}", "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return time_str


def get_night_ephemeris(date_iso: str, lat: float, lon: float) -> dict[str, Any]:
    """Fetch twilight times and moon data from the USNO API.

    Returns a dict with astro_dusk, astro_dawn, moon phase/illumination,
    and moon rise/set times. On any error, returns source_available=False
    with all fields set to None.
    """
    result = _empty_result(date_iso)

    try:
        with httpx.Client(timeout=10.0) as client:
            # --- Twilight / rise-set data ---
            rstt_resp = client.get(
                f"{USNO_BASE_URL}/rstt/oneday",
                params={"date": date_iso, "coords": f"{lat},{lon}", "tz": "0"},
            )
            rstt_resp.raise_for_status()
            rstt = rstt_resp.json()

            props = rstt.get("properties", {}).get("data", {})

            # Sun data - extract astronomical twilight
            for entry in props.get("sundata", []):
                phen = entry.get("phen", "")
                time_val = entry.get("time", "")
                if phen == "BC" or phen == "Begin Civil Twilight":
                    pass  # not needed
                if "Set" in phen or phen == "S":
                    pass  # sunset, not needed directly
                # Astronomical twilight markers vary; USNO uses short codes
                # EC = End Civil Twilight, EN = End Nautical Twilight
                # EA = End Astronomical Twilight (dusk)
                # BA = Begin Astronomical Twilight (dawn)
                if phen in ("End Astronomical Twilight", "EA"):
                    result["astro_dusk"] = _parse_time_to_iso(date_iso, time_val)
                elif phen in ("Begin Astronomical Twilight", "BA"):
                    result["astro_dawn"] = _parse_time_to_iso(date_iso, time_val)

            # Moon data - rise/set from the same endpoint
            for entry in props.get("moondata", []):
                phen = entry.get("phen", "")
                time_val = entry.get("time", "")
                if phen in ("Rise", "R"):
                    result["moon_rise"] = _parse_time_to_iso(date_iso, time_val)
                elif phen in ("Set", "S"):
                    result["moon_set"] = _parse_time_to_iso(date_iso, time_val)

            # Closest moon phase fraction from the same response
            closest_phase = props.get("closestphase", {})
            if closest_phase:
                result["moon_phase"] = closest_phase.get("phase")

            # Current moon fraction (curphase) if available
            cur = props.get("curphase")
            if cur is not None:
                # curphase is a percentage string like "45.6%"
                try:
                    frac_str = str(cur).replace("%", "").strip()
                    result["moon_illumination"] = round(float(frac_str) / 100.0, 4)
                except (ValueError, TypeError):
                    pass

            # --- Moon phase from dedicated endpoint as fallback ---
            if result["moon_phase"] is None or result["moon_illumination"] is None:
                try:
                    phase_resp = client.get(
                        f"{USNO_BASE_URL}/moon/phases/date",
                        params={"date": date_iso, "nump": "1"},
                    )
                    phase_resp.raise_for_status()
                    phase_data = phase_resp.json()
                    phases = phase_data.get("phasedata", [])
                    if phases:
                        if result["moon_phase"] is None:
                            result["moon_phase"] = phases[0].get("phase")
                except Exception:
                    logger.debug("Moon phase fallback request failed", exc_info=True)

            result["source_available"] = True

    except Exception:
        logger.warning("USNO API request failed for %s (%.4f, %.4f)", date_iso, lat, lon, exc_info=True)
        return _empty_result(date_iso)

    return result
