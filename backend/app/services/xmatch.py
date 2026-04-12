"""CDS xMatch service - bulk cross-match targets against VizieR catalogs."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

XMATCH_URL = "http://cdsxmatch.u-strasbg.fr/xmatch/api/v1/sync"


def build_target_csv(targets: list[dict]) -> str:
    """Build a CSV string with columns id, ra, dec from target dicts."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "ra", "dec"])
    for t in targets:
        writer.writerow([t["id"], t["ra"], t["dec"]])
    return buf.getvalue()


def bulk_xmatch_targets(
    targets: list[dict],
    vizier_catalog: str,
    radius_arcsec: float = 60.0,
) -> dict[str, dict[str, Any]]:
    """Cross-match a list of targets against a VizieR catalog via CDS xMatch.

    Parameters
    ----------
    targets : list[dict]
        Each dict must contain keys ``id``, ``ra``, ``dec``.
    vizier_catalog : str
        VizieR catalog identifier (e.g. ``"VII/118/ngc2000"``).
    radius_arcsec : float
        Maximum match distance in arcseconds (default 60).

    Returns
    -------
    dict[str, dict[str, Any]]
        Mapping of target id to the matched catalog row columns.
        Empty dict on error.
    """
    if not targets:
        return {}

    target_csv = build_target_csv(targets)

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                XMATCH_URL,
                data={
                    "request": "xmatch",
                    "distMaxArcsec": str(radius_arcsec),
                    "RESPONSEFORMAT": "csv",
                    "colRA1": "ra",
                    "colDec1": "dec",
                    "cat2": f"vizier:{vizier_catalog}",
                },
                files={
                    "cat1": ("targets.csv", target_csv, "text/csv"),
                },
            )
            resp.raise_for_status()
    except Exception:
        logger.warning("CDS xMatch request failed", exc_info=True)
        return {}

    try:
        reader = csv.DictReader(io.StringIO(resp.text))
        results: dict[str, dict[str, Any]] = {}
        for row in reader:
            tid = row.get("id")
            if tid is not None:
                results[tid] = dict(row)
        return results
    except Exception:
        logger.warning("Failed to parse xMatch response", exc_info=True)
        return {}
