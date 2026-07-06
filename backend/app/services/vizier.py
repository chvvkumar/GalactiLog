"""VizieR catalog service - TAP queries for non-NGC/IC target enrichment."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

from app.services import catalog_cache as cc

if TYPE_CHECKING:
    from app.models.target import Target

logger = logging.getLogger(__name__)

VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"

# Maps catalog_id prefix pattern -> (vizier_catalog_id, adql_table, number_column)
_CATALOG_MAP: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"^SH\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^Sh\s*2[\s-](\d+)$", re.IGNORECASE), "VII/20", '"VII/20/catalog"', "Sh2"),
    (re.compile(r"^LBN\s+(\d+)$", re.IGNORECASE), "VII/9", '"VII/9/catalog"', "LBN"),
    (re.compile(r"^LBN\s+(\d+\.\d+[+-]\d+\.\d+)$", re.IGNORECASE), "VII/9", '"VII/9/catalog"', "LBN_COORD"),
    (re.compile(r"^RCW\s+(\d+)$", re.IGNORECASE), "VII/216", '"VII/216/rcw"', "RCW"),
    (re.compile(r"^vdB\s*(\d+)$", re.IGNORECASE), "VII/21", '"VII/21/catalog"', "VdB"),
    (re.compile(r"^LDN\s+(\d+)$", re.IGNORECASE), "VII/7A", '"VII/7A/ldn"', "LDN"),
    (re.compile(r"^B\s+(\d+)$"), "VII/220A", '"VII/220A/barnard"', "Barn"),
    (re.compile(r"^(Ced|Cederblad)\s+(.+)$", re.IGNORECASE), "VII/231", '"VII/231/catalog"', "Ced"),
    (re.compile(r"^(PN\s+A66|Abell)\s+(\d+)$", re.IGNORECASE), "V/84", '"V/84/main"', "Name"),
    # Open clusters - multiple name formats, all go to B/ocl
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
        # fullmatch so trailing junk (e.g. an injected "'; DROP ...") does not
        # partially match a catalog pattern.
        if pattern.fullmatch(cleaned):
            return (viz_id, table, num_col)

    return None


def _adql_quote(value: str) -> str:
    """Escape a value for use inside a single-quoted ADQL/SQL string literal.

    Doubles single quotes per the SQL standard so the value cannot break out
    of the surrounding quotes.
    """
    return value.replace("'", "''")


def _adql_int(value: str) -> int | None:
    """Coerce a value to int for use in an unquoted ADQL numeric comparison.

    Returns None if the value is not a clean integer, so callers can decline
    to build a query rather than interpolate raw text.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
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
    raw_number = _extract_number(catalog_id)
    number = _adql_int(raw_number)

    # Note: VizieR computed columns (_RA_icrs, _DE_icrs) appear in SELECT *
    # output but cannot be explicitly named in ADQL.  We only need size data
    # from VizieR (targets already have J2000 coords from SIMBAD), so we
    # select only size-related columns.

    if viz_id == "VII/20":
        # Sharpless: Sh2 is integer, Diam in arcmin
        if number is None:
            return None
        return f'SELECT Sh2, Diam FROM {table} WHERE Sh2={number}'

    elif viz_id == "VII/9" and num_col == "LBN_COORD":
        # LBN coordinate-format ID like "LBN 080.79+03.15" - search by galactic coords
        coord_str = catalog_id.strip().split(None, 1)[1]  # "080.79+03.15"
        m = re.match(r"(\d+\.\d+)([+-])(\d+\.\d+)", coord_str)
        if m:
            glon = float(m.group(1))
            sign = m.group(2)
            glat = float(f"{sign}{m.group(3)}")
            return (
                f'SELECT Seq, Diam1, Diam2 FROM {table} '
                f'WHERE ABS(GLON - {glon}) < 0.05 AND ABS(GLAT - {glat}) < 0.05'
            )
        return None

    elif viz_id == "VII/9":
        # LBN: Seq is integer, Diam1/Diam2 in arcmin
        if number is None:
            return None
        return f'SELECT Seq, Diam1, Diam2 FROM {table} WHERE Seq={number}'

    elif viz_id == "VII/216":
        # RCW: RCW is integer, MajAxis/MinAxis in arcmin
        if number is None:
            return None
        return f'SELECT RCW, MajAxis, MinAxis FROM {table} WHERE RCW={number}'

    elif viz_id == "VII/21":
        # vdB: VdB is integer, BRadMax in arcmin (radius, need to double)
        if number is None:
            return None
        return f'SELECT VdB, BRadMax, RRadMax FROM {table} WHERE VdB={number}'

    elif viz_id == "VII/7A":
        # LDN: LDN is integer, Area in sq deg
        if number is None:
            return None
        return f'SELECT LDN, Area FROM {table} WHERE LDN={number}'

    elif viz_id == "VII/220A":
        # Barnard: Barn is CHAR(4), space-padded - use TRIM
        if number is None:
            return None
        return f"SELECT Barn, Diam FROM {table} WHERE TRIM(Barn)='{number}'"

    elif viz_id == "VII/231":
        # Cederblad: Ced is string
        ced_num = catalog_id.split()[-1].strip() if " " in catalog_id else raw_number
        return f"SELECT Ced, Dim1, Dim2 FROM {table} WHERE TRIM(Ced)='{_adql_quote(ced_num)}'"

    elif viz_id == "V/84":
        # Planetary nebulae (Abell PNe): query by Name containing "A <number>"
        # Join with diam table for optical diameter
        if number is None:
            return None
        return (
            f'SELECT m."Name", d.oDiam '
            f'FROM "V/84/main" AS m '
            f'LEFT JOIN "V/84/diam" AS d ON m."PNG"=d."PNG" '
            f"WHERE m.\"Name\" LIKE '%A {number}%'"
        )

    elif viz_id == "B/ocl":
        # Open clusters: Cluster is string like "Collinder 399"
        cluster_name = catalog_id.strip()
        return f"SELECT \"Cluster\", Diam FROM {table} WHERE \"Cluster\"='{_adql_quote(cluster_name)}'"

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

    if viz_id == "VII/20":
        size_major = _float("Diam")

    elif viz_id == "VII/9":
        size_major = _float("Diam1")
        size_minor = _float("Diam2")

    elif viz_id == "VII/216":
        size_major = _float("MajAxis")
        size_minor = _float("MinAxis")

    elif viz_id == "VII/21":
        # vdB stores radius, double for diameter
        brad = _float("BRadMax")
        if brad is not None:
            size_major = brad * 2
        rrad = _float("RRadMax")
        if rrad is not None:
            size_minor = rrad * 2

    elif viz_id == "VII/7A":
        # LDN: Area in sq deg, convert to approximate diameter in arcmin
        area = _float("Area")
        if area is not None:
            import math
            # Approximate circular diameter from area: d = 2 * sqrt(area/pi)
            diam_deg = 2 * math.sqrt(area / math.pi)
            size_major = diam_deg * 60  # Convert degrees to arcmin

    elif viz_id == "VII/220A":
        size_major = _float("Diam")

    elif viz_id == "VII/231":
        size_major = _float("Dim1")
        size_minor = _float("Dim2")

    elif viz_id == "V/84":
        odiam = _float("oDiam")
        if odiam is not None:
            size_major = odiam / 60  # Convert arcsec to arcmin

    elif viz_id == "B/ocl":
        size_major = _float("Diam")

    if size_major is None and size_minor is None:
        return None

    return {
        "size_major": size_major,
        "size_minor": size_minor,
    }


def _coords_to_constellation(ra: float | None, dec: float | None) -> str | None:
    """Derive IAU constellation abbreviation from J2000 coordinates.

    Uses astropy's constellation boundary lookup (Roman 1987).
    Returns None if coords are missing - constellation enrichment is best-effort.
    """
    from app.services.constellation import coords_to_constellation
    return coords_to_constellation(ra, dec)


def query_vizier(catalog_id: str) -> dict[str, Any] | None:
    """Query VizieR TAP for target data. Returns dict with size_major, size_minor, or None.

    Raises on HTTP/network failures for the wrapper's retry+backoff to handle.
    Returns None only for "queried successfully, no result" (parsed as negative cache).
    """
    adql = build_adql_query(catalog_id)
    if adql is None:
        return None

    result = determine_vizier_catalog(catalog_id)
    if result is None:
        return None
    viz_id = result[0]

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


def get_cached_vizier(catalog_id: str, session: Session) -> dict[str, Any] | str | None:
    """Check the VizieR cache for a previous lookup.

    Returns the cached payload dict on a positive hit, cc.NEGATIVE on a negative cache hit,
    or None on a cache miss. Separates cache-check from fetch so HTTP calls happen outside
    any open transaction.
    """
    return cc.get_cached(session, "vizier", catalog_id)


def save_vizier_cache(
    session: Session, catalog_id: str, viz_id: str | None, data: dict[str, Any] | None,
) -> None:
    """Save a VizieR lookup result (including negative) to the cache.

    viz_id (the specific VizieR catalog like "VII/20") is preserved in the payload
    for reference. Does not commit -- caller owns the transaction.
    """
    payload = None
    if data is not None:
        payload = {
            "size_major": data.get("size_major"),
            "size_minor": data.get("size_minor"),
            "constellation": data.get("constellation"),
            "vizier_catalog": viz_id,  # Preserve metadata even though not used in negative detection
        }
    cc.save_cached(session, "vizier", catalog_id, payload)


def enrich_target_from_vizier(session: Session, target: "Target") -> bool:
    """Enrich a target from VizieR. Checks cache first, queries if needed.

    HTTP call is made outside any open transaction to avoid holding DB
    connections during network I/O. A cache-miss fetch goes through the
    cache wrapper's get_or_fetch, so a transient VizieR failure is retried
    with backoff and, if every attempt fails, negative-cached (returns
    False) rather than raising; a non-transient failure (e.g. a 4xx) raises
    NonTransientError uncaught, matching hyperleda/gaia.

    Returns True if any fields were updated.
    """
    if getattr(target, "user_defined", False):
        return False

    if not target.catalog_id:
        return False

    # Skip if not a VizieR-supported catalog
    if determine_vizier_catalog(target.catalog_id) is None:
        return False

    # Check cache (read-only, no transaction). Returns:
    # - dict (positive hit) -- apply enrichment
    # - cc.NEGATIVE (negative hit) -- skip query
    # - None (cache miss or expired) -- query
    cached = get_cached_vizier(target.catalog_id, session)

    if cached is cc.NEGATIVE:
        # Negative cache hit - skip the query
        return False

    if cached is not None:
        # Positive cache hit - apply enrichment
        updated = False
        if cached.get("size_major") is not None and target.size_major is None:
            target.size_major = cached["size_major"]
            updated = True
        if cached.get("size_minor") is not None and target.size_minor is None:
            target.size_minor = cached["size_minor"]
            updated = True
        if cached.get("constellation") is not None and target.constellation is None:
            target.constellation = cached["constellation"]
            updated = True
        return updated

    # Cache miss or expired - Query VizieR via the cache wrapper (handles
    # retry/backoff and negative caching). The HTTP call happens outside any
    # open transaction.
    def fetch() -> dict[str, Any] | None:
        return query_vizier(target.catalog_id)

    data = cc.get_or_fetch(session, "vizier", target.catalog_id, fetch)
    session.commit()

    if data is None:
        return False

    # Apply enrichment
    updated = False
    if data.get("size_major") is not None and target.size_major is None:
        target.size_major = data["size_major"]
        updated = True
    if data.get("size_minor") is not None and target.size_minor is None:
        target.size_minor = data["size_minor"]
        updated = True
    if data.get("constellation") is not None and target.constellation is None:
        target.constellation = data["constellation"]
        updated = True

    return updated
