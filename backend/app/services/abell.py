"""Abell catalog service - load CSV and match to targets."""
from __future__ import annotations

import csv
import logging
import math
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.abell_catalog import AbellEntry
from app.models.target import Target
from app.services.catalog_membership import upsert_membership

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "abell.csv"

# Object types considered cluster-like for coordinate matching
_CLUSTER_TYPES = {"ClG", "GrG", "CGG", "GClstr", "C*G"}

# Coordinate proximity threshold in degrees
_COORD_MATCH_DEG = 0.025


def _parse_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def _parse_int(val: str | None) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


def load_abell_csv(session: Session) -> int:
    """Load the bundled Abell CSV into the abell_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("Abell CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            abell_id = row.get("abell_id", "").strip()
            if not abell_id:
                continue

            entry = {
                "abell_id": abell_id,
                "ra": _parse_float(row.get("ra")),
                "dec": _parse_float(row.get("dec")),
                "richness_class": _parse_int(row.get("richness_class")),
                "distance_class": _parse_int(row.get("distance_class")),
                "bm_type": row.get("bm_type", "").strip() or None,
                "redshift": _parse_float(row.get("redshift")),
            }

            stmt = pg_insert(AbellEntry).values(**entry).on_conflict_do_update(
                index_elements=["abell_id"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d Abell entries", count)
    return count


def _build_abell_metadata(entry: AbellEntry) -> dict:
    """Build metadata dict for an Abell membership record."""
    parts = entry.abell_id.split()
    abell_number = None
    if len(parts) == 2:
        try:
            abell_number = int(parts[1])
        except ValueError:
            pass

    metadata = {
        "richness": entry.richness_class,
        "distance_class": entry.distance_class,
        "bm_type": entry.bm_type,
    }
    if abell_number is not None:
        metadata["abell_number"] = abell_number
    return metadata


def _coord_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Approximate angular distance in degrees between two sky positions."""
    cos_dec = math.cos(math.radians((dec1 + dec2) / 2))
    dra = (ra1 - ra2) * cos_dec
    ddec = dec1 - dec2
    return math.sqrt(dra * dra + ddec * ddec)


def match_abell_targets(session: Session) -> int:
    """Match Abell entries to existing targets using three-stage matching.

    Stage 1: Targets where catalog_id starts with "Abell " or "ACO "
    Stage 2: Targets where aliases contain Abell/ACO patterns
    Stage 3: Coordinate proximity for cluster-type targets

    Returns the number of matches created.
    """
    entries = session.execute(select(AbellEntry)).scalars().all()
    matched = 0

    # Build a lookup from abell number to entry for name matching
    abell_by_number: dict[int, AbellEntry] = {}
    for entry in entries:
        parts = entry.abell_id.split()
        if len(parts) == 2:
            try:
                abell_by_number[int(parts[1])] = entry
            except ValueError:
                pass

    # Get all non-merged targets once
    all_targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    matched_target_ids: set = set()

    # Stage 1: catalog_id starts with "Abell " or "ACO "
    for target in all_targets:
        if not target.catalog_id:
            continue
        cid = target.catalog_id.strip()
        num = None
        if cid.startswith("Abell "):
            try:
                num = int(cid[6:])
            except ValueError:
                pass
        elif cid.startswith("ACO "):
            try:
                num = int(cid[4:])
            except ValueError:
                pass

        if num is not None and num in abell_by_number:
            entry = abell_by_number[num]
            upsert_membership(
                session,
                target_id=target.id,
                catalog_name="abell",
                catalog_number=entry.abell_id,
                metadata=_build_abell_metadata(entry),
            )
            matched_target_ids.add(target.id)
            matched += 1

    # Stage 2: aliases contain "Abell {num}" or "ACO {num}"
    for target in all_targets:
        if target.id in matched_target_ids:
            continue
        if not target.aliases:
            continue

        for alias in target.aliases:
            alias = alias.strip()
            num = None
            if alias.startswith("Abell "):
                try:
                    num = int(alias[6:])
                except ValueError:
                    pass
            elif alias.startswith("ACO "):
                try:
                    num = int(alias[4:])
                except ValueError:
                    pass

            if num is not None and num in abell_by_number:
                entry = abell_by_number[num]
                upsert_membership(
                    session,
                    target_id=target.id,
                    catalog_name="abell",
                    catalog_number=entry.abell_id,
                    metadata=_build_abell_metadata(entry),
                )
                matched_target_ids.add(target.id)
                matched += 1
                break  # One match per target

    # Stage 3: coordinate proximity for cluster-type targets
    for target in all_targets:
        if target.id in matched_target_ids:
            continue
        if target.ra is None or target.dec is None:
            continue
        if not target.object_type:
            continue

        # Check if this target is a cluster type
        is_cluster = any(ct in target.object_type for ct in _CLUSTER_TYPES)
        if not is_cluster:
            continue

        for entry in entries:
            if entry.ra is None or entry.dec is None:
                continue
            dist = _coord_distance(target.ra, target.dec, entry.ra, entry.dec)
            if dist <= _COORD_MATCH_DEG:
                upsert_membership(
                    session,
                    target_id=target.id,
                    catalog_name="abell",
                    catalog_number=entry.abell_id,
                    metadata=_build_abell_metadata(entry),
                )
                matched_target_ids.add(target.id)
                matched += 1
                break  # Best match found

    session.flush()
    logger.info("Matched %d Abell targets", matched)
    return matched
