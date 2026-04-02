import re
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SIMBAD_TAP_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"


def normalize_object_name(name: str) -> str:
    """Normalize a target name: strip outer whitespace, uppercase, collapse inner spaces."""
    cleaned = re.sub(r"\s+", " ", name.strip()).upper()
    return cleaned


# ---------------------------------------------------------------------------
# Catalog priority & alias curation helpers
# ---------------------------------------------------------------------------

def _normalize_ws(s: str) -> str:
    """Collapse multiple whitespace to single space and strip."""
    return re.sub(r"\s+", " ", s.strip())


# Ordered list: index = priority (lower wins).
CATALOG_PATTERNS: list[re.Pattern] = [
    re.compile(r"^M\s*\d+$"),                         # 0  Messier
    re.compile(r"^NGC\s*\d+$"),                        # 1  NGC
    re.compile(r"^IC\s*\d+[A-Z]?$"),                   # 2  IC
    re.compile(r"^(Caldwell|C)\s+\d+$"),               # 3  Caldwell
    re.compile(r"^SH\s*2-\d+$", re.IGNORECASE),       # 4  Sharpless
    re.compile(r"^(PN\s+A66\s+\d+|Abell\s+\d+)$"),    # 5  Abell PN
    re.compile(r"^Arp\s*\d+$"),                        # 6  Arp
    re.compile(r"^HCG\s*\d+$"),                        # 7  HCG
    re.compile(r"^B\s+\d+$"),                          # 8  Barnard
    re.compile(r"^vdB\s*\d+$"),                        # 9  vdB
    re.compile(r"^LBN\s+[\d.+\-]+$"),                  # 10 LBN
    re.compile(r"^LDN\s+\d+$"),                        # 11 LDN
    re.compile(r"^(Cr|Collinder)\s+\d+$"),             # 12 Collinder
    re.compile(r"^(Mel|Melotte)\s+\d+$"),              # 13 Melotte
    re.compile(r"^RCW\s+\d+$"),                        # 14 RCW
    re.compile(r"^Pal\s+\d+$"),                        # 15 Palomar
    re.compile(r"^(Tr|Trumpler)\s+\d+$"),              # 16 Trumpler
    re.compile(r"^Stock\s+\d+$"),                      # 17 Stock
    re.compile(r"^(Ced|Cederblad)\s+\d+$"),            # 18 Cederblad
    re.compile(r"^Simeis\s+\d+$"),                     # 19 Simeis
    re.compile(r"^DWB\s+\d+$"),                        # 20 DWB
    re.compile(r"^SNR\s+G[\d.+\-]+$"),                 # 21 SNR G
    re.compile(r"^Cl\s+Berkeley\s+\d+$"),              # 22 Berkeley
    re.compile(r"^Cl\s+King\s+\d+$"),                  # 23 King
    re.compile(r"^Gum\s+\d+$"),                        # 24 Gum
    re.compile(r"^Sh\s*2[\s\-]\d+$", re.IGNORECASE),  # 25 Sh2 variant
]

# Pattern to detect coordinate-based / survey IDs we want to drop
_COORD_ID_RE = re.compile(
    r"^("
    r"2MASS\s|USNO|GSC|TYC|SDSS|WISE|GAIA|UCAC|IRAS\s"
    r"|\[.*\]"           # bracket-prefixed like [BFS98]
    r"|\d{1,2}\s?\d{2}\s?\d"  # bare RA-style coords
    r")",
    re.IGNORECASE,
)


def _catalog_priority(name: str) -> int | None:
    """Return the priority index of *name* if it matches a known catalog pattern, else None."""
    n = _normalize_ws(name)
    for idx, pat in enumerate(CATALOG_PATTERNS):
        if pat.match(n):
            return idx
    return None


def extract_catalog_id(aliases: list[str], simbad_main_id: str) -> str:
    """Pick the best catalog ID from *aliases* + *simbad_main_id* using catalog priority.

    Falls back to ``_normalize_ws(simbad_main_id)`` if no catalog match is found.
    """
    best_name: str | None = None
    best_pri: int | None = None

    candidates = list(aliases) + [simbad_main_id]
    for raw in candidates:
        n = _normalize_ws(raw)
        pri = _catalog_priority(n)
        if pri is not None and (best_pri is None or pri < best_pri):
            best_pri = pri
            best_name = n

    fallback = _normalize_ws(simbad_main_id)
    # Strip SIMBAD "NAME " prefix from fallback — it's a common-name marker, not a catalog ID
    if fallback.upper().startswith("NAME "):
        fallback = fallback[5:].strip()
    return best_name if best_name is not None else fallback


def curate_aliases(raw_aliases: list[str], fits_names: list[str] | None = None) -> list[str]:
    """Filter and deduplicate aliases.

    Keeps:
    - Catalog IDs (anything matching CATALOG_PATTERNS)
    - NAME entries from SIMBAD (title-cased, NAME prefix stripped)
    - Normalized FITS names

    Drops:
    - Coordinate-based / survey IDs (2MASS, bracket-prefixed, etc.)
    """
    seen_upper: set[str] = set()
    result: list[str] = []

    def _add(value: str) -> None:
        key = value.upper().replace(" ", "")
        if key not in seen_upper:
            seen_upper.add(key)
            result.append(value)

    for raw in raw_aliases:
        n = _normalize_ws(raw)

        # NAME entries -> title-cased common name
        if n.upper().startswith("NAME "):
            common = n[5:].strip().title()
            _add(common)
            continue

        # Catalog match -> keep normalized
        if _catalog_priority(n) is not None:
            _add(n)
            continue

        # Everything else (coordinate IDs, survey IDs) -> drop

    # Add FITS names
    if fits_names:
        for fn in fits_names:
            n = _normalize_ws(fn)
            if n:
                _add(n)

    return result


def extract_common_name(
    raw_aliases: list[str],
    fits_names: list[str] | None = None,
) -> str | None:
    """Extract a human-friendly common name.

    Priority:
    1. SIMBAD ``NAME`` alias (title-cased)
    2. FITS name that is *not* a catalog pattern
    3. None
    """
    # Check SIMBAD NAME aliases first
    for raw in raw_aliases:
        n = _normalize_ws(raw)
        if n.upper().startswith("NAME "):
            return n[5:].strip().title()

    # FITS name fallback — strip "Panel N" suffix
    if fits_names:
        for fn in fits_names:
            n = _PANEL_RE.sub("", _normalize_ws(fn)).strip()
            if n and _catalog_priority(n) is None:
                return n

    return None


def build_primary_name(catalog_id: str | None, common_name: str | None) -> str:
    """Build display name: ``'NGC 7000 - North America Nebula'`` or fallback."""
    if catalog_id and common_name:
        return f"{catalog_id} - {common_name}"
    if catalog_id:
        return catalog_id
    if common_name:
        return common_name
    return "Unknown"


async def _fetch_tap_aliases(object_name: str) -> list[str]:
    """Fetch aliases via SIMBAD TAP (returns one alias per row)."""
    import string
    safe_chars = string.printable.replace('\n', '').replace('\r', '').replace('\t', '')
    sanitized = ''.join(c for c in object_name if c in safe_chars).strip()

    query = f"SELECT id FROM ident JOIN basic ON ident.oidref = basic.oid WHERE basic.main_id = '{sanitized}'"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                SIMBAD_TAP_URL,
                params={
                    "request": "doQuery",
                    "lang": "adql",
                    "format": "tsv",
                    "query": query,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            # First line is the header ("id"), skip it
            if len(lines) <= 1:
                return []
            return [line.strip() for line in lines[1:] if line.strip()]
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("SIMBAD TAP alias query failed for '%s': %s", object_name, e)
        return []


async def _query_simbad_raw(object_name: str) -> dict[str, Any] | None:
    """Query SIMBAD for raw data (main_id, aliases, coords, type). No curation."""
    import string
    safe_chars = string.printable.replace('\n', '').replace('\r', '').replace('\t', '')
    sanitized = ''.join(c for c in object_name if c in safe_chars).strip()
    if not sanitized:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            script = f"""
                format object "%MAIN_ID|%OTYPELIST|%COO(d;A)|%COO(d;D)"
                query id {sanitized}
            """
            resp = await client.post(
                "https://simbad.cds.unistra.fr/simbad/sim-script",
                data={"script": script},
                timeout=15.0,
            )
            resp.raise_for_status()

            text = resp.text
            if "::error::" in text:
                logger.info("SIMBAD found no match for '%s'", sanitized)
                return None

            data_section = text.split("::data::")[-1].strip()
            lines = [l.strip() for l in data_section.splitlines()
                     if l.strip() and not l.startswith("~") and not set(l.strip()).issubset({":"})]
            if not lines:
                return None

            parts = lines[0].split("|")
            if len(parts) < 4:
                return None

            main_id = parts[0].strip()
            obj_type = parts[1].strip()
            ra = float(parts[2].strip()) if parts[2].strip() else None
            dec = float(parts[3].strip()) if parts[3].strip() else None

        raw_aliases = await _fetch_tap_aliases(main_id)

        return {
            "main_id": main_id,
            "raw_aliases": raw_aliases,
            "ra": ra,
            "dec": dec,
            "object_type": obj_type,
        }

    except (httpx.HTTPError, ValueError, IndexError) as e:
        logger.warning("SIMBAD query failed for '%s': %s", sanitized, e)
        return None


def curate_simbad_result(
    raw: dict[str, Any],
    fits_names: list[str] | None = None,
) -> dict[str, Any]:
    """Apply curation to raw SIMBAD data: extract catalog_id, common_name, curate aliases."""
    raw_aliases = [str(a) for a in raw.get("raw_aliases", []) if a is not None]
    main_id = str(raw.get("main_id", ""))

    curated = curate_aliases(raw_aliases, fits_names=fits_names)
    catalog_id = extract_catalog_id(raw_aliases, main_id)
    common_name = extract_common_name(raw_aliases, fits_names=fits_names)
    primary_name = build_primary_name(catalog_id, common_name)

    return {
        "primary_name": primary_name,
        "catalog_id": catalog_id,
        "common_name": common_name,
        "aliases": curated,
        "ra": raw.get("ra"),
        "dec": raw.get("dec"),
        "object_type": raw.get("object_type"),
    }


async def _query_simbad(object_name: str) -> dict[str, Any] | None:
    """Query SIMBAD, cache result, return curated data."""
    raw = await _query_simbad_raw(object_name)
    if raw is None:
        return None
    return curate_simbad_result(raw)


# Common names that SIMBAD's script interface doesn't resolve.
# Maps colloquial/common names to SIMBAD-resolvable identifiers.
COMMON_NAME_MAP: dict[str, str] = {
    "pinwheel galaxy": "M 101",
    "flying bat nebula": "Sh2-129",
    "beehive cluster": "M 44",
    "wizard nebula": "NGC 7380",
    "the wizard nebula": "NGC 7380",
    "hamburger galaxy": "NGC 3628",
    "fish head nebula": "IC 1795",
    "dolphin nebula": "Sh2-308",
    "fossil footprint nebula": "NGC 1491",
    "spaghetti nebula": "Simeis 147",
    "sadr region": "IC 1318",
    "elephant's trunk nebula": "IC 1396A",
    "elephant's trunk neb": "IC 1396A",
    "gam cas nebula": "IC 63",
    "markarian's chain": "NAME Markarian Chain",
    "california nebula": "NGC 1499",
    "heart nebula": "IC 1805",
    "soul nebula": "IC 1848",
    "bode's galaxy": "M 81",
    "moon": "Moon",
    "north america nebula": "NGC 7000",
    "east veil nebula": "NGC 6992",
    "veil nebula": "NGC 6960",
    "flaming star nebula": "IC 405",
    "flame nebula": "NGC 2024",
    "christmas tree cluster": "NGC 2264",
    "cat's eye nebula": "NGC 6543",
    "sombrero galaxy": "M 104",
    "question mark galaxy": "NGC 4258",
    "leo triplet": "NAME Leo Triplet",
    "rho oph": "rho Oph",
    "cave nebula": "Sh2-155",
    "jellyfish nebula": "IC 443",
    "caldwell 4": "NGC 7023",
    "caldwell 38": "NGC 4565",
    "triangulum pinwheel": "M 33",
    "andromeda galaxy": "M 31",
    "seagull nebula": "IC 2177",
    "seagull's wings": "IC 2177",
    "spider nebula": "IC 417",
    "casper the friendly ghost nebula": "Sh2-136",
}

# Strip "Panel N" suffix to get the base object name
_PANEL_RE = re.compile(r"\s+Panel\s+\d+$", re.IGNORECASE)


_SH2_RE = re.compile(r"^Sh2[\s\-_]+(\d+)$", re.IGNORECASE)
_LBN_RE = re.compile(r"^LBN[\s\-_]+(\d+)$", re.IGNORECASE)
_CALDWELL_RE = re.compile(r"^Caldwell\s+(\d+)$", re.IGNORECASE)


def _get_simbad_id(object_name: str) -> str:
    """Try to map a common name to a SIMBAD-resolvable identifier."""
    # Strip panel suffix first
    base = _PANEL_RE.sub("", object_name).strip()
    key = base.lower()

    if key in COMMON_NAME_MAP:
        return COMMON_NAME_MAP[key]

    # Caldwell catalog: "Caldwell 7" -> "C 7" (SIMBAD format)
    m = _CALDWELL_RE.match(base)
    if m:
        return f"C {m.group(1)}"

    # Sharpless catalog: "Sh2 174" -> "SH 2-174"
    m = _SH2_RE.match(base)
    if m:
        return f"SH 2-{m.group(1)}"

    # LBN catalog: "LBN 672" -> "LBN 672" (SIMBAD uses this format)
    m = _LBN_RE.match(base)
    if m:
        return f"LBN {m.group(1)}"

    return object_name


def get_cached_simbad(query_name: str, db_session) -> dict[str, Any] | None:
    """Look up a cached SIMBAD result. Returns raw dict or None."""
    from app.models.simbad_cache import SimbadCache
    row = db_session.execute(
        __import__("sqlalchemy").select(SimbadCache).where(SimbadCache.query_name == query_name)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.main_id is None:
        return {"_negative": True}  # Cached negative result
    return {
        "main_id": row.main_id,
        "raw_aliases": row.raw_aliases or [],
        "ra": row.ra,
        "dec": row.dec,
        "object_type": row.object_type,
    }


def save_simbad_cache(query_name: str, raw: dict[str, Any] | None, db_session) -> None:
    """Persist a SIMBAD result (or negative) to the cache table."""
    from app.models.simbad_cache import SimbadCache
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = {
        "query_name": query_name,
        "main_id": raw["main_id"] if raw else None,
        "raw_aliases": raw.get("raw_aliases", []) if raw else [],
        "ra": raw.get("ra") if raw else None,
        "dec": raw.get("dec") if raw else None,
        "object_type": raw.get("object_type") if raw else None,
    }
    stmt = pg_insert(SimbadCache).values(**values).on_conflict_do_update(
        index_elements=["query_name"],
        set_=values,
    )
    db_session.execute(stmt)


async def resolve_target_name(object_name: str) -> dict[str, Any] | None:
    """Resolve an object name via SIMBAD. Returns curated dict or None."""
    # Try direct query first
    result = await _query_simbad(object_name)
    if result:
        return result

    # Try common name mapping
    mapped = _get_simbad_id(object_name)
    if mapped != object_name:
        logger.info("Trying mapped name: '%s' -> '%s'", object_name, mapped)
        result = await _query_simbad(mapped)
        if result:
            return result

    return None


def resolve_target_name_cached(
    object_name: str, db_session, *, skip_simbad: bool = False,
) -> dict[str, Any] | None:
    """Resolve with persistent DB cache. Sync version for Celery workers.

    If skip_simbad=True, only returns cached data (for smart rebuild).
    """
    import asyncio

    normalized = normalize_object_name(object_name)

    # Check cache
    cached = get_cached_simbad(normalized, db_session)
    if cached is not None:
        if cached.get("_negative"):
            return None
        return curate_simbad_result(cached)

    # Also try with common name mapping
    mapped = _get_simbad_id(object_name)
    if mapped != object_name:
        mapped_norm = normalize_object_name(mapped)
        cached = get_cached_simbad(mapped_norm, db_session)
        if cached is not None:
            if cached.get("_negative"):
                return None
            return curate_simbad_result(cached)

    if skip_simbad:
        return None

    # Query SIMBAD and cache
    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(_query_simbad_raw(object_name))
    finally:
        loop.close()

    if raw is None and mapped != object_name:
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(_query_simbad_raw(mapped))
        finally:
            loop.close()

    # Cache the result (positive or negative)
    save_simbad_cache(normalized, raw, db_session)
    if raw is None:
        return None
    return curate_simbad_result(raw)
