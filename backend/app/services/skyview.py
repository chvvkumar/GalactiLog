"""SkyView service - fetch DSS reference thumbnails for targets."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from celery.exceptions import SoftTimeLimitExceeded

from app.services.upstream import describe_http_error, request_with_fallback

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

# Tried in order. No known mirror.
SKYVIEW_URLS = ["https://skyview.gsfc.nasa.gov/current/cgi/runquery.pl"]


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
        "Scaling": "Log",
        "Return": "JPEG",
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{target.id}.jpg"
    filepath = out / filename

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = request_with_fallback(
                client, "GET", SKYVIEW_URLS, service="SkyView", params=params,
            )
        filepath.write_bytes(resp.content)
        return filename
    except SoftTimeLimitExceeded:
        # The Celery soft-limit signal can land while blocked in the HTTP call.
        # It must propagate to generate_reference_thumbnails so the task writes
        # its terminal "complete" state instead of being swallowed here as a
        # fetch failure and later dying at the hard limit (AUD-003).
        raise
    except Exception as exc:
        # An exhausted request_with_fallback already carries a readable
        # "SkyView is unavailable: <host> <reason>" message; anything else
        # (disk write, unexpected error) gets a short phrase.
        reason = str(exc) if isinstance(exc, httpx.HTTPError) else f"SkyView {describe_http_error(exc)}"
        logger.warning(
            "No SkyView thumbnail for target %s: %s", target.id, reason, exc_info=True,
        )
        return None
