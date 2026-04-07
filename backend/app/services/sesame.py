"""CDS SESAME name resolver — fallback when SIMBAD direct query fails.

SESAME queries SIMBAD, NED, and VizieR behind a single endpoint.
We use it as a fallback to catch objects NED or VizieR can resolve
but SIMBAD's script interface cannot.

Docs: https://vizier.cds.unistra.fr/vizier/doc/sesame.htx
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame"


async def _query_sesame_raw(
    object_name: str, *, resolvers: str = "SNV",
) -> dict[str, Any] | None:
    """Query SESAME and parse the XML response.

    Args:
        object_name: Target name to resolve.
        resolvers: Which backends to query (S=SIMBAD, N=NED, V=VizieR).

    Returns dict with main_id, ra, dec, object_type, aliases, resolver
    or None if no match.
    """
    url = f"{SESAME_URL}/-ox/{resolvers}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params={"": object_name})
            resp.raise_for_status()

        root = ET.fromstring(resp.text)

        # Find the first Resolver with a successful result
        for resolver_el in root.iter("Resolver"):
            jradeg = resolver_el.findtext("jradeg")
            jdedeg = resolver_el.findtext("jdedeg")
            if jradeg is None or jdedeg is None:
                continue

            oname = resolver_el.findtext("oname") or object_name
            otype = resolver_el.findtext("otype") or ""
            resolver_name = resolver_el.get("name", "")

            aliases = [el.text for el in resolver_el.findall("alias") if el.text]

            return {
                "main_id": oname,
                "ra": float(jradeg),
                "dec": float(jdedeg),
                "object_type": otype.strip(),
                "raw_aliases": aliases,
                "resolver": resolver_name,
            }

        logger.info("SESAME found no match for '%s'", object_name)
        return None

    except (httpx.HTTPError, ET.ParseError, ValueError) as e:
        logger.warning("SESAME query failed for '%s': %s", object_name, e)
        return None


def get_cached_sesame(query_name: str, db_session) -> dict[str, Any] | None:
    """Look up a cached SESAME result. Returns raw dict or None (not in cache)."""
    from app.models.sesame_cache import SesameCache
    import sqlalchemy as sa

    row = db_session.execute(
        sa.select(SesameCache).where(SesameCache.query_name == query_name)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.main_id is None:
        return {"_negative": True}
    return {
        "main_id": row.main_id,
        "raw_aliases": row.raw_aliases or [],
        "ra": row.ra,
        "dec": row.dec,
        "object_type": row.object_type,
        "resolver": row.resolver,
    }


def save_sesame_cache(
    query_name: str, raw: dict[str, Any] | None, db_session,
) -> None:
    """Persist a SESAME result (or negative) to the cache table."""
    from app.models.sesame_cache import SesameCache
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = {
        "query_name": query_name,
        "main_id": raw["main_id"] if raw else None,
        "raw_aliases": raw.get("raw_aliases", []) if raw else [],
        "ra": raw.get("ra") if raw else None,
        "dec": raw.get("dec") if raw else None,
        "object_type": raw.get("object_type") if raw else None,
        "resolver": raw.get("resolver") if raw else None,
    }
    stmt = pg_insert(SesameCache).values(**values).on_conflict_do_update(
        index_elements=["query_name"],
        set_=values,
    )
    db_session.execute(stmt)


def resolve_sesame_cached(
    object_name: str, db_session,
) -> dict[str, Any] | None:
    """Resolve via SESAME with persistent DB cache. Sync for Celery workers.

    Returns curated dict compatible with target_resolver's _create_target,
    or None if unresolvable.
    """
    import asyncio
    from app.services.simbad import (
        normalize_object_name,
        curate_simbad_result,
    )

    normalized = normalize_object_name(object_name)

    # Check cache first
    cached = get_cached_sesame(normalized, db_session)
    if cached is not None:
        if cached.get("_negative"):
            return None
        return curate_simbad_result(cached)

    # Query SESAME (NED + VizieR only — skip SIMBAD since we already tried it)
    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(_query_sesame_raw(object_name, resolvers="NV"))
    finally:
        loop.close()

    # Cache the result (positive or negative)
    save_sesame_cache(normalized, raw, db_session)

    if raw is None:
        return None

    return curate_simbad_result(raw)
