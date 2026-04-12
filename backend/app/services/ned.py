"""NED (NASA Extragalactic Database) service - TAP queries for galaxy enrichment."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ned_cache import NEDCache

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

NED_TAP_URL = "https://ned.ipac.caltech.edu/tap/sync"

_GALAXY_TYPES: frozenset[str] = frozenset({
    "G", "GiG", "GiC", "BiC", "Sy1", "Sy2", "LINER", "AGN",
    "rG", "HzG", "BClG", "GiP", "PaG", "SBG", "SyG", "Galaxy",
    "GGroup", "GPair", "GClstr",
})

_SPLIT_RE = re.compile(r"[,\s|]+")


def _is_galaxy_type(object_type: str | None) -> bool:
    """Return True if the target's object_type contains any galaxy-related SIMBAD code."""
    if not object_type:
        return False
    tokens = _SPLIT_RE.split(object_type.strip())
    return any(t in _GALAXY_TYPES for t in tokens if t)


def query_ned(object_name: str) -> dict[str, Any] | None:
    """Query NED TAP for galaxy data. Returns dict with morphology/redshift/distance/activity, or None."""
    adql = (
        f"SELECT prefname, morph_type, z, dist, acttype "
        f"FROM NEDTAP.objdir WHERE prefname = '{object_name}'"
    )

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                NED_TAP_URL,
                data={
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": "tsv",
                    "QUERY": adql,
                },
            )
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()

            if len(lines) < 2:
                return None

            headers = [h.strip() for h in lines[0].split("\t")]
            values = [v.strip().strip('"') for v in lines[1].split("\t")]

            if len(values) < len(headers):
                return None

            row = dict(zip(headers, values))

            def _float(key: str) -> float | None:
                val = row.get(key, "").strip()
                if not val:
                    return None
                try:
                    return float(val)
                except ValueError:
                    return None

            def _str(key: str) -> str | None:
                val = row.get(key, "").strip()
                return val if val else None

            return {
                "ned_morphology": _str("morph_type"),
                "redshift": _float("z"),
                "distance_mpc": _float("dist"),
                "activity_type": _str("acttype"),
            }

    except (httpx.HTTPError, ValueError, IndexError) as e:
        logger.warning("NED query failed for '%s': %s", object_name, e)
        return None


def get_cached_ned(catalog_id: str, session: Session) -> dict | None:
    """Check the NED cache for a previous lookup. Returns dict of fields or None."""
    cached = session.execute(
        select(NEDCache).where(NEDCache.catalog_id == catalog_id)
    ).scalar_one_or_none()

    if cached is None:
        return None

    return {
        "ned_morphology": cached.ned_morphology,
        "redshift": cached.redshift,
        "distance_mpc": cached.distance_mpc,
        "activity_type": cached.activity_type,
    }


def save_ned_cache(session: Session, catalog_id: str, data: dict | None) -> None:
    """Save a NED lookup result (including negative) to the cache."""
    entry = {
        "catalog_id": catalog_id,
        "ned_morphology": data.get("ned_morphology") if data else None,
        "redshift": data.get("redshift") if data else None,
        "distance_mpc": data.get("distance_mpc") if data else None,
        "activity_type": data.get("activity_type") if data else None,
    }
    stmt = pg_insert(NEDCache).values(**entry).on_conflict_do_update(
        index_elements=["catalog_id"],
        set_=entry,
    )
    session.execute(stmt)


def enrich_target_from_ned(session: Session, target: "Target") -> bool:
    """Enrich a target from NED. Checks cache first, queries if needed.

    HTTP call is made outside any open transaction to avoid holding DB
    connections during network I/O.

    Returns True if any fields were updated.
    """
    if not _is_galaxy_type(target.object_type):
        return False

    if not target.catalog_id:
        return False

    # Check cache first
    cached = get_cached_ned(target.catalog_id, session)
    if cached is not None:
        # Cached (positive or negative) - apply if positive
        if all(v is None for v in cached.values()):
            return False
        updated = False
        if cached["ned_morphology"] is not None and target.ned_morphology is None:
            target.ned_morphology = cached["ned_morphology"]
            updated = True
        if cached["redshift"] is not None and target.redshift is None:
            target.redshift = cached["redshift"]
            updated = True
        if cached["distance_mpc"] is not None and target.distance_mpc is None:
            target.distance_mpc = cached["distance_mpc"]
            updated = True
        if cached["activity_type"] is not None and target.activity_type is None:
            target.activity_type = cached["activity_type"]
            updated = True
        return updated

    # Query NED (HTTP call - outside transaction)
    data = query_ned(target.catalog_id)

    # Cache the result (even if None - negative cache)
    save_ned_cache(session, target.catalog_id, data)
    session.commit()

    if data is None:
        return False

    # Apply enrichment (non-destructive)
    updated = False
    if data.get("ned_morphology") is not None and target.ned_morphology is None:
        target.ned_morphology = data["ned_morphology"]
        updated = True
    if data.get("redshift") is not None and target.redshift is None:
        target.redshift = data["redshift"]
        updated = True
    if data.get("distance_mpc") is not None and target.distance_mpc is None:
        target.distance_mpc = data["distance_mpc"]
        updated = True
    if data.get("activity_type") is not None and target.activity_type is None:
        target.activity_type = data["activity_type"]
        updated = True

    return updated
