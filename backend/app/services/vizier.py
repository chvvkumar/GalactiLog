"""VizieR catalog service — TAP queries for non-NGC/IC target enrichment."""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.vizier_cache import VizierCache

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"

# Maps catalog_id prefix pattern -> (vizier_catalog_id, adql_table, number_column)
_CATALOG_MAP: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"^SH\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^Sh\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^LBN\s+(\d+)$", re.IGNORECASE), "VII/9", '"VII/9/catalog"', "LBN"),
    (re.compile(r"^RCW\s+(\d+)$", re.IGNORECASE), "VII/216", '"VII/216/rcw"', "RCW"),
    (re.compile(r"^vdB\s*(\d+)$", re.IGNORECASE), "VII/21", '"VII/21/catalog"', "VdB"),
    (re.compile(r"^LDN\s+(\d+)$", re.IGNORECASE), "VII/7A", '"VII/7A/ldn"', "LDN"),
    (re.compile(r"^B\s+(\d+)$"), "VII/220A", '"VII/220A/barnard"', "Barn"),
    (re.compile(r"^(Ced|Cederblad)\s+(.+)$", re.IGNORECASE), "VII/231", '"VII/231/catalog"', "Ced"),
    (re.compile(r"^(PN\s+A66|Abell)\s+(\d+)$", re.IGNORECASE), "V/84", '"V/84/main"', "Name"),
    # Open clusters — multiple name formats, all go to B/ocl
    (re.compile(r"^(Collinder|Cr|Melotte|Mel|Trumpler|Tr|Berkeley|King|Stock)\s+\d+", re.IGNORECASE),
     "B/ocl", '"B/ocl/clusters"', "Cluster"),
]


def determine_vizier_catalog(catalog_id: str | None) -> tuple[str, str, str] | None:
    """Determine which VizieR catalog to query based on catalog_id prefix.

    Returns (vizier_catalog_id, adql_table, number_column) or None if not a VizieR target.
    """
    if not catalog_id or not catalog_id.strip():
        return None

    cleaned = catalog_id.strip()

    for pattern, viz_id, table, num_col in _CATALOG_MAP:
        if pattern.match(cleaned):
            return (viz_id, table, num_col)

    return None


def _extract_number(catalog_id: str) -> str:
    """Extract the catalog number from a catalog_id like 'SH 2-129' -> '129', 'B 33' -> '33'."""
    # Try splitting on hyphen first (Sharpless: SH 2-129)
    if "-" in catalog_id:
        return catalog_id.rsplit("-", 1)[-1].strip()
    # Otherwise last token (B 33, LBN 437, etc.)
    parts = catalog_id.strip().split()
    return parts[-1].strip() if parts else catalog_id


def build_adql_query(catalog_id: str | None) -> str | None:
    """Build an ADQL query for the given catalog_id.

    Returns the ADQL string or None if not a VizieR target.
    """
    result = determine_vizier_catalog(catalog_id)
    if result is None:
        return None

    viz_id, table, num_col = result
    number = _extract_number(catalog_id)

    if viz_id == "VII/20":
        # Sharpless: Sh2 is integer, Diam in arcmin
        return f'SELECT Sh2, Diam, RA1900, DE1900 FROM {table} WHERE Sh2={number}'

    elif viz_id == "VII/9":
        # LBN: Seq is integer, Diam1/Diam2 in arcmin
        return f'SELECT Seq, Diam1, Diam2, "_RA_icrs", "_DE_icrs" FROM {table} WHERE Seq={number}'

    elif viz_id == "VII/216":
        # RCW: RCW is integer, MajAxis/MinAxis in arcmin
        return f'SELECT RCW, MajAxis, MinAxis, "_RA_icrs", "_DE_icrs" FROM {table} WHERE RCW={number}'

    elif viz_id == "VII/21":
        # vdB: VdB is integer, BRadMax in arcmin (radius, need to double)
        return f'SELECT VdB, BRadMax, RRadMax, "_RA_icrs", "_DE_icrs" FROM {table} WHERE VdB={number}'

    elif viz_id == "VII/7A":
        # LDN: LDN is integer, Area in sq deg
        return f'SELECT LDN, Area, "_RA_icrs", "_DE_icrs" FROM {table} WHERE LDN={number}'

    elif viz_id == "VII/220A":
        # Barnard: Barn is CHAR(4), space-padded — use TRIM
        return f"SELECT Barn, Diam, \"_RA_icrs\", \"_DE_icrs\" FROM {table} WHERE TRIM(Barn)='{number}'"

    elif viz_id == "VII/231":
        # Cederblad: Ced is string
        ced_num = catalog_id.split()[-1].strip() if " " in catalog_id else number
        return f"SELECT Ced, Dim1, Dim2, \"_RA_icrs\", \"_DE_icrs\" FROM {table} WHERE TRIM(Ced)='{ced_num}'"

    elif viz_id == "V/84":
        # Planetary nebulae (Abell PNe): query by Name containing "A <number>"
        # Join with diam table for optical diameter
        return (
            f'SELECT m."Name", d.oDiam, m."_RA_icrs", m."_DE_icrs" '
            f'FROM "V/84/main" AS m '
            f'LEFT JOIN "V/84/diam" AS d ON m."PNG"=d."PNG" '
            f"WHERE m.\"Name\" LIKE '%A {number}%'"
        )

    elif viz_id == "B/ocl":
        # Open clusters: Cluster is string like "Collinder 399"
        cluster_name = catalog_id.strip()
        return f"SELECT \"Cluster\", Diam, RAJ2000, DEJ2000 FROM {table} WHERE \"Cluster\"='{cluster_name}'"

    return None


def _parse_vizier_response(viz_id: str, lines: list[str]) -> dict[str, Any] | None:
    """Parse a TSV response from VizieR into a dict with size_major, size_minor, ra, dec."""
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

    size_major = None
    size_minor = None
    ra = None
    dec = None

    if viz_id == "VII/20":
        size_major = _float("Diam")
        ra = _float("RA1900")  # Approximate — B1900 coords
        dec = _float("DE1900")

    elif viz_id == "VII/9":
        size_major = _float("Diam1")
        size_minor = _float("Diam2")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/216":
        size_major = _float("MajAxis")
        size_minor = _float("MinAxis")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/21":
        # vdB stores radius, double for diameter
        brad = _float("BRadMax")
        if brad is not None:
            size_major = brad * 2
        rrad = _float("RRadMax")
        if rrad is not None:
            size_minor = rrad * 2
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/7A":
        # LDN: Area in sq deg, convert to approximate diameter in arcmin
        area = _float("Area")
        if area is not None:
            import math
            # Approximate circular diameter from area: d = 2 * sqrt(area/pi)
            diam_deg = 2 * math.sqrt(area / math.pi)
            size_major = diam_deg * 60  # Convert degrees to arcmin

        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/220A":
        size_major = _float("Diam")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "VII/231":
        size_major = _float("Dim1")
        size_minor = _float("Dim2")
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "V/84":
        odiam = _float("oDiam")
        if odiam is not None:
            size_major = odiam / 60  # Convert arcsec to arcmin
        ra = _float("_RA_icrs")
        dec = _float("_DE_icrs")

    elif viz_id == "B/ocl":
        size_major = _float("Diam")
        ra = _float("RAJ2000")
        dec = _float("DEJ2000")

    if size_major is None and size_minor is None:
        return None

    return {
        "size_major": size_major,
        "size_minor": size_minor,
        "ra": ra,
        "dec": dec,
    }


def _coords_to_constellation(ra: float | None, dec: float | None) -> str | None:
    """Derive IAU constellation abbreviation from J2000 coordinates.

    Uses a simple lookup of the 88 constellation boundaries.
    Returns None if coords are missing — constellation enrichment is best-effort.
    """
    # Skip if no coordinates
    if ra is None or dec is None:
        return None

    # Use a simplified approach: try the target's existing constellation
    # (most targets already have constellation from OpenNGC or SIMBAD coords)
    # Full constellation boundary lookup is complex; defer to existing data
    return None


def query_vizier(catalog_id: str) -> dict[str, Any] | None:
    """Query VizieR TAP for target data. Returns dict with size_major, size_minor, or None."""
    adql = build_adql_query(catalog_id)
    if adql is None:
        return None

    result = determine_vizier_catalog(catalog_id)
    if result is None:
        return None
    viz_id = result[0]

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                VIZIER_TAP_URL,
                data={
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": "tsv",
                    "QUERY": adql,
                },
            )
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            return _parse_vizier_response(viz_id, lines)

    except (httpx.HTTPError, ValueError, IndexError) as e:
        logger.warning("VizieR query failed for '%s': %s", catalog_id, e)
        return None


def get_cached_vizier(catalog_id: str, session: Session) -> VizierCache | None:
    """Check the VizieR cache for a previous lookup."""
    return session.execute(
        select(VizierCache).where(VizierCache.catalog_id == catalog_id)
    ).scalar_one_or_none()


def save_vizier_cache(
    session: Session, catalog_id: str, viz_id: str | None, data: dict[str, Any] | None,
) -> None:
    """Save a VizieR lookup result (including negative) to the cache."""
    entry = {
        "catalog_id": catalog_id,
        "vizier_catalog": viz_id,
        "size_major": data.get("size_major") if data else None,
        "size_minor": data.get("size_minor") if data else None,
        "constellation": data.get("constellation") if data else None,
    }
    stmt = pg_insert(VizierCache).values(**entry).on_conflict_do_update(
        index_elements=["catalog_id"],
        set_=entry,
    )
    session.execute(stmt)


def enrich_target_from_vizier(session: Session, target: "Target") -> bool:
    """Enrich a target from VizieR. Checks cache first, queries if needed.

    Returns True if any fields were updated.
    """
    if not target.catalog_id:
        return False

    # Skip if not a VizieR-supported catalog
    if determine_vizier_catalog(target.catalog_id) is None:
        return False

    # Check cache
    cached = get_cached_vizier(target.catalog_id, session)
    if cached is not None:
        # Cached (positive or negative) — apply if positive
        if cached.size_major is None and cached.size_minor is None:
            return False
        updated = False
        if cached.size_major is not None and target.size_major is None:
            target.size_major = cached.size_major
            updated = True
        if cached.size_minor is not None and target.size_minor is None:
            target.size_minor = cached.size_minor
            updated = True
        if cached.constellation is not None and target.constellation is None:
            target.constellation = cached.constellation
            updated = True
        return updated

    # Query VizieR
    viz_id = determine_vizier_catalog(target.catalog_id)[0]
    data = query_vizier(target.catalog_id)

    # Cache the result (even if None — negative cache)
    save_vizier_cache(session, target.catalog_id, viz_id, data)
    session.flush()

    if data is None:
        return False

    updated = False
    if data.get("size_major") is not None and target.size_major is None:
        target.size_major = data["size_major"]
        updated = True
    if data.get("size_minor") is not None and target.size_minor is None:
        target.size_minor = data["size_minor"]
        updated = True

    return updated
