"""CDS SESAME name resolver - fallback when SIMBAD direct query fails.

SESAME queries SIMBAD, NED, and VizieR behind a single endpoint.
We use it as a fallback to catch objects NED or VizieR can resolve
but SIMBAD's script interface cannot.

Docs: https://vizier.cds.unistra.fr/vizier/doc/sesame.htx
"""

import logging
import xml.etree.ElementTree as ET
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
    encoded_name = object_name.replace(" ", "+")
    url = f"{SESAME_URL}/-ox/{resolvers}?{encoded_name}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
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

    except (ET.ParseError, ValueError) as e:
        logger.warning("SESAME parse/value error for '%s': %s", object_name, e)
        return None


def get_cached_sesame(query_name: str, db_session) -> dict[str, Any] | None:
    """Look up a cached SESAME result. Returns raw dict or None (not in cache)."""
    from app.services import catalog_cache as cc

    cached = cc.get_cached(db_session, "sesame", query_name)
    if cached is cc.NEGATIVE:
        return {"_negative": True}
    return cached


def save_sesame_cache(
    query_name: str, raw: dict[str, Any] | None, db_session,
) -> None:
    """Persist a SESAME result (or negative) to the cache table."""
    from app.services import catalog_cache as cc

    cc.save_cached(db_session, "sesame", query_name, raw)


def resolve_sesame_cached(
    object_name: str, db_session,
) -> dict[str, Any] | None:
    """Resolve via SESAME with persistent DB cache. Sync for Celery workers.

    Returns curated dict compatible with target_resolver's _create_target,
    or None if unresolvable.

    Routed through catalog_cache's get_or_fetch so a transient SESAME
    failure (timeout, connection error, 5xx, 429) is retried with backoff
    and, if every attempt fails, negative-cached and swallowed (returns
    None) rather than propagating -- matching pre-port behavior for
    callers (api/merges.py's orphan_preview, the duplicate-detection
    worker task, filename_resolver.py, target_resolver.py) that never
    handled an exception from this function. A non-transient failure
    (a 4xx other than 429) raises NonTransientError uncaught, matching
    enrich_target_from_vizier/hyperleda/gaia.
    """
    from app.services import catalog_cache as cc
    from app.services.simbad import (
        normalize_object_name,
        curate_simbad_result,
    )

    normalized = normalize_object_name(object_name)

    def fetch() -> dict[str, Any] | None:
        # Query SESAME (NED + VizieR only - skip SIMBAD since we already
        # tried it). Own event loop since this runs on a sync/worker thread.
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _query_sesame_raw(object_name, resolvers="NV")
            )
        finally:
            loop.close()

    raw = cc.get_or_fetch(db_session, "sesame", normalized, fetch)

    if raw is None:
        return None

    return curate_simbad_result(raw)
