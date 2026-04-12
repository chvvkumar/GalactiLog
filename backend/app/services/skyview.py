"""SkyView service - fetch DSS reference thumbnails for targets."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

SKYVIEW_URL = "https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl"


def _compute_fov(target: Target) -> float:
    """Calculate FOV in degrees from target size_major.

    Returns target.size_major * 1.5 / 60, clamped to [0.1, 5.0].
    Defaults to 0.5 if size_major is None.
    """
    if target.size_major is None:
        return 0.5
    fov = target.size_major * 1.5 / 60.0
    return max(0.1, min(5.0, fov))


def fetch_reference_thumbnail(
    target: Target, output_dir: str | Path
) -> str | None:
    """Fetch a DSS2 Red reference thumbnail from SkyView.

    Returns the relative filename '{target.id}.jpg' on success, None on failure.
    """
    if target.ra is None or target.dec is None:
        return None

    fov = _compute_fov(target)
    params = {
        "Survey": "DSS2 Red",
        "Position": f"{target.ra},{target.dec}",
        "Size": str(fov),
        "Pixels": "512",
        "Return": "JPEG",
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{target.id}.jpg"
    filepath = out / filename

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(SKYVIEW_URL, params=params)
            resp.raise_for_status()
        filepath.write_bytes(resp.content)
        return filename
    except Exception:
        logger.warning("Failed to fetch SkyView thumbnail for target %s", target.id, exc_info=True)
        return None
