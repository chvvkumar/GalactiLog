"""Gaia DR3 service - star cluster distances via median member parallax."""
from __future__ import annotations

import logging
from collections import namedtuple
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

from app.services import catalog_cache as cc

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

# Minimal wrapper for cached payload to maintain attribute access compatibility
_CachedPayload = namedtuple("_CachedPayload", ["distance_pc"])

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"

_CLUSTER_CODES: frozenset[str] = frozenset({
    "OpC", "GlC", "Cl*", "As*", "OCl", "GCl", "C*G",
    "Open Cluster", "Globular Cluster", "Star Cluster",
})


def _is_cluster_type(object_type: str | None) -> bool:
    """Return True if object_type contains a cluster-related SIMBAD code.

    Checks single-word codes (e.g. OpC, GlC) by tokenising on delimiters,
    and multi-word descriptors (e.g. "Open Cluster") by substring search.
    """
    if not object_type:
        return False
    import re
    tokens = re.split(r"[,\s|]+", object_type)
    _single_codes = {c for c in _CLUSTER_CODES if " " not in c}
    _multi_codes = {c for c in _CLUSTER_CODES if " " in c}
    if any(t in _single_codes for t in tokens):
        return True
    normalized = object_type.lower()
    return any(c.lower() in normalized for c in _multi_codes)


def _compute_cone_radius(target: Target) -> float:
    """Return cone search radius in degrees for a cluster target."""
    if target.size_major is not None:
        radius = target.size_major / 60.0 * 0.5
        return max(radius, 0.1)
    return 0.15


def _median(values: list[float]) -> float:
    """Return the median of a sorted list of floats."""
    values.sort()
    n = len(values)
    mid = n // 2
    if n % 2 == 0:
        return (values[mid - 1] + values[mid]) / 2.0
    return values[mid]


def query_cluster_distance(
    ra: float, dec: float, radius_deg: float,
) -> tuple[float, int] | None:
    """Query Gaia DR3 TAP for median parallax within a cone and compute distance.

    Fetches individual parallax values and computes the median client-side,
    because the Gaia TAP server does not support PERCENTILE_CONT or MEDIAN
    aggregate functions in ADQL.

    Returns (distance_pc, star_count) or None if insufficient data. Raises
    httpx.HTTPError on network/HTTP failures so the wrapper can retry.
    """
    adql = (
        "SELECT parallax "
        "FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) "
        "AND parallax > 0 AND parallax_over_error > 5"
    )

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            GAIA_TAP_URL,
            data={
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "csv",
                "QUERY": adql,
            },
        )
        resp.raise_for_status()

    lines = resp.text.strip().splitlines()
    if len(lines) < 2:
        return None

    # Parse parallax values (skip header row)
    parallaxes = []
    for line in lines[1:]:
        val = line.strip()
        if val:
            parallaxes.append(float(val))

    n = len(parallaxes)
    if n < 5:
        return None

    med_parallax = _median(parallaxes)
    if med_parallax <= 0:
        return None

    distance_pc = 1000.0 / med_parallax
    if distance_pc <= 0 or distance_pc > 100000:
        return None

    return (distance_pc, n)


def get_cached_gaia(target_id: Any, session: Session) -> _CachedPayload | None:
    """Check the Gaia cache for a previous lookup.

    Returns a minimal object with .distance_pc attribute:
    - None if not cached (cache miss).
    - _CachedPayload(distance_pc=None) if negatively cached (queried but no result).
    - _CachedPayload(distance_pc=<value>) if positively cached.

    Wraps catalog_cache.get_cached for the generic wrapper.
    """
    cached = cc.get_cached(session, "gaia", str(target_id))
    if cached is None:
        return None
    if cached is cc.NEGATIVE:
        # Negative cache: distance_pc is None, but we have a cached entry
        return _CachedPayload(distance_pc=None)
    # Positive cache: return the cached payload
    return _CachedPayload(distance_pc=cached.get("distance_pc"))


def save_gaia_cache(
    session: Session, target_id: Any, distance_pc: float | None, parallax_count: int | None,
) -> None:
    """Upsert a Gaia lookup result to the cache.

    Keeps the same call shape (two positional distance/parallax args) for
    compatibility with existing callers. Wraps catalog_cache.save_cached.
    """
    payload = None if distance_pc is None else {
        "distance_pc": distance_pc,
        "parallax_count": parallax_count,
    }
    cc.save_cached(session, "gaia", str(target_id), payload)


def enrich_target_from_gaia(session: Session, target: Target) -> bool:
    """Enrich a cluster target with Gaia DR3 distance. Checks cache first.

    Returns True if target.distance_pc was updated.
    """
    if not _is_cluster_type(target.object_type):
        return False

    if target.ra is None or target.dec is None:
        return False

    # Check cache
    cached = get_cached_gaia(target.id, session)
    if cached is not None:
        if cached.distance_pc is not None and target.distance_pc is None:
            target.distance_pc = cached.distance_pc
            return True
        return False

    # Query Gaia (HTTP call outside transaction). Use the wrapper's get_or_fetch
    # which handles retry, backoff, and caching. Negative results (None) are
    # cached automatically, suppressing refetch.
    radius = _compute_cone_radius(target)

    def fetch() -> dict[str, Any] | None:
        result = query_cluster_distance(target.ra, target.dec, radius)
        if result is None:
            return None
        distance_pc, parallax_count = result
        return {"distance_pc": distance_pc, "parallax_count": parallax_count}

    payload = cc.get_or_fetch(session, "gaia", str(target.id), fetch)
    session.commit()

    if payload is not None and target.distance_pc is None:
        target.distance_pc = payload["distance_pc"]
        return True

    return False
