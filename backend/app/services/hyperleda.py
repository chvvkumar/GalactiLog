"""HyperLEDA service - galaxy morphological type and inclination."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.hyperleda_cache import HyperLEDACache

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

# The old fG.cgi CSV endpoint is broken on the new HyperLEDA server
# (leda.univ-lyon1.fr now 302-redirects to atlas.obs-hp.fr/hyperleda, where
# the $objname virtual column and of=csv output are both non-functional).
# Use the ledacat.cgi endpoint which returns structured HTML with
# parameter/value table rows that can be reliably parsed.
HYPERLEDA_URL = "http://atlas.obs-hp.fr/hyperleda/ledacat.cgi"

_GALAXY_TYPES: frozenset[str] = frozenset({
    "G", "GiG", "GiC", "BiC", "Sy1", "Sy2", "LINER", "AGN",
    "rG", "HzG", "BClG", "GiP", "PaG", "SBG", "SyG", "Galaxy",
    "GGroup", "GPair", "GClstr",
})


def _is_galaxy_type(object_type: str | None) -> bool:
    """Return True if the object_type string contains a galaxy-class token."""
    if not object_type:
        return False
    tokens = re.split(r"[,\s|]+", object_type.strip())
    return any(t in _GALAXY_TYPES for t in tokens)


def _hyperleda_name(catalog_id: str) -> str:
    """Convert catalog_id to HyperLEDA format: lowercase, no spaces."""
    return catalog_id.lower().replace(" ", "")


def _extract_param_value(html: str, param_name: str) -> float | None:
    """Extract a numeric parameter value from HyperLEDA ledacat.cgi HTML.

    The HTML contains table rows like:
      <td><a href="leda/param/t.html" ...>t</a></td><td>  4.0 &#177; 0.2</td>
    This extracts the first number from the value cell.
    """
    # Match: >param_name</a></td><td>VALUE</td>
    pattern = rf">{re.escape(param_name)}</a></td><td>([^<]*)</td>"
    match = re.search(pattern, html)
    if not match:
        return None
    raw_value = match.group(1).strip()
    if not raw_value:
        return None
    # Value may include "+/- error" (as "&#177;" or literal +/-).
    # Take just the first number token.
    num_match = re.match(r"([+-]?\s*\d+\.?\d*)", raw_value)
    if not num_match:
        return None
    try:
        return float(num_match.group(1).replace(" ", ""))
    except ValueError:
        return None


def query_hyperleda(catalog_id: str) -> dict[str, Any] | None:
    """Query HyperLEDA for morphological type and inclination.

    Returns {"t_type": float|None, "inclination": float|None} or None on error.
    Uses the ledacat.cgi endpoint which returns structured HTML with
    parameter/value pairs.
    """
    name = _hyperleda_name(catalog_id)

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(HYPERLEDA_URL, params={"o": name})
            resp.raise_for_status()

        html = resp.text

        # Check for "no record" response
        if "returns no record" in html:
            logger.debug("HyperLEDA returned no data for '%s'", catalog_id)
            return None

        t_type = _extract_param_value(html, "t")
        inclination = _extract_param_value(html, "incl")

        if t_type is None and inclination is None:
            logger.debug("HyperLEDA returned no t/incl for '%s'", catalog_id)
            return None

        return {
            "t_type": t_type,
            "inclination": inclination,
        }

    except (httpx.HTTPError, ValueError, IndexError) as e:
        logger.warning("HyperLEDA query failed for '%s': %s", catalog_id, e)
        return None


def get_cached_hyperleda(catalog_id: str, session: Session) -> HyperLEDACache | None:
    """Check the HyperLEDA cache for a previous lookup."""
    return session.execute(
        select(HyperLEDACache).where(HyperLEDACache.catalog_id == catalog_id)
    ).scalar_one_or_none()


def save_hyperleda_cache(
    session: Session, catalog_id: str, data: dict[str, Any] | None,
) -> None:
    """Save a HyperLEDA lookup result (including negative) to the cache."""
    entry = {
        "catalog_id": catalog_id,
        "t_type": data.get("t_type") if data else None,
        "inclination": data.get("inclination") if data else None,
    }
    stmt = pg_insert(HyperLEDACache).values(**entry).on_conflict_do_update(
        index_elements=["catalog_id"],
        set_=entry,
    )
    session.execute(stmt)


def enrich_target_from_hyperleda(session: Session, target: "Target") -> bool:
    """Enrich a target with HyperLEDA morphological type and inclination.

    Only queries for galaxy-type targets. Checks cache first, queries if
    needed. HTTP call is made outside any open transaction to avoid holding
    DB connections during network I/O.

    Returns True if any fields were updated.
    """
    if not _is_galaxy_type(target.object_type):
        return False

    if not target.catalog_id:
        return False

    # Check cache
    cached = get_cached_hyperleda(target.catalog_id, session)
    if cached is not None:
        if cached.t_type is None and cached.inclination is None:
            return False
        updated = False
        if cached.t_type is not None and target.hubble_t_type is None:
            target.hubble_t_type = cached.t_type
            updated = True
        if cached.inclination is not None and target.inclination is None:
            target.inclination = cached.inclination
            updated = True
        return updated

    # Query HyperLEDA
    data = query_hyperleda(target.catalog_id)

    # Cache the result (even if None - negative cache)
    save_hyperleda_cache(session, target.catalog_id, data)
    session.commit()

    if data is None:
        return False

    # Apply enrichment (non-destructive)
    updated = False
    if data.get("t_type") is not None and target.hubble_t_type is None:
        target.hubble_t_type = data["t_type"]
        updated = True
    if data.get("inclination") is not None and target.inclination is None:
        target.inclination = data["inclination"]
        updated = True

    return updated
