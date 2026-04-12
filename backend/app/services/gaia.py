"""Gaia DR3 service - star cluster distances via median member parallax."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.gaia_cache import GaiaCache

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap/sync"

_CLUSTER_CODES: frozenset[str] = frozenset({
    "OpC", "GlC", "Cl*", "As*", "OCl", "GCl", "C*G",
    "Open Cluster", "Globular Cluster", "Star Cluster",
})


def _is_cluster_type(object_type: str | None) -> bool:
    """Return True if object_type contains a cluster-related SIMBAD code."""
    if not object_type:
        return False
    import re
    tokens = re.split(r"[,\s|]+", object_type)
    return any(t in _CLUSTER_CODES for t in tokens)


def _compute_cone_radius(target: Target) -> float:
    """Return cone search radius in degrees for a cluster target."""
    if target.size_major is not None:
        radius = target.size_major / 60.0 * 0.5
        return max(radius, 0.1)
    return 0.15


def query_cluster_distance(
    ra: float, dec: float, radius_deg: float,
) -> tuple[float, int] | None:
    """Query Gaia DR3 TAP for median parallax within a cone and compute distance.

    Returns (distance_pc, star_count) or None if insufficient data or error.
    """
    adql = (
        "SELECT COUNT(parallax) AS n, "
        "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY parallax) AS med_parallax "
        "FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) "
        "AND parallax > 0 AND parallax_over_error > 5"
    )

    try:
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

        headers = [h.strip() for h in lines[0].split(",")]
        values = [v.strip() for v in lines[1].split(",")]
        row = dict(zip(headers, values))

        n = int(row["n"])
        if n < 5:
            return None

        med_parallax = float(row["med_parallax"])
        if med_parallax <= 0:
            return None

        distance_pc = 1000.0 / med_parallax
        if distance_pc <= 0 or distance_pc > 100000:
            return None

        return (distance_pc, n)

    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        logger.warning("Gaia DR3 query failed (ra=%.4f, dec=%.4f): %s", ra, dec, e)
        return None


def get_cached_gaia(target_id, session: Session) -> GaiaCache | None:
    """Check the Gaia cache for a previous lookup."""
    return session.execute(
        select(GaiaCache).where(GaiaCache.target_id == target_id)
    ).scalar_one_or_none()


def save_gaia_cache(
    session: Session, target_id, distance_pc: float | None, parallax_count: int | None,
) -> None:
    """Upsert a Gaia lookup result to the cache."""
    entry = {
        "target_id": target_id,
        "distance_pc": distance_pc,
        "parallax_count": parallax_count,
    }
    stmt = pg_insert(GaiaCache).values(**entry).on_conflict_do_update(
        index_elements=["target_id"],
        set_=entry,
    )
    session.execute(stmt)


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

    # Query Gaia (HTTP call outside transaction)
    radius = _compute_cone_radius(target)
    result = query_cluster_distance(target.ra, target.dec, radius)

    distance_pc = result[0] if result else None
    parallax_count = result[1] if result else None

    # Cache the result (even negative)
    save_gaia_cache(session, target.id, distance_pc, parallax_count)
    session.commit()

    if distance_pc is not None and target.distance_pc is None:
        target.distance_pc = distance_pc
        return True

    return False
